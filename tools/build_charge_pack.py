#!/usr/bin/env python3
"""
Offline-Paket "Ladesäulen" für ein Land (nur geladen, wenn in der App „Ladesäulen“ eingeschaltet ist).

Eingabe: GeoJSON-Sequence aus
  osmium tags-filter <land>.osm.pbf nwr/amenity=charging_station -o charge.osm.pbf
  osmium export charge.osm.pbf -f geojsonseq --add-unique-id=type_id -o charge.geojsonseq

Ausgabe: charge-<ISO>.json.gz
  {"country": "DE", "updated": "...", "e": [[id, lat, lon, name, operator, kw, flags, capacity, fee, opening], ...]}
  flags: Bit 1 = CCS, 2 = Typ 2, 4 = CHAdeMO, 8 = Tesla
  Private/gesperrte und reine Fahrrad-Ladepunkte werden weggelassen.

Aufruf: python tools/build_charge_pack.py DE charge.geojsonseq charge-DE.json.gz
"""
import datetime, os, gzip, json, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guard
from build_poi_pack import center

NUM = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kW|W|kVA)?", re.I)


def kw(s):
    best = None
    for m in NUM.finditer(s or ""):
        v = float(m.group(1).replace(",", "."))
        u = (m.group(2) or "").lower()
        v = v / 1000 if u == "w" or (not u and v > 1000) else v
        if 2 <= v <= 1000:
            best = max(best or 0, v)
    return best


def has(p, k):
    v = p.get(k)
    return bool(v) and v not in ("no", "0")


def main(iso, src, dst):
    out = []
    with open(src, encoding="utf-8") as f:
        for line in f:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            ft = json.loads(line)
            p = ft.get("properties", {})
            if p.get("amenity") != "charging_station" or p.get("motorcar") == "no":
                continue
            if p.get("access") in ("private", "no") or (p.get("bicycle") == "yes" and not p.get("motorcar")):
                continue
            lat, lon = center(ft["geometry"])
            uid = str(ft.get("id", "n0"))
            n = int(re.sub(r"\D", "", uid) or 0)
            oid = n if uid.startswith("n") else (n + 3_600_000_000_000 if uid.startswith("r") else n + 2_400_000_000_000)
            outs = [kw(v) for k, v in p.items() if k.endswith(":output") or k == "maxpower"]
            power = max([o for o in outs if o] or [0]) or None
            flags = (1 if has(p, "socket:type2_combo") else 0) | (2 if has(p, "socket:type2") or has(p, "socket:type2_cable") else 0) \
                | (4 if has(p, "socket:chademo") else 0) | (8 if has(p, "socket:tesla_supercharger") or "tesla" in (p.get("brand") or "").lower() else 0)
            name = p.get("name") or p.get("brand") or p.get("operator") or ""
            cap = p.get("capacity")
            out.append([oid, round(lat, 6), round(lon, 6), name, p.get("operator", ""), power, flags,
                        int(cap) if cap and cap.isdigit() else None, p.get("fee"), p.get("opening_hours")])
    ok, msg = guard.plausible(f"charge-{iso}.json.gz", len(out), lambda d: len(d.get("e", [])))
    if not ok:
        sys.exit(f"{iso}: {msg} – Paket wird nicht ersetzt")
    data = {"country": iso, "updated": datetime.date.today().isoformat(), "source": "© OpenStreetMap-Mitwirkende (ODbL)", "e": out}
    with gzip.open(dst, "wt", encoding="utf-8") as g:
        json.dump(data, g, ensure_ascii=False, separators=(",", ":"))
    print(f"{iso}: {len(out)} Ladestationen -> {dst}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
