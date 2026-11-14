#!/usr/bin/env python3
"""
Amtliche Spritpreise je Tankstelle für Länder, deren Behörden nur Komplett-Listen anbieten
(zu groß fürs Handy) → kompakte Pakete fuel-<ISO>.json.gz für die App.

  ES  Ministerio para la Transición Ecológica (Geoportal Gasolineras)
  IT  MIMIT – Osservatorio prezzi carburanti (täglich)
  PT  DGEG – Preços dos combustíveis
  HR  Ministarstvo gospodarstva (mzoe-gor.hr)
  FR  prix-carburants (roulez-eco.fr) – nur als Ersatz, falls die Live-Schnittstelle ausfällt

Format: {"country","updated","source","s":[[id, lat, lon, name, brand, e5, diesel, lpg, "YYYY-MM-DD HH:MM"]]}
Aufruf: python tools/fuel_packs.py <ausgabeordner> [ES IT PT HR FR]
Veröffentlicht wird nur, was plausibel ist (Mindestanzahl, Vergleich mit der Vorversion, Preisniveau).
"""
import csv, datetime, gzip, io, json, os, statistics, subprocess, sys, time, urllib.request, zipfile
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guard

sys.stdout.reconfigure(encoding="utf-8")

UA = "Mozilla/5.0 (X11; Linux x86_64) RoutenBegleiter-Daten"


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=180) as r:
                b = r.read()
                return gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b
        except Exception as e:
            print("  Fehler", url, e, flush=True)
            time.sleep(10 * (i + 1))
    # Rückfall: curl (manche Server brechen Python-TLS-Verbindungen ab)
    try:
        b = subprocess.run(["curl", "-sSfL", "--compressed", "-m", "300", url], capture_output=True, check=True).stdout
        return gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b
    except Exception as e:
        raise RuntimeError(f"nicht erreichbar: {url} ({e})")


def num(x):
    """Preis in €/l, unplausible Werte → None."""
    try:
        v = float(str(x).replace(",", ".").replace("€", "").strip())
        return round(v, 3) if 0.3 < v < 5 else None
    except ValueError:
        return None


def coord(x):
    try:
        return round(float(str(x).replace(",", ".")), 6)
    except ValueError:
        return None


def es():
    d = json.loads(get("https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/"))
    ts = datetime.datetime.strptime(d["Fecha"], "%d/%m/%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M")
    out = []
    for s in d["ListaEESSPrecio"]:
        lat, lon = coord(s["Latitud"]), coord(s["Longitud (WGS84)"])
        if lat is None or lon is None:
            continue
        e5 = num(s.get("Precio Gasolina 95 E5")) or num(s.get("Precio Gasolina 95 E10"))
        out.append(["ES-" + s["IDEESS"], lat, lon, s.get("Rótulo", ""), s.get("Rótulo", ""), e5,
                    num(s.get("Precio Gasoleo A")), num(s.get("Precio Gases licuados del petróleo")), ts])
    return out, "Ministerio para la Transición Ecológica (geoportalgasolineras.es)"


def it():
    base = "https://www.mimit.gov.it/images/exportCSV/"
    reg = get(base + "anagrafica_impianti_attivi.csv").decode("utf-8", "replace").splitlines()
    pri = get(base + "prezzo_alle_8.csv").decode("utf-8", "replace").splitlines()
    st = {}
    for r in csv.reader(reg[2:], delimiter="|"):
        if len(r) >= 10 and coord(r[8]) is not None and coord(r[9]) is not None:
            st[r[0]] = {"lat": coord(r[8]), "lon": coord(r[9]), "name": r[4], "brand": r[2], "p": {}, "self": {}, "t": ""}
    for r in csv.reader(pri[2:], delimiter="|"):
        if len(r) < 5 or r[0] not in st:
            continue
        kind, v, self_ = r[1].strip().lower(), num(r[2]), r[3] == "1"
        key = {"benzina": "e5", "gasolio": "diesel", "gpl": "lpg"}.get(kind)
        if not key or v is None:
            continue
        s = st[r[0]]
        # Self-Service bevorzugen (Bedienung kostet in Italien oft 20–40 ct mehr)
        if self_:
            s["self"][key] = min(v, s["self"].get(key, 9))
        else:
            s["p"][key] = min(v, s["p"].get(key, 9))
        try:
            s["t"] = max(s["t"], datetime.datetime.strptime(r[4], "%d/%m/%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M"))
        except ValueError:
            pass
    out = []
    for k, s in st.items():
        p = {**s["p"], **s["self"]}
        if p and abs(s["lat"]) > 1:
            out.append(["IT-" + k, s["lat"], s["lon"], s["name"], s["brand"], p.get("e5"), p.get("diesel"), p.get("lpg"), s["t"]])
    return out, "MIMIT – Osservatorio prezzi carburanti (mimit.gov.it)"


def pt():
    out = {}
    for comb, idx in ((3201, 5), (2101, 6), (1120, 7)):   # Gasolina 95, Gasóleo simples, GPL Auto
        d = json.loads(get(f"https://precoscombustiveis.dgeg.gov.pt/api/PrecoComb/PesquisarPostos?idsTiposComb={comb}&qtdPorPagina=20000&pagina=1"))
        for s in d.get("resultado") or []:
            r = out.setdefault(s["Id"], ["PT-%d" % s["Id"], s["Latitude"], s["Longitude"], s["Nome"], s.get("Marca") or "", None, None, None, ""])
            r[idx] = num(s.get("Preco"))
            r[8] = max(r[8], s.get("DataAtualizacao") or "")
    return [r for r in out.values() if r[1] and r[2]], "DGEG – Direção-Geral de Energia e Geologia (precoscombustiveis.dgeg.gov.pt)"


def hr():
    d = json.loads(get("https://mzoe-gor.hr/data.gz"))
    kind = {g["id"]: g["tip_goriva_id"] for g in d["vrsta_gorivas"]}          # 1 Benzin, 2 Diesel, 3 Autoplin
    gor = {g["id"]: (kind.get(g["vrsta_goriva_id"]), g["naziv"] or "") for g in d["gorivos"]}
    brand = {o["id"]: o["naziv"] for o in d["obvezniks"]}
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    out = []
    for s in d["postajas"]:
        a, b = coord(s["long"]), coord(s["lat"])
        if a is None or b is None:
            continue
        lat, lon = max(a, b), min(a, b)   # in den Daten sind lat/long vertauscht; Kroatien: Breite 42–46.6 > Länge 13.4–19.5
        p = {}
        for c in s["cjenici"]:
            t, name = gor.get(c["gorivo_id"], (None, ""))
            key, v = {1: "e5", 2: "diesel", 3: "lpg"}.get(t), num(c["cijena"])
            if key == "e5" and "100" in name:
                continue                    # Super 100 nicht als normales Benzin werten
            if key and v and v < p.get(key, 9):
                p[key] = v
        if p:
            out.append(["HR-%d" % s["id"], lat, lon, s["naziv"], brand.get(s["obveznik_id"], ""), p.get("e5"), p.get("diesel"), p.get("lpg"), now])
    return out, "Ministarstvo gospodarstva RH (mzoe-gor.hr)"


def fr():
    """Komplettliste Frankreich (ZIP mit XML, ~1 MB) – Ersatz für die Umkreis-Abfrage der App."""
    z = zipfile.ZipFile(io.BytesIO(get("https://donnees.roulez-eco.fr/opendata/instantane")))
    root = ET.fromstring(z.read(z.namelist()[0]))
    out = []
    for p in root.iter("pdv"):
        try:
            lat, lon = int(p.get("latitude")) / 100000, int(p.get("longitude")) / 100000
        except (TypeError, ValueError):
            continue
        if not (41 < lat < 52 and -6 < lon < 10):
            continue
        pr, ts = {}, ""
        for x in p.iter("prix"):
            pr[x.get("nom")] = num(x.get("valeur"))
            ts = max(ts, (x.get("maj") or "")[:16])
        e5 = pr.get("SP95") or pr.get("E10")
        if e5 or pr.get("Gazole"):
            out.append(["FR-" + p.get("id"), round(lat, 6), round(lon, 6), (p.findtext("ville") or "").strip(), "",
                        e5, pr.get("Gazole"), pr.get("GPLc"), ts])
    return out, "prix-carburants (Ministère de l'Économie) über roulez-eco.fr"


def sane(rows):
    """Preisniveau muss stimmen (sonst z. B. Cent statt Euro oder vertauschte Spalten)."""
    for idx in (5, 6):
        v = [r[idx] for r in rows if r[idx]]
        if len(v) > 50 and not 0.8 < statistics.median(v) < 3.5:
            return f"Median {statistics.median(v):.3f} €/l unplausibel"
    return None


def main(dst, *codes):
    os.makedirs(dst, exist_ok=True)
    fns = {"ES": es, "IT": it, "PT": pt, "HR": hr, "FR": fr}
    codes = codes or tuple(fns)
    ok = 0
    for c in codes:
        try:
            rows, src = fns[c]()
        except Exception as e:
            print(f"{c}: FEHLER {e}", flush=True)
            continue
        if len(rows) < 100:
            print(f"{c}: nur {len(rows)} Tankstellen – Paket nicht ersetzt", flush=True)
            continue
        bad = sane(rows)
        okp, msg = guard.plausible(f"fuel-{c}.json.gz", len(rows), lambda d: len(d.get("s", [])))
        if bad or not okp:
            print(f"{c}: {bad or msg} – Paket nicht ersetzt", flush=True)
            continue
        doc = {"country": c, "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "source": src, "s": rows}
        path = os.path.join(dst, f"fuel-{c}.json.gz")
        with gzip.open(path, "wt", encoding="utf-8") as g:
            json.dump(doc, g, ensure_ascii=False, separators=(",", ":"))
        ok += 1
        print(f"{c}: {len(rows)} Tankstellen, {os.path.getsize(path) // 1024} KB", flush=True)
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main(*sys.argv[1:])
