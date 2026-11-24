# RoutenBegleiter – Daten

Automatisch erzeugte, öffentliche Daten für die private App *RoutenBegleiter*. Sie liegen im Release
[`data`](../../releases/tag/data), damit die App sie **ohne Zugangsschlüssel** laden kann.

| Datei | Inhalt | Quelle | Aktualisierung |
|---|---|---|---|
| `countries.json` | Tempolimits, Durchschnitts-Spritpreise, Vignetten, Streckenmaut (nur Zahlen/Preise) | ADAC (adac.de) | monatlich |
| `vignettes.json` | Vignetten-Optionen für die Kostenrechnung | ADAC (adac.de) | monatlich |
| `poi-XX.json.gz` | Toiletten, Rastplätze, Fast-Food je Land und Blitzer-Standorte (`highway=speed_camera`, mit Art/Tempolimit) | © OpenStreetMap-Mitwirkende, ODbL 1.0 (über Geofabrik) | monatlich |
| `fuel-ES.json.gz` | Spritpreise je Tankstelle | Ministerio para la Transición Ecológica | alle 3 h |
| (Italien) | Spritpreise je Tankstelle | MIMIT – Osservatorio prezzi carburanti (IODL 2.0) | lädt die App direkt (mimit.gov.it sperrt GitHub-Server) |
| `fuel-PT.json.gz` | Spritpreise je Tankstelle | DGEG – Direção-Geral de Energia e Geologia | alle 3 h |
| `fuel-HR.json.gz` | Spritpreise je Tankstelle | Ministarstvo gospodarstva RH | alle 3 h |
| `fuel-FR.json.gz` | Spritpreise je Tankstelle (Ersatz, falls die Live-Abfrage ausfällt) | prix-carburants, Ministère de l'Économie (Licence Ouverte 2.0) | alle 3 h |
| `mobile.json.gz` | Von der Polizei angekündigte Geschwindigkeitskontrollen (Saarland-Wochenvorschau, Kantone St.Gallen und Solothurn); Koordinaten über OSM ermittelt, ungefähr | Landespolizeidirektion Saarland (Presseportal), Kantonspolizei St.Gallen, Polizei Kanton Solothurn; Orte © OSM/ODbL | täglich |
| `cameras-XX.json.gz` | Blitzer-Standorte je Land (fest, Abschnittskontrolle, Rotlicht; nur in OSM eingetragene mobile Messstellen) | © OpenStreetMap-Mitwirkende, ODbL 1.0 (Overpass) | täglich |
| `lez.json.gz` | Umweltzonen (Umweltplakette, Crit'Air, LEZ …) | © OpenStreetMap-Mitwirkende, ODbL 1.0 | monatlich |
| `config.json` | Fernsteuerung: Adressen der Quellen, abgeschaltete Quellen, Hinweis an die App | von Hand (`data/config.json`) | bei Änderung |
| `health.json` | Ergebnis des täglichen Gesundheits-Checks aller Quellen | `tools/health_check.py` | täglich |
| `eu-fuel.json` | Durchschnittspreise aller EU-Länder inkl. Steuern | © Europäische Union, Weekly Oil Bulletin | wöchentlich |

Die OSM-Pakete stehen unter der [Open Database License](https://opendatacommons.org/licenses/odbl/).
Alle Angaben ohne Gewähr – vor der Fahrt im Zweifel bei der jeweiligen Quelle prüfen.

## Absicherung

- **Plausibilitäts-Sperre** (`tools/guard.py`): Eine neue Datei wird nur veröffentlicht, wenn sie nicht drastisch kleiner ist als die
  bisherige und das Preisniveau stimmt. Lieber ein paar Stunden alte als kaputte Daten.
- **Gesundheits-Check** (täglich): prüft jede Quelle der App inklusive aller Ersatz-Anbieter mit echten Abfragen auf genau die Felder,
  die die App ausliest. Bei Problemen öffnet sich das Issue „Datenquellen-Störung“ (mit E-Mail), es schließt sich selbst, wenn alles wieder läuft.
- **Fernsteuerung** (`data/config.json`): Ändert ein Anbieter seine Adresse oder fällt dauerhaft aus, hier anpassen bzw. unter
  `disabled` abschalten – die App übernimmt das innerhalb eines Tages, ohne neue Version.

## Skripte

- `tools/update_country_data.py` (mit `OUT_DIR=data PUBLIC=1`)
- `tools/build_poi_pack.py`
- `tools/fuel_packs.py`, `tools/fuel_eu.py`
- `tools/build_lez.py` (Umweltzonen), `tools/health_check.py`, `tools/guard.py`
