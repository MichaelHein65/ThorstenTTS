# ThorstenTTS

Lokale Browser-App fuer TTS ueber einen Raspberry Pi 5. Die App kombiniert:

- **Piper** fuer die festen Thorsten-Stimmen
- **Coqui XTTS v2** fuer mehrsprachige Ausgabe, eingebaute Sprecher und Referenz-WAVs
- Wiedergabe und MP3-Speicherung direkt auf dem Mac

## Features
- Web-UI mit gemeinsamer Engine-Auswahl fuer Piper und Coqui
- Piper-Stimmen: Thorsten High, Emotional, Hessisch
- Emotionsauswahl fuer `thorsten_emotional`
- Coqui XTTS v2 mit:
  - Sprachwahl
  - eingebauten XTTS-Sprechern
  - Referenz-WAV-Pfaden auf dem Pi
  - optionalem Satz-Splitting
- Fortschrittsanzeige fuer laufende Synthesen
- Replay der letzten Ausgabe ohne Neu-Synthese
- MP3-Export mit Lyrics-Tag
- Automatisches Speichern nach `/Users/michaelhein/Pi5Platte/AI_Radio/Thorsten/latest.mp3`
- Demo-Ordner auf dem Pi mit kurzen Sprecherproben unter `/home/pi/Coqui/Demos`

## Architektur
- Der Browser spricht mit `server.py` auf dem Mac.
- `server.py` leitet Piper- oder Coqui-Aufrufe per SSH an den Pi weiter.
- `tts_client.py` kuemmert sich um SSH, Audio-Rueckgabe und lokale Wiedergabe.
- MP3-Erzeugung und Playback laufen auf dem Mac.

## Voraussetzungen

### Mac
- macOS mit Python 3
- `ffmpeg`
- funktionierender SSH-Zugriff auf den Pi, z. B. Host `pi5`
- gemountetes Pi-Laufwerk auf dem Mac: `/Users/michaelhein/Pi5Platte`

### Pi fuer Piper
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

### Pi fuer Coqui
- Coqui-Umgebung unter `/home/pi/Coqui/.venv`
- XTTS v2 installiert und nutzbar
- funktionierende Pakete:
  - `coqui-tts==0.27.5`
  - `torch==2.10.0`
  - `torchaudio==2.10.0`
  - `transformers==4.57.1`

Wichtig: `transformers` wurde auf `4.57.1` festgezogen, weil XTTS v2 mit `5.3.0` in dieser Umgebung nicht kompatibel war.

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
COQUI_PYTHON="/home/pi/Coqui/.venv/bin/python" \
python3 "server.py" --host 0.0.0.0 --port 8080 --pi-host pi5 --pi-user pi
```

## Bedienung

### Piper
- Engine `Piper Thorsten` waehlen
- Stimme auswaehlen
- bei `Thorsten Emotional` optional eine Emotion setzen
- Text eingeben und `Sprich jetzt`

### Coqui XTTS v2
- Engine `Coqui XTTS v2` waehlen
- Modell `XTTS v2` waehlen
- Sprache setzen, z. B. `de`
- entweder:
  - einen eingebauten Sprecher waehlen
  - oder `Referenz-WAV auf dem Pi` aktivieren und einen oder mehrere Pi-Pfade eintragen
- optional Satz-Splitting an- oder abschalten
- Text eingeben und `Sprich jetzt`

Beispiel fuer Referenz-WAVs:
```text
/home/pi/audio/meine_stimme.wav
/home/pi/audio/zweite_probe.wav
```

## Coqui Demos auf dem Pi
Alle eingebauten XTTS-Sprecher wurden als kurze MP3-Demos erzeugt:

```text
/home/pi/Coqui/Demos
```

Jede Datei hat den Namen des Sprechers und enthaelt den Satz:
```text
Das ist die Stimme von <Name>.
```

## Modelle herunterladen

### Piper-Modelle
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

### XTTS-v2-Test auf dem Pi
```bash
/home/pi/Coqui/.venv/bin/tts \
  --text "Hallo, dies ist ein XTTS-v2-Testlauf auf dem Raspberry Pi 5." \
  --model_name tts_models/multilingual/multi-dataset/xtts_v2 \
  --speaker_idx "Ana Florence" \
  --language_idx de \
  --out_path /home/pi/Coqui/xtts_v2_test_de.wav
```

## Interne Endpunkte
- `GET /` liefert die UI
- `GET /options` liefert Engine-, Modell-, Sprach- und Sprecheroptionen fuer das Frontend
- `POST /speak` startet Synthese
- `POST /replay` spielt die letzte Ausgabe erneut ab
- `POST /download` speichert die letzte Ausgabe als MP3

## Dateien
- `index.html` - Frontend fuer Piper und Coqui
- `server.py` - lokaler HTTP-Server, Routing, MP3-Export
- `tts_client.py` - SSH-Bridge, Piper/Coqui-Audio, lokale Wiedergabe
- `run.command` - Start per Doppelklick
- `run.sh` - Shell-Startskript
- `news_to_mp3.py` - optionales Zusatzskript fuer News-Automation, falls im Repo vorhanden

## Verifikation
Geprueft wurden zuletzt:
- Python-Syntax von `server.py` und `tts_client.py`
- lokaler Serverstart
- `GET /options`
- echter Coqui-End-to-End-Lauf ueber den Mac-Server zum Pi
- XTTS-Demo-Erzeugung fuer alle 58 eingebauten Sprecher

## Hinweis zu Finder-Rechten
Wenn Finder nicht in `/Users/michaelhein/Pi5Platte/AI_Radio/Thorsten` schreiben kann, fehlen Rechte auf dem Pi-Mount. Auf dem Pi:
```bash
ssh pi@pi5 "sudo chmod o+w /mnt/meineplatte/AI_Radio/Thorsten"
```
