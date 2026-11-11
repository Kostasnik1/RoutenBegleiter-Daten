#!/usr/bin/env python3
"""
Amtliche Durchschnittspreise aller EU-Länder (inkl. Steuern) aus dem Weekly Oil Bulletin der EU-Kommission
→ eu-fuel.json  {"updated","week","source","prices":{"AT":{"e5":1.747,"diesel":2.148,"lpg":...}}}
Dient der App als Plausibilitätsprüfung der Tankstellenpreise und als Länder-Durchschnitt.
Aufruf: python tools/fuel_eu.py <ausgabeordner>
"""
import datetime, io, json, os, sys, time, urllib.request
import openpyxl

sys.stdout.reconfigure(encoding="utf-8")

URL = "https://energy.ec.europa.eu/document/download/264c2d0f-f161-4ea3-a777-78faae59bea0_en?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx"
ISO = {"Austria": "AT", "Belgium": "BE", "Bulgaria": "BG", "Croatia": "HR", "Cyprus": "CY", "Czechia": "CZ", "Czech Republic": "CZ",
       "Denmark": "DK", "Estonia": "EE", "Finland": "FI", "France": "FR", "Germany": "DE", "Greece": "GR", "Hungary": "HU",
       "Ireland": "IE", "Italy": "IT", "Latvia": "LV", "Lithuania": "LT", "Luxembourg": "LU", "Malta": "MT", "Netherlands": "NL",
       "Poland": "PL", "Portugal": "PT", "Romania": "RO", "Slovakia": "SK", "Slovenia": "SI", "Spain": "ES", "Sweden": "SE"}


def main(dst):
    for i in range(4):
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 RoutenBegleiter-Daten"})
            data = urllib.request.urlopen(req, timeout=120).read()
            break
        except Exception as e:
            print("Fehler", e)
            time.sleep(30 * (i + 1))
    else:
        sys.exit("EU-Ölbulletin nicht erreichbar")
    ws = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    week = rows[1][0].date().isoformat() if isinstance(rows[1][0], datetime.datetime) else str(rows[1][0])
    prices = {}
    for r in rows[2:]:
        iso = ISO.get(str(r[0]).strip()) if r and r[0] else None
        if not iso:
            continue
        p = {k: round(float(v) / 1000, 3) for k, v in (("e5", r[1]), ("diesel", r[2]), ("lpg", r[6] if len(r) > 6 else None))
             if isinstance(v, (int, float)) and v > 300}
        if p:
            prices[iso] = p
    if len(prices) < 20:
        sys.exit(f"nur {len(prices)} Länder gelesen – Format geändert?")
    os.makedirs(dst, exist_ok=True)
    json.dump({"updated": datetime.date.today().isoformat(), "week": week,
               "source": "EU-Kommission, Weekly Oil Bulletin (Durchschnitt inkl. Steuern)", "prices": prices},
              open(os.path.join(dst, "eu-fuel.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(prices)} Länder, Woche {week}: DE {prices.get('DE')}")


if __name__ == "__main__":
    main(*sys.argv[1:])
