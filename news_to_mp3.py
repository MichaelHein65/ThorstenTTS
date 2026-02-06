import argparse
import json
import os
import subprocess
import tempfile
from datetime import date
from typing import Optional
from urllib.request import Request, urlopen

from tts_client import merge_wavs, split_sentences, synthesize_wav

DEFAULT_OUTPUT = os.path.join("Nachrichten", "Aktuell.mp3")
DEFAULT_MODEL_DIR = "/mnt/tts/models/thorsten"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

VOICE_OPTIONS = {
    "neutral": {
        "label": "Thorsten High",
        "model": "de_DE-thorsten-high.onnx",
        "config": "de_DE-thorsten-high.onnx.json",
        "supports_emotion": False,
    },
    "emotional": {
        "label": "Thorsten Emotional",
        "model": "de_DE-thorsten_emotional-medium.onnx",
        "config": "de_DE-thorsten_emotional-medium.onnx.json",
        "supports_emotion": True,
    },
    "hessisch": {
        "label": "Thorsten Hessisch",
        "model": "de_DE-thorsten_hessisch-medium.onnx",
        "config": "de_DE-thorsten_hessisch-medium.onnx.json",
        "supports_emotion": False,
    },
}

EMOTION_SPEAKERS = {
    "happy": 0,
    "angry": 1,
    "disgusted": 2,
    "drunk": 3,
    "neutral": 4,
    "sleepy": 5,
    "surprised": 6,
    "whisper": 7,
}


DEFAULT_PROMPT = (
    "Schreibe einen kurzen Nachrichtenüberblick auf Deutsch (max. 1200 Zeichen). "
    "Strukturiere ihn in 3-5 knappen Meldungen mit kurzen Überschriften. "
    "Kein Quellenverweis, keine Aufzählungszeichen mit Zahlen. "
    "Beende mit einem kurzen Ausblick-Satz."
)


def load_dotenv(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if raw.startswith("export "):
                raw = raw[len("export ") :].strip()
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


def resolve_voice(voice_key: str) -> dict:
    if isinstance(voice_key, str):
        option = VOICE_OPTIONS.get(voice_key.strip().lower())
        if option:
            return option
    return VOICE_OPTIONS["neutral"]


def resolve_emotion(emotion_value: Optional[str]) -> int:
    if emotion_value is None:
        return EMOTION_SPEAKERS["neutral"]
    cleaned = str(emotion_value).strip().lower()
    if cleaned.isdigit():
        num = int(cleaned)
        if num in EMOTION_SPEAKERS.values():
            return num
        raise ValueError("emotion speaker id is invalid")
    if cleaned in EMOTION_SPEAKERS:
        return EMOTION_SPEAKERS[cleaned]
    raise ValueError("emotion must be a known key or speaker id")


def build_prompt(custom_prompt: Optional[str]) -> str:
    today = date.today().strftime("%d.%m.%Y")
    base = custom_prompt.strip() if custom_prompt else DEFAULT_PROMPT
    return f"Stand: {today}. {base}"


def fetch_news_text(api_key: str, model: str, prompt: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "developer", "content": "Du bist ein präziser deutscher Nachrichtenredakteur."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
    }
    req = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urlopen(req, timeout=60) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8"))
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )
    if not content:
        raise RuntimeError("OpenAI response did not include content")
    return content


def wav_to_mp3(wav_bytes: bytes, text: str) -> bytes:
    wav_path = None
    mp3_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wav_file:
            wav_path = wav_file.name
            wav_file.write(wav_bytes)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as mp3_file:
            mp3_path = mp3_file.name
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            wav_path,
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "3",
            "-metadata",
            f"lyrics={text}",
            mp3_path,
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ffmpeg failed: {err}")
        with open(mp3_path, "rb") as f:
            return f.read()
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass
        if mp3_path and os.path.exists(mp3_path):
            try:
                os.remove(mp3_path)
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate news text via OpenAI and synthesize MP3 with Thorsten")
    parser.add_argument("--pi-host", required=True, help="Pi host (e.g. pi5)")
    parser.add_argument("--pi-user", required=True, help="SSH user (e.g. pi)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output MP3 path")
    parser.add_argument("--voice", default="neutral", choices=VOICE_OPTIONS.keys(), help="Voice preset")
    parser.add_argument("--emotion", default="neutral", help="Emotion for emotional voice")
    parser.add_argument("--model-dir", default=os.environ.get("TTS_MODEL_DIR", DEFAULT_MODEL_DIR))
    parser.add_argument("--openai-model", default=os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL))
    parser.add_argument("--prompt", default=os.environ.get("NEWS_PROMPT"), help="Custom news prompt")
    args = parser.parse_args()

    load_dotenv(os.path.join(os.getcwd(), ".env"))
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY missing. Put it in .env or environment.")

    voice = resolve_voice(args.voice)
    speaker = None
    if voice["supports_emotion"]:
        speaker = resolve_emotion(args.emotion)

    model_path = os.path.join(args.model_dir, voice["model"])
    config_path = os.path.join(args.model_dir, voice["config"])

    prompt = build_prompt(args.prompt)
    text = fetch_news_text(api_key, args.openai_model, prompt)

    sentences = split_sentences(text)
    if not sentences:
        raise SystemExit("OpenAI returned empty text")

    wavs = [
        synthesize_wav(sentence, args.pi_host, args.pi_user, model_path, config_path, speaker)
        for sentence in sentences
    ]
    merged = merge_wavs(wavs)
    mp3_bytes = wav_to_mp3(merged, text)

    out_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(mp3_bytes)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
