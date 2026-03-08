# Changelog

## 0.4.1 - 2026-03-08
- Restrict the app model selection to Thorsten TTS voices only.
- Remove Coqui controls from the web UI and simplify the client payload.
- Limit `/options` to Thorsten voice data and reject direct Coqui requests.
- Refresh the README to match the Thorsten-only app behavior.

## 0.4.0 - 2026-03-07
- Extend the UI and backend from Piper-only to Piper plus Coqui XTTS v2.
- Add dynamic engine, model, language, speaker and reference-WAV options via `/options`.
- Add Coqui synthesis routing over SSH to the Pi and normalize playback for local macOS output.
- Document the combined Piper/Coqui setup, XTTS compatibility pin and generated demo voices.

## 0.3.0 - 2026-02-06
- Add news automation script using OpenAI API to generate text and synthesize MP3.
- Document .env configuration and news automation usage.

## 0.2.0 - 2026-02-04
- Add voice selection (High/Emotional/Hessisch) and emotion selection in the UI.
- Add model/emotion routing on the server, including model existence checks on the Pi.
- Document model download commands and model directory override.
