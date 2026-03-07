import argparse
import json
import os
import shlex
import socket
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer

from tts_client import (
    DEFAULT_COQUI_MODEL,
    DEFAULT_COQUI_PYTHON,
    merge_wavs,
    play_wav_bytes,
    split_sentences,
    synthesize_coqui_wav,
    synthesize_wav,
)

DEFAULT_SAVE_DIR = "/Users/michaelhein/Pi5Platte/AI_Radio/Thorsten"
DEFAULT_SAVE_NAME = "latest.mp3"
DEFAULT_MODEL_DIR = "/mnt/tts/models/thorsten"

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

COQUI_XTTS_LANGUAGES = [
    "en",
    "es",
    "fr",
    "de",
    "it",
    "pt",
    "pl",
    "tr",
    "ru",
    "nl",
    "cs",
    "ar",
    "zh-cn",
    "hu",
    "ko",
    "ja",
    "hi",
]

COQUI_XTTS_SPEAKERS = [
    "Claribel Dervla",
    "Daisy Studious",
    "Gracie Wise",
    "Tammie Ema",
    "Alison Dietlinde",
    "Ana Florence",
    "Annmarie Nele",
    "Asya Anara",
    "Brenda Stern",
    "Gitta Nikolina",
    "Henriette Usha",
    "Sofia Hellen",
    "Tammy Grit",
    "Tanja Adelina",
    "Vjollca Johnnie",
    "Andrew Chipper",
    "Badr Odhiambo",
    "Dionisio Schuyler",
    "Royston Min",
    "Viktor Eka",
    "Abrahan Mack",
    "Adde Michal",
    "Baldur Sanjin",
    "Craig Gutsy",
    "Damien Black",
    "Gilberto Mathias",
    "Ilkin Urbano",
    "Kazuhiko Atallah",
    "Ludvig Milivoj",
    "Suad Qasim",
    "Torcull Diarmuid",
    "Viktor Menelaos",
    "Zacharie Aimilios",
    "Nova Hogarth",
    "Maja Ruoho",
    "Uta Obando",
    "Lidiya Szekeres",
    "Chandra MacFarland",
    "Szofi Granger",
    "Camilla Holmström",
    "Lilya Stainthorpe",
    "Zofija Kendrick",
    "Narelle Moon",
    "Barbora MacLean",
    "Alexandra Hisakawa",
    "Alma María",
    "Rosemary Okafor",
    "Ige Behringer",
    "Filip Traverse",
    "Damjan Chapman",
    "Wulf Carlevaro",
    "Aaron Dreschner",
    "Kumar Dahl",
    "Eugenio Mataracı",
    "Ferran Simen",
    "Xavier Hayasaka",
    "Luis Moray",
    "Marcos Rudaski",
]

COQUI_MODELS = {
    DEFAULT_COQUI_MODEL: {
        "label": "XTTS v2",
        "supports_language": True,
        "supports_speaker": True,
        "supports_speaker_wav": True,
        "supports_split_sentences": True,
        "languages": COQUI_XTTS_LANGUAGES,
        "speakers": COQUI_XTTS_SPEAKERS,
        "default_language": "de",
        "default_speaker": "Ana Florence",
    }
}


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    length = int(handler.headers.get("Content-Length", "0"))
    return handler.rfile.read(length) if length > 0 else b""


def _resolve_voice(voice_key: object) -> dict:
    if isinstance(voice_key, str):
        option = VOICE_OPTIONS.get(voice_key.strip().lower())
        if option:
            return option
    return VOICE_OPTIONS["neutral"]


def _resolve_engine(engine_value: object) -> str:
    if isinstance(engine_value, str) and engine_value.strip().lower() == "coqui":
        return "coqui"
    return "piper"


def _resolve_emotion(emotion_value: object) -> int:
    if isinstance(emotion_value, int):
        if emotion_value in EMOTION_SPEAKERS.values():
            return emotion_value
        raise ValueError("emotion speaker id is invalid")
    if isinstance(emotion_value, str):
        cleaned = emotion_value.strip().lower()
        if cleaned.isdigit():
            num = int(cleaned)
            if num in EMOTION_SPEAKERS.values():
                return num
            raise ValueError("emotion speaker id is invalid")
        if cleaned in EMOTION_SPEAKERS:
            return EMOTION_SPEAKERS[cleaned]
    raise ValueError("emotion must be a known key or speaker id")


def _is_local_host(host: str) -> bool:
    cleaned = (host or "").strip().lower()
    if cleaned in {"localhost", "127.0.0.1", "::1"}:
        return True
    local_names = {socket.gethostname().lower(), socket.getfqdn().lower()}
    try:
        local_names.add(os.uname().nodename.lower())
    except AttributeError:
        pass
    return cleaned in local_names


def _resolve_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in {"1", "true", "yes", "on"}:
            return True
        if cleaned in {"0", "false", "no", "off"}:
            return False
    return default


def _resolve_coqui_model(model_name: object) -> str:
    if isinstance(model_name, str) and model_name.strip():
        return model_name.strip()
    return DEFAULT_COQUI_MODEL


def _resolve_coqui_speaker_wavs(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = value.replace("\r", "\n").replace(",", "\n").split("\n")
        return [item.strip() for item in candidates if item.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _remote_file_exists(pi_user: str, pi_host: str, path: str) -> bool:
    if _is_local_host(pi_host):
        return os.path.isfile(path)
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        f"{pi_user}@{pi_host}",
        f"test -f {shlex.quote(path)}",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc.returncode == 0


def _build_options_payload() -> dict:
    return {
        "engines": [
            {"id": "piper", "label": "Piper Thorsten"},
            {"id": "coqui", "label": "Coqui XTTS v2"},
        ],
        "defaults": {
            "engine": "piper",
            "voice": "neutral",
            "emotion": "neutral",
            "coqui_model_name": DEFAULT_COQUI_MODEL,
            "coqui_language": COQUI_MODELS[DEFAULT_COQUI_MODEL]["default_language"],
            "coqui_speaker": COQUI_MODELS[DEFAULT_COQUI_MODEL]["default_speaker"],
            "coqui_split_sentences": True,
            "coqui_use_speaker_wav": False,
            "coqui_speaker_wav": "",
        },
        "piper": {
            "voices": [
                {
                    "id": key,
                    "label": value["label"],
                    "supports_emotion": value["supports_emotion"],
                }
                for key, value in VOICE_OPTIONS.items()
            ],
            "emotions": [
                {"id": key, "label": key.capitalize()}
                for key in EMOTION_SPEAKERS.keys()
            ],
        },
        "coqui": {
            "models": [
                {
                    "id": model_name,
                    "label": config["label"],
                    "supports_language": config["supports_language"],
                    "supports_speaker": config["supports_speaker"],
                    "supports_speaker_wav": config["supports_speaker_wav"],
                    "supports_split_sentences": config["supports_split_sentences"],
                    "default_language": config["default_language"],
                    "default_speaker": config["default_speaker"],
                    "languages": config["languages"],
                    "speakers": config["speakers"],
                }
                for model_name, config in COQUI_MODELS.items()
            ]
        },
    }


class TTSHandler(BaseHTTPRequestHandler):
    server_version = "TTSServer/2.0"

    def do_GET(self) -> None:
        if self.path == "/options":
            data = json.dumps(_build_options_payload()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if self.path in ("/", "/index.html"):
            index_path = os.path.join(self.server.static_dir, "index.html")
            try:
                with open(index_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except FileNotFoundError:
                self.send_error(404, "index.html not found")
            return

        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        if self.path == "/download":
            self._handle_download()
            return

        if self.path == "/replay":
            self._handle_replay()
            return

        if self.path == "/speak":
            self._handle_speak()
            return

        self.send_error(404, "Not found")

    def _handle_download(self) -> None:
        if not self.server.last_wav or not self.server.last_text:
            self.send_error(400, "No cached audio")
            return

        body = _read_body(self)
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        filename = payload.get("filename", "tts.mp3")
        if not isinstance(filename, str) or not filename.strip():
            filename = "tts.mp3"
        if not filename.lower().endswith(".mp3"):
            filename += ".mp3"

        try:
            mp3_bytes = self.server.wav_to_mp3(self.server.last_wav, self.server.last_text)
            os.makedirs(self.server.auto_save_dir, exist_ok=True)
            out_path = os.path.join(self.server.auto_save_dir, filename)
            with open(out_path, "wb") as f:
                f.write(mp3_bytes)
        except Exception as exc:
            data = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        data = json.dumps({"ok": True, "path": out_path}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_replay(self) -> None:
        if not self.server.last_wav:
            self.send_error(400, "No cached audio")
            return
        try:
            play_wav_bytes(self.server.last_wav)
        except Exception as exc:
            data = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        data = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_speak(self) -> None:
        body = _read_body(self)
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        text = payload.get("text", "")
        if not isinstance(text, str) or not text.strip():
            self.send_error(400, "Missing text")
            return

        engine = _resolve_engine(payload.get("engine", "piper"))
        if engine == "coqui":
            self._handle_coqui(payload, text.strip())
            return
        self._handle_piper(payload, text.strip())

    def _handle_piper(self, payload: dict, text: str) -> None:
        voice = _resolve_voice(payload.get("voice", "neutral"))
        speaker = None
        if voice["supports_emotion"]:
            try:
                speaker = _resolve_emotion(payload.get("emotion", "neutral"))
            except ValueError as exc:
                self.send_error(400, str(exc))
                return

        model_path = os.path.join(self.server.model_dir, voice["model"])
        config_path = os.path.join(self.server.model_dir, voice["config"])

        sentences = split_sentences(text)
        if not sentences:
            self.send_error(400, "Missing text")
            return

        if not _remote_file_exists(self.server.pi_user, self.server.pi_host, model_path):
            self.send_error(400, f"Model not found on Pi: {model_path}")
            return
        if not _remote_file_exists(self.server.pi_user, self.server.pi_host, config_path):
            self.send_error(400, f"Config not found on Pi: {config_path}")
            return

        self._begin_stream()

        try:
            total = len(sentences)
            self._send_line(f"START {total}")
            wavs = []
            for idx, sentence in enumerate(sentences, start=1):
                self._send_line(f"PROGRESS {idx}/{total}")
                wavs.append(
                    synthesize_wav(
                        sentence,
                        self.server.pi_host,
                        self.server.pi_user,
                        model_path,
                        config_path,
                        speaker,
                    )
                )

            merged = merge_wavs(wavs)
            self._finalize_audio(text, merged)
        except Exception as exc:
            self._send_line(f"ERROR {exc}")

    def _handle_coqui(self, payload: dict, text: str) -> None:
        model_name = _resolve_coqui_model(payload.get("coqui_model_name"))
        model_config = COQUI_MODELS.get(model_name, COQUI_MODELS[DEFAULT_COQUI_MODEL])

        language = payload.get("coqui_language", model_config["default_language"])
        if not isinstance(language, str) or not language.strip():
            language = model_config["default_language"]
        language = language.strip()

        use_speaker_wav = _resolve_bool(payload.get("coqui_use_speaker_wav"), False)
        speaker_wav = _resolve_coqui_speaker_wavs(payload.get("coqui_speaker_wav"))
        speaker = payload.get("coqui_speaker", model_config["default_speaker"])
        if not isinstance(speaker, str) or not speaker.strip():
            speaker = model_config["default_speaker"]
        speaker = speaker.strip()

        split_sentences = _resolve_bool(payload.get("coqui_split_sentences"), True)

        if use_speaker_wav and not speaker_wav:
            self.send_error(400, "Speaker WAV path missing")
            return

        if not use_speaker_wav and not speaker:
            self.send_error(400, "Speaker missing")
            return

        self._begin_stream()

        try:
            self._send_line("START 1")
            self._send_line("INFO Lade Coqui-Modell auf dem Pi ...")
            wav = synthesize_coqui_wav(
                text,
                self.server.pi_host,
                self.server.pi_user,
                self.server.coqui_python,
                model_name,
                None if use_speaker_wav else speaker,
                language,
                speaker_wav if use_speaker_wav else None,
                split_sentences,
            )
            self._send_line("PROGRESS 1/1")
            self._finalize_audio(text, wav)
        except Exception as exc:
            self._send_line(f"ERROR {exc}")

    def _begin_stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    def _send_line(self, line: str) -> None:
        self.wfile.write((line + "\n").encode("utf-8"))
        self.wfile.flush()

    def _finalize_audio(self, text: str, wav_bytes: bytes) -> None:
        self.server.last_text = text
        self.server.last_wav = wav_bytes
        try:
            mp3_bytes = self.server.wav_to_mp3(wav_bytes, text)
            os.makedirs(self.server.auto_save_dir, exist_ok=True)
            out_path = os.path.join(self.server.auto_save_dir, self.server.auto_save_name)
            with open(out_path, "wb") as f:
                f.write(mp3_bytes)
            self._send_line(f"SAVED {out_path}")
        except Exception as exc:
            self._send_line(f"WARNING could not save mp3: {exc}")

        try:
            play_wav_bytes(wav_bytes)
        except Exception as exc:
            self._send_line(f"WARNING could not play audio: {exc}")
        self._send_line("DONE")

    def log_message(self, format: str, *args) -> None:
        return


class TTSServer(HTTPServer):
    def __init__(self, server_address, handler_class, static_dir: str, pi_host: str, pi_user: str):
        super().__init__(server_address, handler_class)
        self.static_dir = static_dir
        self.pi_host = pi_host
        self.pi_user = pi_user
        self.last_wav: bytes | None = None
        self.last_text: str | None = None
        self.auto_save_dir = os.environ.get("TTS_SAVE_DIR", DEFAULT_SAVE_DIR)
        self.auto_save_name = os.environ.get("TTS_SAVE_NAME", DEFAULT_SAVE_NAME)
        self.model_dir = os.environ.get("TTS_MODEL_DIR", DEFAULT_MODEL_DIR)
        self.coqui_python = os.environ.get("COQUI_PYTHON", DEFAULT_COQUI_PYTHON)

    def wav_to_mp3(self, wav_bytes: bytes, text: str) -> bytes:
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
    parser = argparse.ArgumentParser(description="Local TTS bridge for Piper and Coqui on a Pi")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    parser.add_argument("--pi-host", required=True, help="Pi host (e.g. pi5)")
    parser.add_argument("--pi-user", required=True, help="SSH user (e.g. pi)")
    parser.add_argument("--static", default=os.path.dirname(__file__), help="Directory with index.html")
    args = parser.parse_args()

    server = TTSServer((args.host, args.port), TTSHandler, args.static, args.pi_host, args.pi_user)
    print(f"Serving on http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
