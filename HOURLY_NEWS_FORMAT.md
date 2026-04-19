# Hourly News Format (ThorstenTTS)

## Ziel
Dieses Projekt erzeugt stuendliche Nachrichten-Texte und MP3-Dateien produktiv mit Thorsten/Piper auf dem Raspberry Pi 5.

## Intro / Outro
Der Nachrichtentext enthält automatisch:

- Intro:
  `Und hier die AI-Radio Nachrichten zur vollen Stunde. Es ist <Wochentag>, der <Ordinal-Tag> <Monat> <Jahr>.`
- Outro:
  `Diese Nachrichten wurden dem Newsfeed der Tagesschau entnommen und von Thorsten fuer AI-Radio gesprochen. Alles wie gewohnt automatisch produziert.`

## Ordinal-Tag
Der Kalendertag wird als gesprochenes Ordinal formuliert:
`erste, zweite, dritte, ... einunddreissigste`.

## Quellen
Standardquelle ist `tagesschau` (RSS):

- Tagesschau-Ressorts: Top-Thema, Deutschland, Europa, Welt, Kurioses, Wetter
- Sport: Sportschau-RSS (da im Tagesschau-Hauptfeed nicht immer Sportmeldungen enthalten sind)

## Aktualitaet der Einzelmeldungen
RSS-Eintraege werden vor der Rubriken-Auswahl nach `pubDate` gefiltert. Dadurch kann ein neuer Nachrichtenblock keine mehrtaegigen Einzelmeldungen aus dem Feed-Fallback uebernehmen.

Defaults:

- normale Nachrichten: maximal `30` Stunden alt
- Sport: maximal `48` Stunden alt
- Wetter: maximal `36` Stunden alt
- Eintraege ohne `pubDate` werden standardmaessig verworfen

Optional per ENV:

- `NEWS_MAX_ITEM_AGE_HOURS`
- `NEWS_SPORT_MAX_ITEM_AGE_HOURS`
- `NEWS_WEATHER_MAX_ITEM_AGE_HOURS`
- `NEWS_REQUIRE_PUBDATE` (`1`/`0`, Default `1`)

## Rubriken-Layout
Der Nachrichtenkoerper wird mit festen Zielmengen erzeugt:

- TOP-THEMA: 2 Meldungen
- DEUTSCHLAND: 3 Meldungen
- EUROPA: 3 Meldungen
- WELT: 3 Meldungen
- SPORT: 2 Meldungen
- KURIOSES: 1 Meldung
- WETTER: 1 Meldung

Jede Einzelmeldung hat mindestens 3 Saetze.

### Kurioses-Anti-Repeat
- `Kurioses` vermeidet Wiederholungen per Link-Historie.
- Standard: derselbe Link wird fuer `72` Stunden nicht erneut verwendet.
- Historie: `output/hourly_blocks/curious_history.json`
- Optional per ENV:
  - `CURIOUS_REPEAT_BLOCK_HOURS`
  - `CURIOUS_HISTORY_KEEP_DAYS`
  - `CURIOUS_HISTORY_FILE`

## Segmentierung fuer bessere Sprachpausen
In `tts_client.py` wird zeilenbasiert segmentiert:

- Ueberschriften sind eigene Sprecheinheiten
- Meldungen (Bullet-Zeilen) werden als gesamter Block gesprochen
- Die produktive Stundenproduktion rendert mit Thorsten/Piper auf `pi5`
- Zwischen zwei Sprechbloecken wird zusaetzlich Stille eingefuegt (`TTS_CHUNK_PAUSE_SEC`, Default `0.65`)

Damit entstehen kurze Gedankenpausen zwischen Ueberschriften und Meldungen.

## Redaktionsmodus
Bei `source=tagesschau` kann OpenAI fuer die Redaktion genutzt werden:

- `TAGESSCHAU_REDACTION_MODE=required` (Default): Jede Meldung wird per API sinngemaess neu formuliert; ohne API-Key Abbruch
- `TAGESSCHAU_REDACTION_MODE=auto`: OpenAI-Redaktion, mit lokalem Fallback
- `TAGESSCHAU_REDACTION_MODE=openai`: OpenAI-Redaktion bevorzugt

Die API-Paraphrase ist auf nicht-woertliche Umformulierung ausgelegt (sinngemaess korrekt, leicht jugendlich, aber serioes).

## Wichtige Optionen

- `--source tagesschau|openai`
- `--text-only` (nur Text ausgeben, kein MP3)
- `--sport-items 1|2`

Beispiel:

```bash
cd /home/pi/ThorstenTTS
TTS_BACKEND=piper python3 news_to_mp3.py --pi-host localhost --pi-user pi --source tagesschau --output /home/pi/ThorstenTTS/output/Nachrichten_Aktuell_Thorsten_hourly.mp3
```
