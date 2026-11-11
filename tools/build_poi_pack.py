#!/usr/bin/env python3
"""
Erzeugt ein Offline-Paket "Toiletten & Rastplätze" für ein Land aus einem OpenStreetMap-Auszug.

Eingabe: GeoJSON-Sequence aus
  osmium tags-filter <land>.osm.pbf nwr/amenity=toilets nwr/highway=rest_area,services nwr/amenity=fast_food \
      nwr/toilets:fee=no n/highway=speed_camera -o filtered.osm.pbf
  osmium export filtered.osm.pbf -f geojsonseq --add-unique-id=type_id -o filtered.geojsonseq

Ausgabe: poi-<ISO>.json.gz  {"country": "DE", "updated": "...", "e": [[id, lat, lon, {tags}], ...]}
(id: Knoten positiv, Wege/Relationen mit Offset, damit sie nicht mit Knoten kollidieren – wie in der App)

Aufruf: python tools/build_poi_pack.py DE filtered.geojsonseq poi-DE.json.gz
"""
import datetime, gzip, json, re, sys

KEEP = ["name", "brand", "operator", "fee", "toilets:fee", "toilets", "toilets:wheelchair", "amenity", "highway",
        "opening_hours", "wheelchair", "access", "charge", "maxspeed", "changing_table"]
CHAINS = re.compile(r"mcdonald|burger king", re.I)
GASTRO = {"restaurant", "cafe", "fast_food", "pub", "bar", "biergarten"}


def center(geom):
    t, c = geom["type"], geom["coordinates"]
    if t == "Point":
        return c[1], c[0]
    pts = []
    def walk(x):
        if isinstance(x[0], (int, float)):
            pts.append(x)
        else:
            for y in x:
                walk(y)
    walk(c)
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)


def main(iso, src, dst):
    out = []
    with open(src, encoding="utf-8") as f:
        for line in f:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            ft = json.loads(line)
            p = ft.get("properties", {})
            am, hw = p.get("amenity"), p.get("highway")
            keep = (am == "toilets" or hw in ("rest_area", "services", "speed_camera")
                    or (am == "fast_food" and CHAINS.search((p.get("brand") or "") + " " + (p.get("name") or "")))
                    or (am in GASTRO and p.get("toilets:fee") == "no"))
            if not keep or hw == "rest_area" and p.get("toilets") == "no":
                continue
            lat, lon = center(ft["geometry"])
            uid = str(ft.get("id", "n0"))
            n = int(re.sub(r"\D", "", uid) or 0)
            oid = n if uid.startswith("n") else (n + 3_600_000_000_000 if uid.startswith("r") else n + 2_400_000_000_000)
            out.append([oid, round(lat, 6), round(lon, 6), {k: p[k] for k in KEEP if k in p}])
    data = {"country": iso, "updated": datetime.date.today().isoformat(), "source": "© OpenStreetMap-Mitwirkende (ODbL)", "e": out}
    with gzip.open(dst, "wt", encoding="utf-8") as g:
        json.dump(data, g, ensure_ascii=False, separators=(",", ":"))
    print(f"{iso}: {len(out)} Einträge -> {dst}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
