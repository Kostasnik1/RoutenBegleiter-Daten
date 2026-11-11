#!/usr/bin/env python3
"""
Holt Länderinfos für Europa vom ADAC (adac.de) und schreibt sie für die App:

  app/src/main/assets/countries.json  – Tempolimits, Spritpreise, Regeln (Promille, Warnweste, Winter …),
                                         Streckenmaut-Beispiele, Quelle + Datum
  app/src/main/assets/vignettes.json  – Vignetten-Optionen (Tage, Preis, Gültigkeit) für die Kostenrechnung

Manuelle Werte in vignettes.json bleiben erhalten, wenn der ADAC für ein Land nichts liefert.
Abweichungen zwischen ADAC und bisherigem Stand werden ausgegeben (für den GitHub-Workflow → Issue).

Aufruf: python tools/update_country_data.py
"""
import datetime, html, json, os, re, sys, time, urllib.request

ROOT = os.environ.get("OUT_DIR") or os.path.join(os.path.dirname(__file__), "..", "app", "src", "main", "assets")
# PUBLIC=1: ohne die ADAC-Regeltexte (Prosa, urheberrechtlich geschützt) – nur Fakten (Zahlen/Preise) fürs öffentliche Daten-Repo
PUBLIC = os.environ.get("PUBLIC") == "1"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
BASE = "https://www.adac.de/reise-freizeit"

COUNTRIES = {  # ISO: (Name, ADAC-Slug)
    "DE": ("Deutschland", "deutschland"), "AT": ("Österreich", "oesterreich"), "CH": ("Schweiz", "schweiz"),
    "FR": ("Frankreich", "frankreich"), "IT": ("Italien", "italien"), "ES": ("Spanien", "spanien"),
    "PT": ("Portugal", "portugal"), "NL": ("Niederlande", "niederlande"), "BE": ("Belgien", "belgien"),
    "LU": ("Luxemburg", "luxemburg"), "DK": ("Dänemark", "daenemark"), "PL": ("Polen", "polen"),
    "CZ": ("Tschechien", "tschechien"), "SK": ("Slowakei", "slowakei"), "HU": ("Ungarn", "ungarn"),
    "SI": ("Slowenien", "slowenien"), "HR": ("Kroatien", "kroatien"), "BA": ("Bosnien und Herzegowina", "bosnien-herzegowina"),
    "RS": ("Serbien", "serbien"), "ME": ("Montenegro", "montenegro"), "AL": ("Albanien", "albanien"),
    "MK": ("Nordmazedonien", "nordmazedonien"), "GR": ("Griechenland", "griechenland"), "BG": ("Bulgarien", "bulgarien"),
    "RO": ("Rumänien", "rumaenien"), "MD": ("Moldau", "moldau"), "TR": ("Türkei", "tuerkei"),
    "GB": ("Großbritannien", "grossbritannien"), "IE": ("Irland", "irland"), "NO": ("Norwegen", "norwegen"),
    "SE": ("Schweden", "schweden"), "FI": ("Finnland", "finnland"), "EE": ("Estland", "estland"),
    "LV": ("Lettland", "lettland"), "LT": ("Litauen", "litauen"), "LI": ("Liechtenstein", "liechtenstein"),
}

# Länder, deren Vignettenpreis manuell (offizieller Preis) gepflegt wird – ADAC nennt hier den eigenen Verkaufspreis
KEEP_MANUAL = {"CH"}

# Regel-Abschnitte von der ADAC-Seite ".../reiseziele/<land>/fahrzeug/", die in der App gezeigt werden
RULES = ["Promillegrenze", "Telefonieren", "Licht", "Abblendlicht", "Warnwestenpflicht", "Weitere Mitführpflichten",
         "Winterausrüstung", "Fahrzeuge bis 3,5 t zGG", "Schneeketten", "Spikes", "Rettungsgasse", "Radarwarngeräte",
         "Dashcam", "Umweltzonen", "Halten und Parken", "Kindersitze"]


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(3 * (i + 1))
        except Exception:
            time.sleep(3 * (i + 1))
    return None


def clean(s):
    s = re.sub(r"<sup.*?</sup>", "", s, flags=re.S)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"\s+", " ", s).strip()


def blocks(page):
    """Folge von ("h", Überschrift) / ("t", Tabelle als Zeilenliste) / ("p", Text) in Seitenreihenfolge."""
    page = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", "", page, flags=re.S)
    out, tables = [], []

    def stash(m):  # Tabellen stehen beim ADAC teils in <p> – vorher herauslösen
        tables.append(m.group(0))
        return f"</p><tbl{len(tables) - 1}></tbl><p>"
    page = re.sub(r"<table.*?</table>", stash, page, flags=re.S)
    for m in re.finditer(r"<h([1-4])[^>]*>(.*?)</h\1>|<tbl(\d+)>|<p[^>]*>(.*?)</p>|<li[^>]*>(.*?)</li>", page, flags=re.S):
        g = m.group(0)
        if g.startswith("<h"):
            out.append(("h", clean(m.group(2))))
        elif g.startswith("<tbl"):
            t = tables[int(m.group(3))]
            rows = [[clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S)] for r in re.findall(r"<tr.*?</tr>", t, flags=re.S)]
            out.append(("t", [r for r in rows if any(r)]))
        else:
            t = clean(m.group(4) or m.group(5) or "")
            if t:
                out.append(("p", t))
    return out


PRICE = re.compile(r"(\d{1,3}(?:[ .  ]\d{3})+|\d+)(?:,(\d{1,2}))?\s*(€|Euro|EUR|CHF|CZK|Kč|HUF|Ft|RON|lei|BGN|PLN|zł|NOK|SEK|DKK|GBP|£|RSD|BAM|MKD|ALL|TRY|MDL)?")


def price(s):
    m = PRICE.search(s or "")
    if not m or (not m.group(2) and not m.group(3)):
        return None, None
    v = float(re.sub(r"[ .  ]", "", m.group(1)) + "." + (m.group(2) or "0"))
    cur = {"€": "EUR", "Euro": "EUR", "Kč": "CZK", "Ft": "HUF", "lei": "RON", "zł": "PLN", "£": "GBP", None: "EUR"}.get(m.group(3), m.group(3))
    return v, cur


def validity_days(label):
    l = label.lower()
    m = re.search(r"(\d+)\s*-?\s*tag", l)
    if m: return int(m.group(1))
    if "tages" in l or "tagesvignette" in l: return 1
    if "wochenende" in l: return 3
    if "wochen" in l or "woche" in l:
        m = re.search(r"(\d+)\s*-?\s*woche", l); return 7 * (int(m.group(1)) if m else 1)
    m = re.search(r"(\d+)\s*-?\s*monat", l)
    if m: return 365 if int(m.group(1)) == 12 else 30 * int(m.group(1))
    if "monat" in l: return 30
    if "jahr" in l: return 365
    return None


def parse_tolls(page):
    vign, sections, head = [], [], ""
    for kind, v in blocks(page):
        if kind == "h":
            head = v; continue
        if kind != "t" or not v:
            continue
        header = v[0]
        col = next((i for i, c in enumerate(header) if c.lower().startswith("pkw")), 1)
        for row in v[1:]:
            if len(row) <= col:
                continue
            p, cur = price(row[col])
            if p is None:
                continue
            label = row[0]
            days = validity_days(label)
            if days and not re.search(r"fahrt|strecke|tunnel|brücke|maut für|karte|komitat|elektro", (label + " " + head).lower()):
                y = re.search(r"\b(20\d\d)\b", label)
                vign.append({"label": re.sub(r"\s*\b20\d\d\b", "", label).strip(), "days": days, "price": p, "currency": cur,
                             "year": int(y.group(1)) if y else None})
            else:
                sections.append({"name": label, "price": p, "currency": cur, "group": head})
    return vign, sections


def parse_rules(page):
    speed, rules, cur, buf = {}, {}, None, []
    def flush():
        if cur and buf:
            t = " ".join(buf)
            rules[cur] = (t[:700] + " …") if len(t) > 700 else t
    in_speed = False
    for kind, v in blocks(page):
        if kind == "h":
            flush(); buf = []
            cur = v if any(v.startswith(r) for r in RULES) else None
            in_speed = v.lower().startswith(("tempolimit", "pkw")) and not speed
            continue
        if kind == "t" and in_speed and not speed:
            for row in v:
                if len(row) >= 2 and "km/h" in row[1]:
                    speed[row[0]] = row[1]
        elif kind == "p" and cur:
            buf.append(v)
    flush()
    return speed, rules


def parse_fuel(page):
    fuel = {}
    for kind, v in blocks(page):
        if kind == "t":
            for row in v:
                if len(row) >= 2 and re.search(r"/\s*Liter", row[1]):
                    p, cur = price(row[1])
                    if p: fuel[row[0]] = {"price": p, "currency": cur}
            if fuel:
                break
    return fuel


def main():
    vpath, cpath = os.path.join(ROOT, "vignettes.json"), os.path.join(ROOT, "countries.json")
    vj = json.load(open(vpath, encoding="utf-8"))
    today = datetime.date.today().isoformat()
    out, changes = {}, []
    for iso, (name, slug) in COUNTRIES.items():
        maut = get(f"{BASE}/maut-vignette/{slug}/")
        veh = get(f"{BASE}/reiseplanung/reiseziele/{slug}/fahrzeug/")
        fuelp = get(f"{BASE}/reiseplanung/reiseziele/{slug}/tanken-laden/")
        vign, sections = parse_tolls(maut) if maut else ([], [])
        speed, rules = parse_rules(veh) if veh else ({}, {})
        fuel = parse_fuel(fuelp) if fuelp else {}
        out[iso] = {"name": name, "speed": speed, "fuel": fuel, "rules": {} if PUBLIC else rules, "tollSections": sections[:40],
                    "vignettes": vign,
                    "sources": {k: u for k, u in (("maut", maut and f"{BASE}/maut-vignette/{slug}/"),
                                                    ("regeln", veh and f"{BASE}/reiseplanung/reiseziele/{slug}/fahrzeug/"),
                                                    ("tanken", fuelp and f"{BASE}/reiseplanung/reiseziele/{slug}/tanken-laden/")) if u}}
        print(f"{iso}: {len(vign)} Vignetten, {len(sections)} Strecken, {len(speed)} Tempo, {len(fuel)} Sprit, {len(rules)} Regeln", flush=True)

        # Vignetten für die Kostenrechnung übernehmen (nur Pkw-Optionen mit Gültigkeitsdauer)
        if vign and iso not in KEEP_MANUAL:
            opts = []
            for v in vign:
                y = v["year"]
                if v["days"] >= 365 and y:  # Jahresvignette gilt meist 1.12. Vorjahr bis 31.1. Folgejahr
                    fr, to = f"{y - 1}-12-01", f"{y + 1}-01-31"
                elif y:
                    fr, to = f"{y}-01-01", f"{y}-12-31"
                else:
                    fr, to = "2000-01-01", "2099-12-31"
                lab = v["label"] + (f" {y}" if y and v["days"] >= 365 else "")
                opts.append({"days": v["days"], "label": lab, "price": v["price"], "from": fr, "to": to, "currency": v["currency"]})
            curs = {o["currency"] for o in opts}
            old = vj["countries"].get(iso, {})
            oldp = {(o["days"], o["from"][:4]): o["price"] for o in old.get("options", [])}
            for o in opts:
                k = (o["days"], o["from"][:4] if o["days"] < 365 else str(int(o["from"][:4])))
                if k in oldp and abs(oldp[k] - o["price"]) > 0.005:
                    changes.append(f"{name}: {o['label']} {oldp[k]:.2f} → {o['price']:.2f}")
            vj["countries"][iso] = {**old, "name": name, "currency": curs.pop() if len(curs) == 1 else "EUR", "verified": True,
                                    "source": "ADAC", "url": old.get("url") or f"{BASE}/maut-vignette/{slug}/",
                                    "options": [{k: v for k, v in o.items() if k != "currency"} for o in opts]}
        time.sleep(1)

    vj["updated"] = today
    vj["info"] = "Pkw bis 3,5 t, Quelle ADAC (automatisch monatlich aktualisiert). 'verified=false' = nur manuell gepflegt – vor der Fahrt prüfen."
    json.dump(vj, open(vpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"updated": today, "source": "ADAC (adac.de) – Maut & Vignette, Reiseziele/Fahrzeug, Tanken & Laden", "countries": out},
              open(cpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if changes:
        print("\nPREISÄNDERUNGEN:\n" + "\n".join(changes))
        open(os.environ.get("CHANGES_FILE", os.devnull), "w", encoding="utf-8").write("\n".join(changes))


if __name__ == "__main__":
    main()
