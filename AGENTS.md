# Agent-Anleitung: Kalender-Sync

Dieses Repo wird täglich von GitHub Actions befüllt (`scripts/ingest.py`). Deine Aufgabe ist **nicht** das Scraping, sondern das Eintragen neuer Termine in Google Calendar.

## Wann handeln?

1. `data/last-run.json` lesen.
2. Nur fortfahren, wenn `new > 0` oder der Nutzer explizit einen Sync wünscht.

## Ablauf

1. Repository aktuell halten (`git pull`).
2. `data/events.json` laden — Feld `events` ist die Liste.
3. `data/calendar-synced.json` laden — Feld `synced_ids` enthält bereits eingetragene Event-IDs.
4. Für jedes Event in `events`, dessen `id` **nicht** in `synced_ids` steht:
   - Google Calendar-Eintrag anlegen über **Composio** (bestehende Verbindung):
     - **Titel:** `title`
     - **Start:** `start` (ISO 8601; wenn `null`, Nutzer fragen oder aus `url`/Beschreibung schätzen)
     - **Ort:** `location` oder `city`
     - **Beschreibung:** `description`, Link `url`, Quelle `source`
   - Nach Erfolg: `id` zu `synced_ids` hinzufügen.
5. `data/calendar-synced.json` speichern und committen (wenn der Nutzer das wünscht).

## Felder pro Event

```json
{
  "id": "stuttgart-official:abc123",
  "source": "stuttgart-official",
  "title": "...",
  "start": "2026-05-22T19:00:00+02:00",
  "end": null,
  "location": "Stuttgart",
  "url": "https://...",
  "city": "Stuttgart",
  "region": "Baden-Württemberg"
}
```

## Nutzer-Prompt (Kurzform)

> Sync neue Events aus `data/events.json` in meinen Google Calendar. Überspringe IDs in `data/calendar-synced.json`. Aktualisiere `calendar-synced.json` danach.

## Fehler

- Scraping-Fehler stehen in `data/last-run.json` → `errors` — nicht mit Kalender-Sync verwechseln.
- Bei fehlendem `start`: Event überspringen oder Nutzer um Klärung bitten.

## Keine Secrets in diesem Repo

Kalender-Zugang läuft über die bereits in Cursor/Composio konfigurierte OAuth-Verbindung — keine API-Keys ins Repository committen.
