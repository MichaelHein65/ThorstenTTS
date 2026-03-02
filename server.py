import argparse
import json
import os
import shlex
import socket
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer

from tts_client import merge_wavs, play_wav_bytes, split_sentences, synthesize_wav

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


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    length = int(handler.headers.get("Content-Length", "0"))
    return handler.rfile.read(length) if length > 0 else b""


def _resolve_voice(voice_key: object) -> dict:
    if isinstance(voice_key, str):
        option = VOICE_OPTIONS.get(voice_key.strip().lower())
        if option:
            return option
    return VOICE_OPTIONS["neutral"]


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


class TTSHandler(BaseHTTPRequestHandler):
    server_version = "TTSServer/1.0"

    def do_GET(self) -> None:
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
            return

        if self.path == "/replay":
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
            return

        if self.path != "/speak":
            self.send_error(404, "Not found")
            return

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

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def send_line(line: str) -> None:
            self.wfile.write((line + "\n").encode("utf-8"))
            self.wfile.flush()

        try:
            if not _remote_file_exists(self.server.pi_user, self.server.pi_host, model_path):
                self.send_error(400, f"Model not found on Pi: {model_path}")
                return
            if not _remote_file_exists(self.server.pi_user, self.server.pi_host, config_path):
                self.send_error(400, f"Config not found on Pi: {config_path}")
                return
            total = len(sentences)
            send_line(f"START {total}")
            wavs = []
            for idx, sentence in enumerate(sentences, start=1):
                send_line(f"PROGRESS {idx}/{total}")
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
            self.server.last_text = text
            self.server.last_wav = merged
            try:
                mp3_bytes = self.server.wav_to_mp3(merged, text)
                os.makedirs(self.server.auto_save_dir, exist_ok=True)
                out_path = os.path.join(self.server.auto_save_dir, self.server.auto_save_name)
                with open(out_path, "wb") as f:
                    f.write(mp3_bytes)
                send_line(f"SAVED {out_path}")
            except Exception as exc:
                send_line(f"WARNING could not save mp3: {exc}")
            try:
                play_wav_bytes(merged)
            except Exception as exc:
                send_line(f"WARNING could not play audio: {exc}")
            send_line("DONE")
        except Exception as exc:
            send_line(f"ERROR {exc}")
            return

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
    parser = argparse.ArgumentParser(description="Local TTS bridge for Piper on a Pi")
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
