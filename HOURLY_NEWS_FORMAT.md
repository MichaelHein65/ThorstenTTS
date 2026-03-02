# Hourly News Format (ThorstenTTS)

## Ziel
Dieses Projekt erzeugt stündliche Nachrichten-Texte und MP3-Dateien mit Thorsten TTS.

## Intro / Outro
Der Nachrichtentext enthält automatisch:

- Intro:
  `Und hier die AI-Radio Nachrichten zur vollen Stunde. Es ist <Wochentag>, der <Ordinal-Tag> <Monat> <Jahr> um <naechste volle Stunde> Uhr.`
- Outro:
  `Diese Nachrichten wurden dem Newsfeed der Tagesschau entnommen und von Thorsten TTS gesprochen. Alles wie gewohnt automatisch von AI-Radio.`

## Ordinal-Tag
Der Kalendertag wird als gesprochenes Ordinal formuliert:
`erste, zweite, dritte, ... einunddreissigste`.

## Quellen
Standardquelle ist `tagesschau` (RSS):

- Tagesschau-Ressorts: Top-Thema, Deutschland, Europa, Welt, Kurioses, Wetter
- Sport: Sportschau-RSS (da im Tagesschau-Hauptfeed nicht immer Sportmeldungen enthalten sind)

## Segmentierung fuer bessere Sprachpausen
In `tts_client.py` wird zeilenbasiert segmentiert:

- Ueberschriften sind eigene Sprecheinheiten
- Meldungen werden satzweise gesprochen
- Piper nutzt `--sentence_silence` (Default `0.35`)

Damit entstehen kurze Gedankenpausen zwischen Ueberschriften und Meldungen.

## Wichtige Optionen

- `--source tagesschau|openai`
- `--text-only` (nur Text ausgeben, kein MP3)
- `--sport-items 1|2`

Beispiel:

```bash
cd /home/pi/ThorstenTTS
python3 news_to_mp3.py --pi-host localhost --pi-user pi --source tagesschau --voice neutral --output /home/pi/ThorstenTTS/output/Nachrichten_Aktuell_Thorsten_hourly.mp3
```
