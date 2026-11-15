#!/usr/bin/env python3
"""
Täglicher Gesundheits-Check aller Datenquellen der App – inklusive der Ersatz-Anbieter.

Jede Quelle wird mit einer echten, kleinen Abfrage geprüft, und zwar genau auf die Felder, die die App ausliest.
Ändert ein Anbieter sein Format oder fällt aus, steht das am nächsten Morgen in health.json (zeigt die App an)
und als GitHub-Issue "Datenquellen-Störung" (GitHub schickt dazu eine E-Mail).

Die Adressen kommen aus data/config.json – also genau die, die auch die App benutzt.
Aufruf: python tools/health_check.py data/config.json <ausgabeordner>
"""
import datetime, gzip, io, json, os, sys, time, urllib.parse, urllib.request, zipfile

sys.stdout.reconfigure(encoding="utf-8")
UA = "RoutenBegleiter-Daten/1.0 (health check)"
REPO = os.environ.get("GITHUB_REPOSITORY", "Kostasnik1/RoutenBegleiter-Daten")
FFM, MUC = (50.1109, 8.6821), (48.1374, 11.5755)
# Mindestgröße je Datei (KB) – fängt leere/abgeschnittene Pakete ab
MIN_KB = {"fuel-ES.json.gz": 100, "fuel-PT.json.gz": 40, "fuel-HR.json.gz": 8, "fuel-FR.json.gz": 100, "countries.json": 20,
          "vignettes.json": 3, "lez.json.gz": 20, "poi-DE.json.gz": 500}


def fetch(url, data=None, headers=None, timeout=60):
    h = {"User-Agent": UA, "Accept-Encoding": "gzip"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
    return gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b


def js(url, **kw):
    return json.loads(fetch(url, **kw))


def need(cond, msg):
    if not cond:
        raise AssertionError(msg)


def age_h(iso):
    t = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 3600


def checks(cfg):
    u = cfg["urls"]
    c = {}

    # ---------- Routing (gewählter Anbieter → OSRM-Server → Valhalla) ----------
    for i, base in enumerate(u["route.osrm"]):
        def osrm(base=base):
            o = js(f"{base}/route/v1/driving/{FFM[1]},{FFM[0]};{MUC[1]},{MUC[0]}?overview=false&steps=true&geometries=polyline6")
            need(o.get("code") == "Ok", o.get("code"))
            r = o["routes"][0]
            need(r["legs"][0]["steps"][0]["geometry"], "keine Geometrie")
            need(300_000 < r["distance"] < 500_000, f"Strecke {r['distance']} m unplausibel")
            return f"{r['distance'] / 1000:.0f} km"
        c[f"route.osrm.{i + 1}"] = (f"Routing OSRM ({urllib.parse.urlparse(base).netloc})", osrm)
    for base in u["route.valhalla"]:
        def valhalla(base=base):
            q = {"locations": [{"lat": FFM[0], "lon": FFM[1]}, {"lat": MUC[0], "lon": MUC[1]}], "costing": "auto", "units": "kilometers"}
            o = js(f"{base}/route?json=" + urllib.parse.quote(json.dumps(q)))
            leg = o["trip"]["legs"][0]
            need(leg["shape"] and leg["maneuvers"][0].get("time") is not None, "Format")
            need(300 < o["trip"]["summary"]["length"] < 500, "Strecke unplausibel")
            return f"{o['trip']['summary']['length']:.0f} km"
        c["route.valhalla"] = ("Routing Valhalla (FOSSGIS)", valhalla)

    # ---------- Adresssuche / Land ----------
    def photon():
        f = js(f"{u['geo.photon'][0]}/api/?q=Wien&limit=1&lang=de")["features"][0]
        need(abs(f["geometry"]["coordinates"][1] - 48.2) < 0.3, "falscher Ort")
        p = js(f"{u['geo.photon'][0]}/reverse?lat=47.8&lon=13.04&limit=1")["features"][0]["properties"]
        need(p.get("countrycode", "").upper() == "AT", f"Land {p.get('countrycode')}")
        return "Suche + Land ok"
    c["geo.photon"] = ("Adresssuche Photon", photon)

    def nominatim():
        r = js(f"{u['geo.nominatim'][0]}/search?q=Wien&format=jsonv2&limit=1")[0]
        need(abs(float(r["lat"]) - 48.2) < 0.3, "falscher Ort")
        time.sleep(1.2)
        a = js(f"{u['geo.nominatim'][0]}/reverse?lat=47.8&lon=13.04&format=jsonv2&zoom=3")
        need(a["address"]["country_code"].upper() == "AT", "Land")
        return "Suche + Land ok"
    c["geo.nominatim"] = ("Adresssuche Nominatim (Ersatz)", nominatim)

    # ---------- Wetter ----------
    om = u["weather.openmeteo"][0]
    for model in ("icon_seamless", "best_match", "ecmwf_ifs025"):
        def openmeteo(model=model):
            h = js(f"{om}?latitude={FFM[0]},{MUC[0]}&longitude={FFM[1]},{MUC[1]}&hourly=temperature_2m,precipitation,weather_code,wind_gusts_10m"
                   f"&models={model}&timezone=GMT&forecast_days=3")[0]["hourly"]
            need(len(h["time"]) >= 48 and any(v is not None for v in h["temperature_2m"]) and "weather_code" in h, "Felder fehlen")
            return f"{len(h['time'])} Stunden"
        c[f"weather.openmeteo.{model}"] = (f"Wetter Open-Meteo ({model})", openmeteo)

    def nowcast():
        m = js(f"{om}?latitude={FFM[0]}&longitude={FFM[1]}&minutely_15=precipitation&forecast_minutely_15=16&timezone=GMT")["minutely_15"]
        need(len(m["time"]) >= 8, "zu wenig Werte")
        return "15-Min-Werte ok"
    c["weather.nowcast"] = ("Regen-Kurzfrist (Open-Meteo)", nowcast)

    def metno():
        ts = js(f"{u['weather.metno'][0]}?lat={FFM[0]}&lon={FFM[1]}")["properties"]["timeseries"]
        d = ts[0]["data"]
        need("air_temperature" in d["instant"]["details"] and d["next_1_hours"]["summary"]["symbol_code"], "Felder fehlen")
        return f"{len(ts)} Zeitpunkte"
    c["weather.metno"] = ("Wetter MET Norway", metno)

    def dwd():
        o = js(f"{u['alerts.dwd'][0]}?lat={FFM[0]}&lon={FFM[1]}")
        need("alerts" in o, "Feld alerts fehlt")
        return f"{len(o['alerts'])} Warnungen"
    c["alerts.dwd"] = ("Unwetterwarnungen DWD (Bright Sky)", dwd)

    def radar():
        o = js(u["radar"][0])
        need(o["radar"]["past"] and o["host"], "Format")
        return "ok"
    c["radar"] = ("Regenradar (RainViewer)", radar)

    # ---------- Sprit live ----------
    def tk():
        # Demo-Schlüssel von Tankerkönig liefert Testdaten im echten Format
        o = js(f"{u['fuel.DE'][0]}?lat={FFM[0]}&lng={FFM[1]}&rad=5&sort=price&type=e5&apikey=00000000-0000-0000-0000-000000000002")
        need(o.get("ok") and isinstance(o.get("stations"), list), o.get("message"))
        s = o["stations"][0]
        need(all(k in s for k in ("id", "lat", "lng", "price", "isOpen")), "Felder fehlen")
        return f"{len(o['stations'])} Stationen (Demo)"
    c["fuel.DE"] = ("Sprit DE Tankerkönig/MTS-K", tk)

    def ec():
        a = js(f"{u['fuel.AT'][0]}?latitude=48.2&longitude=16.37&fuelType=SUP&includeClosed=false")
        s = next(x for x in a if x.get("prices"))
        need(s["prices"][0]["amount"] > 0.8 and "latitude" in s["location"], "Format")
        return f"{len(a)} Stationen"
    c["fuel.AT"] = ("Sprit AT E-Control", ec)

    def fr():
        where = urllib.parse.quote("within_distance(geom, geom'POINT(2.35 48.85)', 5km)")
        r = js(f"{u['fuel.FR'][0]}?limit=20&where={where}&select=id,adresse,ville,geom,sp95_prix,sp95_maj,gazole_prix,gazole_maj")["results"]
        need(r and any(x.get("gazole_prix") for x in r) and r[0]["geom"]["lat"], "Format")
        return f"{len(r)} Stationen"
    c["fuel.FR"] = ("Sprit FR prix-carburants (live)", fr)

    def si():
        r = js(f"{u['fuel.SI'][0]}?position=46.05,14.5&radius=5000&o=price_95")["results"]
        need(r and "95" in r[0]["prices"] and r[0]["lat"], "Format")
        return f"{len(r)} Stationen"
    c["fuel.SI"] = ("Sprit SI goriva.si", si)

    # ---------- Daten im Release "data" ----------
    rel = {a["name"]: a for a in js(f"https://api.github.com/repos/{REPO}/releases/tags/data",
                                     headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}"} if os.environ.get("GH_TOKEN") else None)["assets"]}
    for name, max_h, label in (("fuel-ES.json.gz", 8, "Sprit ES (Paket)"), ("fuel-PT.json.gz", 8, "Sprit PT (Paket)"),
                               ("fuel-HR.json.gz", 8, "Sprit HR (Paket)"), ("fuel-FR.json.gz", 8, "Sprit FR (Ersatz-Paket)"),
                               ("eu-fuel.json", 24 * 10, "EU-Durchschnittspreise"), ("countries.json", 24 * 40, "Länderinfos (ADAC)"),
                               ("vignettes.json", 24 * 40, "Vignettenpreise"), ("lez.json.gz", 24 * 40, "Umweltzonen"),
                               ("poi-DE.json.gz", 24 * 40, "Toiletten-Pakete (Stichprobe DE)"), ("config.json", 24 * 365, "Fernsteuerung (config.json)")):
        def asset(name=name, max_h=max_h):
            a = rel.get(name)
            need(a, "fehlt im Release")
            h = age_h(a["updated_at"])
            need(h <= max_h, f"{h:.0f} h alt (erlaubt {max_h} h)")
            need(a["size"] >= MIN_KB.get(name, 1) * 1024, f"nur {a['size']} Bytes – leer/kaputt?")
            return f"{h:.0f} h alt, {a['size'] // 1024} KB"
        c[f"data.{name}"] = (label, asset)

    def all_poi():
        # Jedes Land einzeln: ein Land, dessen OSM-Download mehrmals scheiterte, behält sein altes Paket – hier fällt es auf.
        poi = {n[4:6]: x for n, x in rel.items() if n.startswith("poi-") and n.endswith(".json.gz")}
        need(len(poi) >= 30, f"nur {len(poi)} Länder")
        old = sorted(f"{k} {age_h(x['updated_at']) / 24:.0f} T" for k, x in poi.items() if age_h(x["updated_at"]) > 24 * 70)
        need(not old, "zu alt: " + ", ".join(old))
        return f"{len(poi)} Länder, alle jünger als 70 Tage"
    c["data.poi-all"] = ("Toiletten-Pakete (alle Länder)", all_poi)

    def overpass():
        q = '[out:json][timeout:25];node["amenity"="toilets"](50.10,8.67,50.12,8.69);out 1;'
        errs = []
        for ep in u["overpass"]:
            try:
                o = js(ep, data=("data=" + urllib.parse.quote(q)).encode(), timeout=40)
                need("elements" in o, "Format")
                return f"{urllib.parse.urlparse(ep).netloc} ok"
            except Exception as e:
                errs.append(f"{urllib.parse.urlparse(ep).netloc}: {e}")
        raise AssertionError("; ".join(errs))
    c["overpass"] = ("Toiletten live (Overpass, ohne Paket)", overpass)

    def autobahn():
        o = js(f"{u['traffic.autobahn'][0]}/A7/services/roadworks")
        need("roadworks" in o, "Format")
        return f"{len(o['roadworks'])} Baustellen A7"
    c["traffic.autobahn"] = ("Autobahn GmbH (Baustellen, Sperrungen)", autobahn)

    def fx():
        r = js(f"{u['fx'][0]}?base=EUR")["rates"]
        need(r.get("CHF") and r.get("CZK"), "Kurse fehlen")
        return f"CHF {r['CHF']}"
    c["fx"] = ("Wechselkurse (EZB über frankfurter.dev)", fx)
    return c


def main(cfg_path, dst):
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    res = {}
    for key, (label, fn) in checks(cfg).items():
        t = time.time()
        for attempt in range(2):
            try:
                msg = fn()
                res[key] = {"label": label, "ok": True, "msg": msg}
                break
            except Exception as e:
                res[key] = {"label": label, "ok": False, "msg": f"{type(e).__name__}: {e}"[:300]}
                time.sleep(5)
        res[key]["ms"] = int((time.time() - t) * 1000)
        print(("✔ " if res[key]["ok"] else "✖ ") + f"{label}: {res[key]['msg']}", flush=True)
    os.makedirs(dst, exist_ok=True)
    doc = {"checked": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "results": res}
    json.dump(doc, open(os.path.join(dst, "health.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    bad = [r for r in res.values() if not r["ok"]]
    with open(os.path.join(dst, "issue.md"), "w", encoding="utf-8") as f:
        if bad:
            f.write("Der tägliche Check hat Probleme gefunden:\n\n" + "\n".join(f"- **{r['label']}**: {r['msg']}" for r in bad) +
                    "\n\nDie App nutzt dafür automatisch Ersatz-Anbieter bzw. den letzten guten Stand. "
                    "Ändert sich eine Adresse dauerhaft: `data/config.json` anpassen – die App übernimmt das ohne Update.\n")
    print(f"{len(res) - len(bad)}/{len(res)} ok")


if __name__ == "__main__":
    main(*sys.argv[1:3])
