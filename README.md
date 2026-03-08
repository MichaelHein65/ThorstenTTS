# ThorstenTTS

Lokale Browser-App fuer Thorsten TTS ueber einen Raspberry Pi 5. Die App ist in der Modelauswahl auf die Thorsten-Modelle begrenzt und spielt die erzeugte Ausgabe direkt auf dem Mac ab.

## Features
- Web-UI fuer die Thorsten-Modelle `Thorsten High`, `Thorsten Emotional` und `Thorsten Hessisch`
- Emotionsauswahl fuer `Thorsten Emotional`
- Fortschrittsanzeige waehrend der Synthese
- Replay der letzten Ausgabe ohne Neu-Synthese
- MP3-Export mit automatischem Speichern nach `/Users/michaelhein/Pi5Platte/AI_Radio/Thorsten/latest.mp3`

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
- gemountetes Pi-Laufwerk auf dem Mac: `/Users/michaelhein/Pi5Platte`

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
TTS_SAVE_DIR="/Users/michaelhein/Pi5Platte/AI_Radio/Thorsten" \
TTS_SAVE_NAME="mein.mp3" \
TTS_MODEL_DIR="/mnt/tts/models/thorsten" \
python3 "server.py" --host 0.0.0.0 --port 8080 --pi-host pi5 --pi-user pi
```

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
- `POST /download` speichert die letzte Ausgabe als MP3

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

## Hinweis zu Finder-Rechten
Wenn Finder nicht in `/Users/michaelhein/Pi5Platte/AI_Radio/Thorsten` schreiben kann, fehlen Rechte auf dem Pi-Mount. Auf dem Pi:
```bash
ssh pi@pi5 "sudo chmod o+w /mnt/meineplatte/AI_Radio/Thorsten"
```
