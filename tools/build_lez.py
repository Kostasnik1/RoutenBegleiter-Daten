#!/usr/bin/env python3
"""
Umweltzonen (boundary=low_emission_zone) aus OpenStreetMap → lez.json.gz für die App.

Schritt 1 je Land (im OSM-Paket-Job, aus dem bereits geladenen Geofabrik-Auszug):
  osmium tags-filter land.osm.pbf nwr/boundary=low_emission_zone -o lez.osm.pbf
  osmium export lez.osm.pbf -f geojsonseq --geometry-types=polygon --add-unique-id=type_id -o lez.geojsonseq
  python tools/build_lez.py country DE lez.geojsonseq lez-DE.json

Schritt 2 (alle Länder zusammenführen; Länder ohne neues Ergebnis behalten ihre bisherigen Zonen):
  python tools/build_lez.py merge <ordner mit lez-*.json> lez.json.gz

Format: {"updated","source","zones":[{"id","c","n","bb":[s,w,n,e],"r":[[lat,lon,lat,lon,…], …],"t":{…}}]}
"""
import datetime, glob, gzip, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guard

KEEP = ("website", "url", "contact:website", "start_date", "description", "access:note", "motor_vehicle:conditional",
        "opening_hours", "short_name", "operator")


def rdp(pts, eps):
    """Douglas-Peucker: Polygon vereinfachen (≈50 m Toleranz reichen für eine Warnung völlig)."""
    if len(pts) < 4:
        return pts
    stack, keep = [(0, len(pts) - 1)], {0, len(pts) - 1}
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        n = (dx * dx + dy * dy) ** 0.5 or 1e-12
        best, idx = 0, None
        for i in range(a + 1, b):
            px, py = pts[i]
            d = abs(dy * px - dx * py + bx * ay - by * ax) / n
            if d > best:
                best, idx = d, i
        if idx is not None and best > eps:
            keep.add(idx)
            stack += [(a, idx), (idx, b)]
    return [pts[i] for i in sorted(keep)]


def outer_rings(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [p[0] for p in geom["coordinates"]]
    return []


def country(iso, src, dst):
    zones = []
    with open(src, encoding="utf-8") as f:
        for line in f:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            ft = json.loads(line)
            p = ft.get("properties", {})
            rings = []
            for ring in outer_rings(ft["geometry"]):
                r = rdp([(c[0], c[1]) for c in ring], 0.0005)
                if len(r) >= 4:
                    rings.append([v for lon, lat in r for v in (round(lat, 5), round(lon, 5))])
            if not rings:
                continue
            lats = [r[i] for r in rings for i in range(0, len(r), 2)]
            lons = [r[i] for r in rings for i in range(1, len(r), 2)]
            zones.append({"id": str(ft.get("id", "")), "c": iso, "n": p.get("name") or p.get("short_name") or "",
                          "bb": [min(lats), min(lons), max(lats), max(lons)], "r": rings,
                          "t": {k: p[k][:300] for k in KEEP if k in p}})
    # unbenannte Teilflächen weglassen, wenn eine benannte Zone dieselbe Gegend abdeckt
    named = [z for z in zones if z["n"]]
    def inside(a, b):
        return a["bb"][0] >= b["bb"][0] - 0.01 and a["bb"][1] >= b["bb"][1] - 0.01 and a["bb"][2] <= b["bb"][2] + 0.01 and a["bb"][3] <= b["bb"][3] + 0.01
    zones = named + [z for z in zones if not z["n"] and not any(inside(z, n) for n in named)]
    json.dump({"country": iso, "zones": zones}, open(dst, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"{iso}: {len(zones)} Umweltzonen ({len(named)} mit Namen)")


def merge(folder, dst):
    new = {}
    for f in glob.glob(os.path.join(folder, "**", "lez-*.json"), recursive=True):
        d = json.load(open(f, encoding="utf-8"))
        new[d["country"]] = d["zones"]
    prev = guard.previous("lez.json.gz") or {"zones": []}
    kept = [z for z in prev.get("zones", []) if z["c"] not in new]   # Land diesmal fehlgeschlagen → alte Zonen behalten
    zones = kept + [z for zs in new.values() for z in zs]
    ok, msg = guard.plausible("lez.json.gz", len(zones), lambda d: len(d.get("zones", [])), 0.7)
    if not ok:
        sys.exit(msg)
    doc = {"updated": datetime.date.today().isoformat(), "source": "© OpenStreetMap-Mitwirkende (ODbL), boundary=low_emission_zone",
           "zones": zones}
    with gzip.open(dst, "wt", encoding="utf-8") as g:
        json.dump(doc, g, ensure_ascii=False, separators=(",", ":"))
    by = {}
    for z in zones:
        by[z["c"]] = by.get(z["c"], 0) + 1
    print(f"{len(zones)} Zonen ({msg}): " + ", ".join(f"{k} {v}" for k, v in sorted(by.items())))


if __name__ == "__main__":
    {"country": country, "merge": merge}[sys.argv[1]](*sys.argv[2:])
