# ThorstenTTS

Lokale Browser‑App für deutsche TTS mit **Piper** auf einem **Raspberry Pi 5** und Wiedergabe/MP3‑Speicherung auf dem Mac.

## Features
- Web‑UI mit Texteingabe
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
python3 "server.py" --host 0.0.0.0 --port 8080 --pi-host pi5 --pi-user pi
```

## MP3‑Export per Button
Der Button **„MP3 speichern“** fragt nach einem Dateinamen und speichert direkt in den oben genannten Zielordner (kein Safari‑Download‑Ordner). Der Text wird im MP3 als **Lyrics** gespeichert.

## Dateien
- `server.py` – lokaler HTTP‑Server + Fortschritt + MP3‑Export
- `tts_client.py` – SSH/Piper‑Client, Satz‑Split, WAV‑Merge
- `index.html` – Frontend
- `run.command` – Start per Doppelklick

## Hinweis zu Finder‑Rechten
Wenn Finder nicht in `/Users/michaelhein/Pi5Platte/AI_Radio/Thorsten` schreiben kann, fehlen Rechte auf dem Pi‑Mount. Auf dem Pi:
```bash
ssh pi@pi5 "sudo chmod o+w /mnt/meineplatte/AI_Radio/Thorsten"
```
