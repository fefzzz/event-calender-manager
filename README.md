# Event Calendar Manager (Stuttgart / BW)

Kleines MVP-Repository: GitHub Actions holt täglich Veranstaltungen aus öffentlichen Quellen (RSS/HTML) und speichert sie als JSON. Claude/Cursor kann das Repo jederzeit lesen und neue Termine über die bestehende Google-Calendar-Anbindung (z. B. Composio) eintragen.

## Schnellstart

1. Repository auf GitHub anlegen und diesen Ordner pushen.
2. Unter **Actions** den Workflow **Daily event ingest** einmal mit **Run workflow** starten.
3. Prüfen, ob `data/events.json` und `data/last-run.json` aktualisiert wurden.
4. In Cursor: `AGENTS.md` öffnen und Kalender-Sync für neue Events ausführen.

## Lokaler Test

```powershell
cd event-calender-manager
pip install -r scripts/requirements.txt
python scripts/ingest.py
```

## Struktur

| Pfad | Zweck |
|------|--------|
| `config/sources.yaml` | Event-Quellen (RSS/HTML), Horizont in Tagen |
| `scripts/ingest.py` | Fetch, Dedup, JSON schreiben |
| `data/events.json` | Aktuelle Events im Zeitraum |
| `data/state.json` | Bereits gesehene Event-IDs |
| `data/last-run.json` | Letzter Lauf (neu/übersprungen/Fehler) |
| `data/calendar-synced.json` | IDs, die bereits im Kalender sind |
| `AGENTS.md` | Anleitung für Claude (Kalender-Sync) |

## Automatisierung

- **Cron:** täglich 05:00 UTC (ca. 07:00 MESZ)
- **Manuell:** Actions → Daily event ingest → Run workflow
- Keine Secrets nötig für die Standard-RSS-Quelle Stuttgart.

## Quellen erweitern

In `config/sources.yaml` weitere Einträge unter `sources:` anlegen. HTML-Quellen (`type: html`) sind experimentell — bei Layout-Änderungen können Fehler in `data/last-run.json` → `errors` auftauchen.

`visit-bw` ist vorbereitet, aber standardmäßig `enabled: false`.

## Kalender

Das Scraping läuft in GitHub Actions. Das Eintragen in Google Calendar erfolgt bewusst über Claude mit eurer bestehenden Composio/OAuth-Konfiguration — siehe `AGENTS.md`.

## Rechtliches

Nur öffentliche Veranstaltungslisten, moderate Abrufrate, User-Agent mit Projektbezug. Kein Umgehen von Zugangsbeschränkungen.
