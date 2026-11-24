"""
Angekündigte Geschwindigkeitskontrollen der Polizei (bewegliche / halb-stationäre Messstellen) → mobile.json.gz

NUR amtliche Quellen der Polizei, einmal täglich abgefragt:
  SL  Landespolizeidirektion Saarland – Wochenvorschau, veröffentlicht über das Presseportal (Pressemitteilung "POL-SL:
      Geschwindigkeitskontrollen im Saarland … KW"): je Tag Straßenabschnitte / Orte
  SG  Kantonspolizei St.Gallen – Tabelle "Semistationäre Messanlagen" (sg.ch)
  SO  Polizei Kanton Solothurn – Tabelle "Semistationäre Anlagen" (so.ch); mobile Kontrollen werden dort NICHT veröffentlicht

Die Quellen nennen nur Straße/Ort, keine Koordinaten: Orte werden bei Nominatim (OSM) nachgeschlagen (Ergebnisse
zwischengespeichert, 1 Anfrage/s), Straßenabschnitte über die Straßengeometrie aus Overpass. Genauigkeit: einige hundert Meter.
Alle Angaben ohne Gewähr; die Polizei kann Kontrollen kurzfristig streichen oder zusätzlich durchführen.

Ausgabe: {"updated": ..., "z": [{"id","c","from","to","label","src","p": [[lat,lon], ...]}]}

Aufruf: python tools/build_mobile_checks.py OUTDIR
"""
import datetime, gzip, html, json, math, os, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guard

UA = "RoutenBegleiter-Daten (github.com/" + os.environ.get("GITHUB_REPOSITORY", "Kostasnik1/RoutenBegleiter-Daten") + ")"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]
TODAY = datetime.date.today()
DAYS = {"Montag": 0, "Dienstag": 1, "Mittwoch": 2, "Donnerstag": 3, "Freitag": 4, "Samstag": 5, "Sonntag": 6}


def get(url, data=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "de"})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def text_lines(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", "", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</tr>|</h[1-6]>|</div>", "\n", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    return [re.sub(r"\s+", " ", html.unescape(l)).strip() for l in h.split("\n") if l.strip()]


# ---------------------------------------------------------------- Geokodierung (mit Zwischenspeicher)

CACHE = {}
_last_nominatim = [0.0]


def geocode(q, cc):
    key = f"{cc}|{q}"
    if key in CACHE:
        return CACHE[key]
    wait = 1.2 - (time.time() - _last_nominatim[0])
    if wait > 0:
        time.sleep(wait)
    _last_nominatim[0] = time.time()
    res = None
    try:
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": q, "format": "json", "limit": 1, "countrycodes": cc})
        r = json.loads(get(url))
        if r:
            res = [float(r[0]["lat"]), float(r[0]["lon"])]
    except Exception as e:
        print(f"  Geokodierung '{q}': {e}", flush=True)
        return None            # Fehler nicht zwischenspeichern
    CACHE[key] = res
    return res


def dist(a, b):
    dy = (a[0] - b[0]) * 111_000
    dx = (a[1] - b[1]) * 111_000 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def thin(points, step):
    out = []
    for p in points:
        if not out or dist(out[-1], p) >= step:
            out.append(p)
    return out


OVERPASS_FAILS = [0]


def overpass(q):
    """Straßengeometrie holen. Ist Overpass überlastet (mehrere Fehlschläge in Folge), gibt es danach nur noch Näherungen,
    statt den ganzen Lauf auszubremsen."""
    if OVERPASS_FAILS[0] >= 6:
        return None
    for ep in OVERPASS:
        try:
            o = json.loads(get(ep, urllib.parse.urlencode({"data": q}).encode(), 50))
            if "elements" in o:
                OVERPASS_FAILS[0] = 0
                return o["elements"]
        except Exception as e:
            print(f"  Overpass {ep}: {e}", flush=True)
        OVERPASS_FAILS[0] += 1
        if OVERPASS_FAILS[0] >= 6:
            print("  Overpass überlastet – ab jetzt nur Näherungen", flush=True)
            return None
    return None


def road_points(refs, a, b=None, pad=0.04, corridor=2500):
    """Punkte der Straße [refs] (Liste möglicher ref-Schreibweisen) zwischen a und b (oder in der Nähe von a)."""
    s = min(a[0], (b or a)[0]) - pad; n = max(a[0], (b or a)[0]) + pad
    w = min(a[1], (b or a)[1]) - pad * 1.5; e = max(a[1], (b or a)[1]) + pad * 1.5
    rx = "|".join(re.escape(r) for r in refs)
    q = ('[out:json][timeout:90];way["highway"]["ref"~"(^|;)(%s)(;|$)"](%.4f,%.4f,%.4f,%.4f);out geom;' % (rx, s, w, n, e))
    els = overpass(q)
    if not els:
        return None
    pts = []
    for el in els:
        for g in el.get("geometry", []):
            pts.append([g["lat"], g["lon"]])
    if not pts:
        return None
    if b is not None:
        # nur Punkte, die zwischen den beiden Endpunkten liegen
        dx, dy = b[1] - a[1], b[0] - a[0]
        L2 = dx * dx + dy * dy or 1e-12
        keep = []
        for p in pts:
            t = ((p[1] - a[1]) * dx + (p[0] - a[0]) * dy) / L2
            if -0.05 <= t <= 1.05:
                proj = [a[0] + t * dy, a[1] + t * dx]
                if dist(p, proj) <= corridor:
                    keep.append((t, p))
        keep.sort()
        pts = [p for _, p in keep]
    else:
        pts = [p for p in pts if dist(p, a) <= corridor + 1500]
    return thin(pts, 300)[:80] or None


def line_between(a, b):
    n = max(2, int(dist(a, b) / 300))
    return [[a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n] for i in range(n + 1)][:80]


def rnd(points):
    return [[round(p[0], 5), round(p[1], 5)] for p in points]


# ---------------------------------------------------------------- Saarland

def clean_place(s):
    s = re.sub(r"^(?:dem|der|die)\s+", "", s.strip())
    s = re.sub(r"^(?:Autobahndreieck|Autobahnkreuz|Anschlussstelle|Anschlussstellen|AD|AK|AS)\s+", "", s)
    return s.strip(" .,;")


def saarland():
    zones = []
    rss = get("https://www.presseportal.de/rss/polizei/laender/13.rss2")
    items = ET.fromstring(rss).findall(".//item")
    wanted = [(it.findtext("title") or "", it.findtext("link") or "") for it in items]
    wanted = [(t, l) for t, l in wanted if "Geschwindigkeitskontrollen im Saarland" in t][:2]   # diese und nächste Woche
    if not wanted:
        raise RuntimeError("keine Saarland-Meldung im Presseportal-Feed")
    for title, link in wanted:
        raw = "\n".join(text_lines(get(link)))
        days = "Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag"
        raw = re.sub(r"\s+((?:%s),\s*[0-9]{2}\.[0-9]{2}\.[0-9]{4})" % days, r"\n\1", raw)
        raw = re.sub(r"\s+Hinweis:.*", "", raw, flags=re.S)       # alles ab dem Hinweis gehört nicht mehr zur Liste
        day = None
        for ln in raw.split("\n"):
            m = re.match(r"^(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag),\s*(\d\d)\.(\d\d)\.(\d{4})\s*$", ln)
            if m:
                day = datetime.date(int(m.group(4)), int(m.group(3)), int(m.group(2)))
                continue
            if day is None or not ln.startswith("-"):
                continue
            item = ln.lstrip("- ").strip()
            z = saar_item(item, day)
            if z:
                zones.append(z)
    return zones


def saar_item(item, day):
    m = re.match(r"^(BAB|A|B|L|K)\s*(\d+)\s*(?:neu\s+)?zwischen\s+(.+?)\s+und\s+(.+)$", item)
    if m:
        kind, num, p1, p2 = m.group(1), m.group(2), clean_place(m.group(3)), clean_place(m.group(4))
        ref = ("A" if kind == "BAB" else kind) + " " + num
        pts_ends = []
        for p in (p1, p2):
            if p.lower().startswith("landesgrenze"):
                continue
            g = geocode(f"{p}, Saarland, Deutschland", "de")
            if g:
                pts_ends.append(g)
        if not pts_ends:
            return None
        pts = road_points([ref, ref.replace(" ", "")], pts_ends[0], pts_ends[1] if len(pts_ends) > 1 else None)
        if not pts:
            pts = line_between(pts_ends[0], pts_ends[1]) if len(pts_ends) > 1 else pts_ends
        return zone("SL", "DE", day, f"{ref} zwischen {p1} und {p2}", "Landespolizeidirektion Saarland", pts)
    # "B 268 Losheim" / "L 118 Reiskirchen": Straße im Bereich eines Ortes
    m = re.match(r"^(BAB|A|B|L|K)\s*([0-9]+)\s+(?!zwischen)(.+)$", item)
    if m:
        ref = ("A" if m.group(1) == "BAB" else m.group(1)) + " " + m.group(2)
        ort = clean_place(m.group(3))
        g = geocode(f"{ort}, Saarland, Deutschland", "de")
        if g:
            pts = road_points([ref, ref.replace(" ", "")], g, None, pad=0.03, corridor=2500) or [g]
            return zone("SL", "DE", day, f"{ref} bei {ort}", "Landespolizeidirektion Saarland", pts)
        return None
    # "41 zwischen X und Y": die Quelle lässt hier das "B" weg
    m = re.match(r"^([0-9]{1,3})\s+zwischen\s+(.+?)\s+und\s+(.+)$", item)
    if m:
        return saar_item(f"B {m.group(1)} zwischen {m.group(2)} und {m.group(3)}", day)
    m = re.match(r"^in\s+(.+)$", item) or re.match(r"^((?:St\.|Sankt)?\s*[A-ZÄÖÜ][^0-9]*)$", item)
    if m:
        ort = clean_place(m.group(1))
        g = geocode(f"{ort}, Saarland, Deutschland", "de")
        if g:
            return zone("SL", "DE", day, f"Messung in {ort} (Stadtgebiet)", "Landespolizeidirektion Saarland", [g])
    print(f"  Saarland: nicht erkannt: {item}", flush=True)
    return None


# ---------------------------------------------------------------- Schweiz (St.Gallen, Solothurn)

def ch_street(gemeinde, ort, strasse, canton, src, cid):
    s = (strasse or "").strip()
    ref = re.search(r"Autobahn\s+(A\s?\d+)", s)
    center = geocode(f"{ort or gemeinde}, {gemeinde}, {canton}, Schweiz", "ch") or geocode(f"{gemeinde}, {canton}, Schweiz", "ch")
    if not center:
        return None
    day = TODAY
    if ref:
        r = ref.group(1).replace(" ", "")
        pts = road_points([r, r[0] + " " + r[1:]], center, None, pad=0.03, corridor=2500)
        label = f"Autobahn {r} bei {gemeinde}"
        if not pts:
            return None
        return zone(cid, "CH", day, label, src, pts, days=2)
    street = re.split(r"[,/]", s)[0].strip()
    g = geocode(f"{street}, {ort or gemeinde}, {gemeinde}, {canton}, Schweiz", "ch") or center
    return zone(cid, "CH", day, f"{street}, {gemeinde}", src, [g], days=2)


def table_rows(h):
    out = []
    for tr in re.findall(r"(?is)<tr.*?</tr>", h):
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", c))).strip()
                 for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", tr)]
        if cells:
            out.append(cells)
    return out


def sankt_gallen():
    h = get("https://www.sg.ch/sicherheit/kantonspolizei/verkehr/radar.html")
    zones = []
    for i, c in enumerate(table_rows(h)):
        if len(c) >= 3 and c[0] != "Gemeinde":
            z = ch_street(c[0], c[1], c[2], "St. Gallen", "Kantonspolizei St.Gallen", "SG")
            if z:
                z["id"] += f"-{i}"; zones.append(z)
    return zones


def solothurn():
    h = get("https://so.ch/verwaltung/departement-des-innern/polizei/praevention/verkehr/radarstandorte/")
    # nur die Tabelle "Semistationäre Anlagen" (die stationären stehen schon in OpenStreetMap)
    start = h.find("Semistation")
    end = h.find("Stationäre Anlagen", start + 20)
    part = h[start:end if end > start else len(h)]
    zones = []
    for i, c in enumerate(table_rows(part)):
        if len(c) >= 2 and c[0] != "Gemeinde" and "ausser Betrieb" not in c[1]:
            z = ch_street(c[0], "", c[1], "Solothurn", "Polizei Kanton Solothurn", "SO")
            if z:
                z["id"] += f"-{i}"; zones.append(z)
    return zones


def zone(prefix, country, day, label, src, pts, days=1):
    return {"id": f"{prefix}-{day:%Y%m%d}", "c": country, "from": day.isoformat(),
            "to": (day + datetime.timedelta(days=days - 1)).isoformat(), "label": label, "src": src, "p": rnd(pts)}


# ---------------------------------------------------------------- Hauptprogramm

def main(out):
    os.makedirs(out, exist_ok=True)
    prev = guard.previous("geocache.json")
    if isinstance(prev, dict):
        CACHE.update({k: v for k, v in prev.items()})
    zones, failed = [], 0
    for name, fn in (("Saarland", saarland), ("St.Gallen", sankt_gallen), ("Solothurn", solothurn)):
        try:
            z = fn()
            print(f"{name}: {len(z)} Messstellen", flush=True)
            zones += z
        except Exception as e:
            failed += 1
            print(f"::warning::{name}: {e}", flush=True)
    if failed == 3:
        sys.exit("keine Quelle erreichbar – alter Stand bleibt")
    # Doppelte IDs vermeiden (mehrere Messstellen am selben Tag)
    seen = {}
    for z in zones:
        n = seen.get(z["id"], 0); seen[z["id"]] = n + 1
        z["id"] = f'{z["id"]}-{n}'
    data = {"updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "info": "Angekündigte Messstellen der Polizei (Saarland, St.Gallen, Solothurn). Ohne Gewähr.", "z": zones}
    with gzip.open(os.path.join(out, "mobile.json.gz"), "wt", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
    with open(os.path.join(out, "geocache.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in CACHE.items() if v is not None}, f, ensure_ascii=False)
    print(f"mobile.json.gz: {len(zones)} Messstellen")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out")
