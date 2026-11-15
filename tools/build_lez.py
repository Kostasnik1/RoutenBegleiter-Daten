#!/usr/bin/env python3
"""
Umweltzonen (boundary=low_emission_zone) aus OpenStreetMap → lez.json.gz für die App.

Schritt 1 je Land (im OSM-Paket-Job, aus dem bereits geladenen Geofabrik-Auszug):
  osmium tags-filter land.osm.pbf nwr/boundary=low_emission_zone -o lez.osm.pbf
  python tools/build_lez.py country DE lez.osm.pbf lez-DE.json        (braucht pyosmium)

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
    if pts[0] == pts[-1]:
        # geschlossener Ring: an dem vom Start am weitesten entfernten Punkt teilen (sonst ist die Bezugslinie ein Punkt)
        k = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
        if 0 < k < len(pts) - 1:
            return rdp(pts[:k + 1], eps)[:-1] + rdp(pts[k:], eps)
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


def join_rings(segments):
    """Wege (Koordinatenlisten) an gemeinsamen Endpunkten zu geschlossenen Ringen verbinden."""
    segs = [list(x) for x in segments if len(x) >= 2]
    rings = []
    while segs:
        cur = segs.pop(0)
        changed = True
        while cur[0] != cur[-1] and changed:
            changed = False
            for i, sg in enumerate(segs):
                if sg[0] == cur[-1]:
                    cur += sg[1:]
                elif sg[-1] == cur[-1]:
                    cur += sg[::-1][1:]
                elif sg[-1] == cur[0]:
                    cur = sg[:-1] + cur
                elif sg[0] == cur[0]:
                    cur = sg[::-1][:-1] + cur
                else:
                    continue
                segs.pop(i)
                changed = True
                break
        if cur[0] == cur[-1] and len(cur) >= 4:
            rings.append(cur)
    return rings


def read_osm(src):
    """Zonen aus einer OSM-Datei (pbf/xml): geschlossene Wege und Relationen (Ringe selbst zusammengesetzt).
    osmium export erzeugt aus boundary-Relationen keine Flächen – daher eigene, einfache Ring-Bildung."""
    import osmium

    class H(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.ways, self.wtags, self.rels = {}, {}, []

        def way(self, w):
            try:
                self.ways[w.id] = [(round(n.lon, 6), round(n.lat, 6)) for n in w.nodes]
            except osmium.InvalidLocationError:
                return
            if w.tags.get("boundary") == "low_emission_zone":
                self.wtags[w.id] = dict(w.tags)

        def relation(self, r):
            if r.tags.get("boundary") == "low_emission_zone":
                self.rels.append((r.id, dict(r.tags), [m.ref for m in r.members if m.type == "w" and m.role in ("outer", "")]))

    h = H()
    h.apply_file(src, locations=True)
    used = set()
    out = []
    for rid, tags, members in h.rels:
        rings = join_rings([h.ways[m] for m in members if m in h.ways])
        used.update(members)
        if rings:
            out.append((f"r{rid}", tags, rings))
    for wid, tags in h.wtags.items():
        c = h.ways.get(wid)
        if wid in used and not tags.get("name"):
            continue          # unbenannter Teil einer Relation
        if c and len(c) >= 4 and c[0] == c[-1]:
            out.append((f"w{wid}", tags, [c]))
    return out


def country(iso, src, dst):
    zones = []
    for oid, p, rings_raw in read_osm(src):
        rings = []
        for ring in rings_raw:
            r = rdp(ring, 0.0005)
            if len(r) >= 4:
                rings.append([v for lon, lat in r for v in (round(lat, 5), round(lon, 5))])
        if not rings:
            continue
        lats = [r[i] for r in rings for i in range(0, len(r), 2)]
        lons = [r[i] for r in rings for i in range(1, len(r), 2)]
        zones.append({"id": oid, "c": iso, "n": p.get("name") or p.get("short_name") or "",
                      "bb": [min(lats), min(lons), max(lats), max(lons)], "r": rings,
                      "t": {k: p[k][:300] for k in KEEP if k in p}})
    # reine Lkw-/Mofa-/Rad-Zonen sind für Autos ohne Belang
    zones = [z for z in zones if not re.search(r"LKW|Lkw|hgv|brom|snorfiets|Fahrrad", z["n"])]
    # gleichnamige Teile (z. B. mehrere Flächen einer Stadt) zu einer Zone zusammenfassen
    by = {}
    for z in zones:
        if z["n"] and z["n"] in by:
            o = by[z["n"]]
            o["r"] += z["r"]
            o["bb"] = [min(o["bb"][0], z["bb"][0]), min(o["bb"][1], z["bb"][1]), max(o["bb"][2], z["bb"][2]), max(o["bb"][3], z["bb"][3])]
        else:
            by[z["n"] or z["id"]] = z
    zones = list(by.values())
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
