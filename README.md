# ThorstenTTS

Lokale Browser-App fuer Thorsten TTS ueber einen Raspberry Pi 5. Die App ist in der Modelauswahl auf die Thorsten-Modelle begrenzt und spielt die erzeugte Ausgabe direkt auf dem Mac ab.

## Features
- Web-UI fuer die Thorsten-Modelle `Thorsten High`, `Thorsten Emotional` und `Thorsten Hessisch`
- Emotionsauswahl fuer `Thorsten Emotional`
- Fortschrittsanzeige waehrend der Synthese
- Replay der letzten Ausgabe ohne Neu-Synthese
- MP3-Export mit lokalem Staging unter `~/Documents/PiSync/Pi5Platte/AI_Radio/Thorsten/latest.mp3`
- automatischer SSH-Upload nach `pi5:/mnt/meineplatte/AI_Radio/Thorsten/latest.mp3`

## Architektur
- Der Browser spricht mit `server.py` auf dem Mac.
- `server.py` leitet Thorsten/Piper-Aufrufe per SSH an den Pi weiter.
- `tts_client.py` kuemmert sich um SSH, Audio-Rueckgabe und lokale Wiedergabe.
- MP3-Erzeugung und Playback laufen auf dem Mac.

## Voraussetzungen

### Mac
- macOS mit Python 3
- `ffmpeg`
- funktionierender SSH-Zugriff auf den Pi, z. B. Host `pi5`
- kein SSHFS-Mount notwendig

### Pi
- `/usr/local/bin/piper`
- `espeak-ng` Daten unter `/opt/piper/espeak-ng-data`
- Modellordner `/mnt/tts/models/thorsten`
- erwartete Dateien:
  - `de_DE-thorsten-high.onnx`
  - `de_DE-thorsten-high.onnx.json`
  - `de_DE-thorsten_emotional-medium.onnx`
  - `de_DE-thorsten_emotional-medium.onnx.json`
  - `de_DE-thorsten_hessisch-medium.onnx`
  - `de_DE-thorsten_hessisch-medium.onnx.json`

## Start

### Terminal
```bash
python3 "/Users/michaelhein/* VSC/20260202 Thorsten/server.py" \
  --host 0.0.0.0 \
  --port 8080 \
  --pi-host pi5 \
  --pi-user pi
```

Dann im Browser:
```text
http://127.0.0.1:8080
```

### Doppelklick
`run.command` startet den Server und oeffnet den Browser.

## Konfiguration per Umgebungsvariablen
```bash
TTS_SAVE_DIR="$HOME/Documents/PiSync/Pi5Platte/AI_Radio/Thorsten" \
TTS_SAVE_NAME="mein.mp3" \
TTS_REMOTE_SYNC_ENABLED="1" \
TTS_REMOTE_SAVE_HOST="pi5" \
TTS_REMOTE_SAVE_USER="pi" \
TTS_REMOTE_SAVE_DIR="/mnt/meineplatte/AI_Radio/Thorsten" \
TTS_MODEL_DIR="/mnt/tts/models/thorsten" \
python3 "server.py" --host 0.0.0.0 --port 8080 --pi-host pi5 --pi-user pi
```

### News-Aktualitaet
`news_to_mp3.py` filtert Tagesschau- und Sportschau-RSS-Eintraege vor der Rubriken-Auswahl nach `pubDate`. Dadurch werden keine mehrtaegigen Einzelmeldungen in einen neuen Nachrichtenblock uebernommen.

Defaults:
- `NEWS_MAX_ITEM_AGE_HOURS=30`
- `NEWS_SPORT_MAX_ITEM_AGE_HOURS=48`
- `NEWS_WEATHER_MAX_ITEM_AGE_HOURS=36`
- `NEWS_REQUIRE_PUBDATE=1`

### Lernender Aussprache-Fundus

Vor jeder News-Synthese prueft `news_tts_normalizer.py` den vollstaendigen
Nachrichtentext auf schwierige Namen, Fremdwoerter und unbekannte Abkuerzungen.
Hochkonfidente TTS-Schreibweisen werden dauerhaft in
`thorsten_tts_learned.json` gespeichert und in spaeteren Nachrichten automatisch
wiederverwendet. Bestehende Eintraege werden bei abweichenden Vorschlaegen nicht
automatisch ueberschrieben.

Zu jeder Analyse wird unter `output/pronunciation_learning/` ein JSON-Protokoll
mit Originaltext, tatsaechlichem TTS-Text, neuen Eintraegen, Ablehnungen und
Konflikten abgelegt. Falls die KI-Pruefung nicht erreichbar ist, laeuft die
Synthese mit dem vorhandenen Fundus weiter.

Optionale Umgebungsvariablen:

- `NEWS_TTS_AUTO_LEARN=1`
- `NEWS_TTS_LEARN_MODEL` (Default: `OPENAI_MODEL` oder `gpt-4o-mini`)
- `NEWS_TTS_LEARN_MIN_CONFIDENCE=0.90`
- `NEWS_TTS_LEARNED_CATALOG`
- `NEWS_TTS_LEARNING_AUDIT_DIR`

## Bedienung
- Modell auswaehlen
- bei `Thorsten Emotional` optional eine Emotion setzen
- Text eingeben
- `Sprich jetzt` klicken

## Modelle herunterladen
```bash
ssh pi@pi5 "mkdir -p /mnt/tts/models/thorsten && cd /mnt/tts/models/thorsten \
  && curl -L -o de_DE-thorsten_emotional-medium.onnx \
     'https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/de/de_DE/thorsten_emotional/medium/de_DE-thorsten_emotional-medium.onnx' \
  && curl -L -o de_DE-thorsten_emotional-medium.onnx.json \
     'https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/de/de_DE/thorsten_emotional/medium/de_DE-thorsten_emotional-medium.onnx.json' \
  && curl -L -o de_DE-thorsten_hessisch-medium.onnx \
     'https://huggingface.co/Thorsten-Voice/Hessisch/resolve/main/Thorsten-Voice_Hessisch_Piper_high-Oct2023.onnx' \
  && curl -L -o de_DE-thorsten_hessisch-medium.onnx.json \
     'https://huggingface.co/Thorsten-Voice/Hessisch/resolve/main/Thorsten-Voice_Hessisch_Piper_high-Oct2023.onnx.json'"
```

Check:
```bash
ssh pi@pi5 "ls -la /mnt/tts/models/thorsten"
```

## Interne Endpunkte
- `GET /` liefert die UI
- `GET /options` liefert nur die Thorsten-Modell- und Emotionsoptionen
- `POST /speak` startet die Thorsten-Synthese
- `POST /replay` spielt die letzte Ausgabe erneut ab
- `POST /download` speichert die letzte Ausgabe lokal als MP3 und synchronisiert sie optional per SSH

## Dateien
- `index.html` - Frontend fuer die Thorsten-Modelauswahl
- `server.py` - lokaler HTTP-Server, Routing, MP3-Export
- `tts_client.py` - SSH-Bridge, Audio-Rueckgabe, lokale Wiedergabe
- `run.command` - Start per Doppelklick
- `run.sh` - Shell-Startskript
- `news_to_mp3.py` - optionales Zusatzskript fuer News-Automation

## Verifikation
Zuletzt geprueft:
- `python3 -m py_compile server.py`
- `node --check` fuer das eingebettete Script in `index.html`
- `GET /options` mit Thorsten-only-Antwort

## Hinweis zu Remote-Rechten
Wenn der SSH-Upload nach `pi5:/mnt/meineplatte/AI_Radio/Thorsten` fehlschlaegt, fehlen meist Rechte auf dem Pi-Zielpfad. Auf dem Pi:
```bash
ssh pi@pi5 "sudo chmod o+w /mnt/meineplatte/AI_Radio/Thorsten"
```

## Direkter Upload ohne App
Das folgende Skript ist ein lokales Begleitskript auf diesem Mac und nicht Teil dieses Git-Repos:
```bash
~/bin/pi5_platte_push.sh "$HOME/Documents/PiSync/Pi5Platte/AI_Radio/Thorsten/latest.mp3"
```
