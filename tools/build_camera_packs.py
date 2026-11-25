"""
Blitzer-Standorte je Land aus OpenStreetMap (Overpass), klein und schnell – täglich neu, unabhängig von den großen
Toiletten-Paketen (poi-XX).

Ausgabe: cameras-<ISO>.json.gz  {"country": "DE", "updated": "...", "c": [[id, lat, lon, maxspeed|null, kind], ...]}
kind: fixed | average | redlight | mobile
Quelle: © OpenStreetMap-Mitwirkende, ODbL 1.0 (node["highway"="speed_camera"]).

Aufruf: python tools/build_camera_packs.py OUTDIR [ISO ...]   (ohne ISO: alle Länder der App)
Eine Datei wird nur ersetzt, wenn sie plausibel ist (tools/guard.py); schlägt ein Land fehl, bleibt der alte Stand.
"""
import datetime, gzip, json, os, re, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guard

COUNTRIES = ("DE AT CH LI FR IT ES NL BE LU PL CZ SK HU SI HR DK PT GR BG RO RS BA ME AL MK MD TR GB IE NO SE FI EE LV LT").split()
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter"]
UA = "RoutenBegleiter-Daten (github.com/" + os.environ.get("GITHUB_REPOSITORY", "Kostasnik1/RoutenBegleiter-Daten") + ")"


def query(iso):
    q = ('[out:json][timeout:100];area["ISO3166-1"="%s"]["admin_level"="2"]->.a;'
         'node(area.a)["highway"="speed_camera"];out;' % iso)
    last = None
    for ep in ENDPOINTS:
        try:
            req = urllib.request.Request(ep, data=urllib.parse.urlencode({"data": q}).encode(), headers={"User-Agent": UA})
            o = json.loads(urllib.request.urlopen(req, timeout=130).read())
            if "elements" in o:
                return o["elements"]
        except Exception as e:
            last = e
            print(f"  {iso}: {ep}: {e}", flush=True)
        time.sleep(5)
    raise RuntimeError(f"{iso}: Overpass nicht erreichbar ({last})")


def kind(tags):
    enf = (tags.get("enforcement") or "").lower()
    if "traffic_signals" in enf or "red_light" in enf:
        return "redlight"
    if "average" in enf:
        return "average"
    if tags.get("camera:type") == "mobile" or "mobile" in enf:
        return "mobile"
    return "fixed"


def maxspeed(tags):
    m = re.search(r"[0-9]{2,3}", tags.get("maxspeed") or "")
    return int(m.group(0)) if m else None


def build(iso, out):
    els = query(iso)
    rows = [[e["id"], round(e["lat"], 6), round(e["lon"], 6), maxspeed(e.get("tags", {})), kind(e.get("tags", {}))]
            for e in els if e.get("type") == "node" and "lat" in e]
    name = f"cameras-{iso}.json.gz"
    ok, msg = guard.plausible(name, len(rows), lambda d: len(d.get("c", [])))
    print(f"{iso}: {msg}", flush=True)
    if not ok or not rows:
        return False
    data = {"country": iso, "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "source": "OpenStreetMap (ODbL)", "c": rows}
    with gzip.open(os.path.join(out, name), "wt", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    return True


if __name__ == "__main__":
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    want = sys.argv[2:] or COUNTRIES
    if not sys.argv[2:]:
        # Reihenfolge rotiert mit jedem Lauf (alle 6 Stunden eine andere Startposition), damit auch bei Zeitbudget
        # und überlastetem Overpass jedes Land regelmäßig drankommt
        k = (int(time.time() // 21600) * 9) % len(want)
        want = want[k:] + want[:k]
    done = 0
    budget = float(os.environ.get("BUDGET_MIN", "75")) * 60
    t0 = time.time()
    for i, iso in enumerate(want):
        if time.time() - t0 > budget:
            print(f"::warning::Zeitbudget erreicht – übrige Länder ({' '.join(want[i:])}) kommen beim nächsten Lauf", flush=True)
            break
        try:
            done += bool(build(iso, out))
        except Exception as e:
            print(f"::warning::{iso}: {e}", flush=True)
        time.sleep(8)   # Overpass schonen
    print(f"{done} von {len(want)} Paketen gebaut")
    if done == 0:
        sys.exit("kein Paket gebaut")
