# RoutenBegleiter – Daten

Automatisch erzeugte, öffentliche Daten für die private App *RoutenBegleiter*. Sie liegen im Release
[`data`](../../releases/tag/data), damit die App sie **ohne Zugangsschlüssel** laden kann.

| Datei | Inhalt | Quelle | Aktualisierung |
|---|---|---|---|
| `countries.json` | Tempolimits, Durchschnitts-Spritpreise, Vignetten, Streckenmaut (nur Zahlen/Preise) | ADAC (adac.de) | monatlich |
| `vignettes.json` | Vignetten-Optionen für die Kostenrechnung | ADAC (adac.de) | monatlich |
| `poi-XX.json.gz` | Toiletten, Rastplätze, Fast-Food je Land | © OpenStreetMap-Mitwirkende, ODbL 1.0 (über Geofabrik) | monatlich |
| `fuel-ES.json.gz` | Spritpreise je Tankstelle | Ministerio para la Transición Ecológica | alle 3 h |
| `fuel-IT.json.gz` | Spritpreise je Tankstelle | MIMIT – Osservatorio prezzi carburanti (IODL 2.0) | alle 3 h (Quelle täglich) |
| `fuel-PT.json.gz` | Spritpreise je Tankstelle | DGEG – Direção-Geral de Energia e Geologia | alle 3 h |
| `fuel-HR.json.gz` | Spritpreise je Tankstelle | Ministarstvo gospodarstva RH | alle 3 h |
| `eu-fuel.json` | Durchschnittspreise aller EU-Länder inkl. Steuern | © Europäische Union, Weekly Oil Bulletin | wöchentlich |

Die OSM-Pakete stehen unter der [Open Database License](https://opendatacommons.org/licenses/odbl/).
Alle Angaben ohne Gewähr – vor der Fahrt im Zweifel bei der jeweiligen Quelle prüfen.

## Skripte

- `tools/update_country_data.py` (mit `OUT_DIR=data PUBLIC=1`)
- `tools/build_poi_pack.py`
- `tools/fuel_packs.py`, `tools/fuel_eu.py`
