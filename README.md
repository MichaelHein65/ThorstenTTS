# ThorstenTTS

Lokale Browser‑App für deutsche TTS mit **Piper** auf einem **Raspberry Pi 5** und Wiedergabe/MP3‑Speicherung auf dem Mac.

## Features
- Web‑UI mit Texteingabe
- Auswahl von Thorsten High, Emotional (Emotionen) und Hessisch
- Satz‑weise Synthese mit Fortschrittsanzeige
- Replay der letzten Ausgabe (ohne Neu‑Synthese)
- MP3‑Export mit Lyrics‑Tag (ID3)
- Automatisches Speichern der MP3 auf die Pi‑Platte (gemountet auf dem Mac)

## Voraussetzungen
- macOS mit Python 3
- SSH‑Zugriff auf den Pi5 (Host z. B. `pi5`)
- Piper auf dem Pi mit folgenden Fix‑Pfaden:
  - `/usr/local/bin/piper`
  - `--espeak_data /opt/piper/espeak-ng-data`
  - `--model /mnt/tts/models/thorsten/de_DE-thorsten-high.onnx`
  - `--config /mnt/tts/models/thorsten/de_DE-thorsten-high.onnx.json`
  - Zusatzmodelle im selben Ordner:
    - `de_DE-thorsten_emotional-medium.onnx` (+ `.json`)
    - `de_DE-thorsten_hessisch-medium.onnx` (+ `.json`)
- `ffmpeg` auf dem Mac (für MP3 + Lyrics‑Tag)
- Gemountetes Pi‑Laufwerk auf dem Mac: `/Users/michaelhein/Pi5Platte`

## Start (Terminal)
```bash
python3 "/Users/michaelhein/* VSC/20260202 Thorsten/server.py" --host 0.0.0.0 --port 8080 --pi-host pi5 --pi-user pi
```
Dann im Browser öffnen:
```
http://127.0.0.1:8080
```

## Start (Doppelklick)
`run.command` doppelklicken. Es startet den Server und öffnet Safari.

## MP3‑Speicherort
Standardmäßig wird jede Synthese automatisch gespeichert nach:
```
/Users/michaelhein/Pi5Platte/AI_Radio/Thorsten/latest.mp3
```
Anpassbar via Umgebungsvariablen:
```bash
TTS_SAVE_DIR="/Users/michaelhein/Pi5Platte/AI_Radio/Thorsten" \
TTS_SAVE_NAME="mein.mp3" \
TTS_MODEL_DIR="/mnt/tts/models/thorsten" \
python3 "server.py" --host 0.0.0.0 --port 8080 --pi-host pi5 --pi-user pi
```

## MP3‑Export per Button
Der Button **„MP3 speichern“** fragt nach einem Dateinamen und speichert direkt in den oben genannten Zielordner (kein Safari‑Download‑Ordner). Der Text wird im MP3 als **Lyrics** gespeichert.

## Modelle herunterladen (Pi)
Die Thorsten‑Voice Piper‑Seite verlinkt Model + Konfiguration für Neutral, Emotional und Hessisch. Die App erwartet die Dateinamen wie unten.

Direkt auf dem Pi laden:
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

## Nachrichten‑Automatik (OpenAI → Thorsten → MP3)
Die Automatik erzeugt per OpenAI‑API einen kurzen Nachrichtentext und baut daraus eine MP3, gespeichert als `Nachrichten/Aktuell.mp3`.

1) `.env` anlegen (siehe `.env.example`):
```bash
cp .env.example .env
```

2) Script ausführen:
```bash
python3 news_to_mp3.py --pi-host pi5 --pi-user pi
```

Optional:
```bash
python3 news_to_mp3.py --pi-host pi5 --pi-user pi --voice emotional --emotion happy
python3 news_to_mp3.py --pi-host pi5 --pi-user pi --output Nachrichten/Aktuell.mp3
```

## Dateien
- `server.py` – lokaler HTTP‑Server + Fortschritt + MP3‑Export
- `tts_client.py` – SSH/Piper‑Client, Satz‑Split, WAV‑Merge
- `index.html` – Frontend
- `run.command` – Start per Doppelklick
- `news_to_mp3.py` – OpenAI‑News → Thorsten → MP3

## Hinweis zu Finder‑Rechten
Wenn Finder nicht in `/Users/michaelhein/Pi5Platte/AI_Radio/Thorsten` schreiben kann, fehlen Rechte auf dem Pi‑Mount. Auf dem Pi:
```bash
ssh pi@pi5 "sudo chmod o+w /mnt/meineplatte/AI_Radio/Thorsten"
```
