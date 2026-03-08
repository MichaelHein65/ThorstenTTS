import io
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import unicodedata
import wave
from typing import Iterable, List, Optional


DEFAULT_MODEL_PATH = "/mnt/tts/models/thorsten/de_DE-thorsten-high.onnx"
DEFAULT_CONFIG_PATH = "/mnt/tts/models/thorsten/de_DE-thorsten-high.onnx.json"
DEFAULT_TTS_BACKEND = "piper"
DEFAULT_COQUI_TTS_BIN = "/home/pi/Coqui/.venv/bin/tts"
DEFAULT_COQUI_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
DEFAULT_COQUI_LANGUAGE = "de"
DEFAULT_COQUI_SPEAKER = "Asya Anara"
DEFAULT_COQUI_WORK_DIR = "/home/pi/Coqui/tmp"


def _build_piper_cmd(model_path: str, config_path: str, speaker: Optional[int]) -> List[str]:
    sentence_silence = os.environ.get("TTS_SENTENCE_SILENCE", "0.50").strip()
    cmd = [
        "/usr/local/bin/piper",
        "--espeak_data",
        "/opt/piper/espeak-ng-data",
        "--model",
        model_path,
        "--config",
        config_path,
    ]
    if speaker is not None:
        cmd.extend(["--speaker", str(speaker)])
    if sentence_silence:
        cmd.extend(["--sentence_silence", sentence_silence])
    cmd.extend(["--output_file", "-"])
    return cmd


def _tts_backend() -> str:
    backend = os.environ.get("TTS_BACKEND", DEFAULT_TTS_BACKEND).strip().lower()
    if backend in {"piper", "coqui"}:
        return backend
    raise RuntimeError("TTS_BACKEND must be 'piper' or 'coqui'")


def _coqui_settings() -> dict:
    return {
        "tts_bin": os.environ.get("COQUI_TTS_BIN", DEFAULT_COQUI_TTS_BIN).strip() or DEFAULT_COQUI_TTS_BIN,
        "model": os.environ.get("COQUI_MODEL", DEFAULT_COQUI_MODEL).strip() or DEFAULT_COQUI_MODEL,
        "language": os.environ.get("COQUI_LANGUAGE", DEFAULT_COQUI_LANGUAGE).strip() or DEFAULT_COQUI_LANGUAGE,
        "speaker": os.environ.get("COQUI_SPEAKER", DEFAULT_COQUI_SPEAKER).strip() or DEFAULT_COQUI_SPEAKER,
        "speaker_wav": os.environ.get("COQUI_SPEAKER_WAV", "").strip(),
        "work_dir": os.environ.get("COQUI_WORK_DIR", DEFAULT_COQUI_WORK_DIR).strip() or DEFAULT_COQUI_WORK_DIR,
    }


def _build_remote_cmd(model_path: str, config_path: str, speaker: Optional[int]) -> str:
    return " ".join(shlex.quote(part) for part in _build_piper_cmd(model_path, config_path, speaker))


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


def _run_cmd_with_stdin(
    cmd: List[str],
    stdin_data: bytes,
    err_prefix: str,
    not_found_msg: str,
) -> bytes:
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(not_found_msg) from exc

    proc_stderr: Optional[bytes] = None
    output = bytearray()

    try:
        if proc.stdin is None or proc.stdout is None:
            raise RuntimeError("failed to open process stdin/stdout")

        proc.stdin.write(stdin_data)
        proc.stdin.close()

        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            output.extend(chunk)

        proc.wait()
        if proc.stderr is not None:
            proc_stderr = proc.stderr.read()
    finally:
        if proc.poll() is None:
            proc.kill()

    if proc.returncode != 0:
        raise RuntimeError(_format_err(err_prefix, proc_stderr))
    return bytes(output)


def _run_cmd_capture(
    cmd: List[str],
    err_prefix: str,
    not_found_msg: str,
) -> bytes:
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise RuntimeError(not_found_msg) from exc

    if proc.returncode != 0:
        raise RuntimeError(_format_err(err_prefix, proc.stderr))
    return proc.stdout


def _format_err(prefix: str, stderr: Optional[bytes]) -> str:
    detail = ""
    if stderr:
        try:
            detail = stderr.decode("utf-8", errors="replace").strip()
        except Exception:
            detail = str(stderr)
    if detail:
        return f"{prefix}: {detail}"
    return prefix


def _sanitize_text_for_coqui(text: str) -> str:
    cleaned = unicodedata.normalize("NFKC", text or "")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    chars = []
    for ch in cleaned:
        if ch in "\n\t":
            chars.append(ch)
            continue
        if unicodedata.category(ch) in {"Cc", "Cf", "Cs", "Co", "Cn"}:
            chars.append(" ")
            continue
        chars.append(ch)
    cleaned = "".join(chars)
    cleaned = re.sub(r"[‐‑‒]", " ", cleaned)
    replacements = {
        "„": "",
        "“": "",
        "\"": "",
        "’": "'",
        "–": ", ",
        "—": ", ",
        "‑": " ",
        "&": " und ",
        "/": " ",
        ";": ",",
        ":": ",",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"[()\[\]{}<>]", " ", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    return cleaned.strip()


def split_sentences(text: str) -> List[str]:
    if not isinstance(text, str):
        return []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    if _tts_backend() == "coqui":
        normalized = _sanitize_text_for_coqui(normalized)
        max_chars_raw = os.environ.get("TTS_COQUI_MAX_CHARS", "1800").strip()
        try:
            max_chars = max(400, int(max_chars_raw))
        except ValueError:
            max_chars = 1800

        lines: List[str] = []
        for raw_line in normalized.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("- "):
                line = line[2:].strip()
            if not line:
                continue
            if re.fullmatch(r"[A-ZÄÖÜ0-9][A-ZÄÖÜ0-9\s\-]*", line):
                line = line + "."
            lines.append(line)

        chunks: List[str] = []
        current: List[str] = []
        current_len = 0
        for line in lines:
            projected = current_len + len(line) + (1 if current else 0)
            if current and projected > max_chars:
                chunks.append(" ".join(current).strip())
                current = [line]
                current_len = len(line)
                continue
            current.append(line)
            current_len = projected
        if current:
            chunks.append(" ".join(current).strip())
        return chunks

    out: List[str] = []

    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("- "):
            line = line[2:].strip()
            if not line:
                continue
            # Ganze Nachricht als Block sprechen, damit zwischen Meldungen
            # ein deutlicherer Segmentwechsel entsteht.
            out.append(line)
            continue

        # Ueberschriften als eigene Sprecheinheit behandeln.
        if re.fullmatch(r"[A-ZÄÖÜ0-9][A-ZÄÖÜ0-9\s\-]*", line):
            out.append(line + ".")
            continue

        parts = re.split(r"(?<=[.!?])\s+", line)
        out.extend(part.strip() for part in parts if part.strip())

    return out


def synthesize_wav(
    text: str,
    pi_host: str,
    pi_user: str,
    model_path: Optional[str] = None,
    config_path: Optional[str] = None,
    speaker: Optional[int] = None,
) -> bytes:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    text = text.strip() + "\n"

    model_path = model_path or DEFAULT_MODEL_PATH
    config_path = config_path or DEFAULT_CONFIG_PATH
    if speaker is not None:
        try:
            speaker = int(speaker)
        except (TypeError, ValueError) as exc:
            raise ValueError("speaker must be an integer") from exc

    backend = _tts_backend()
    if backend == "piper":
        text_bytes = text.encode("utf-8")
        if _is_local_host(pi_host):
            return _run_cmd_with_stdin(
                _build_piper_cmd(model_path, config_path, speaker),
                text_bytes,
                "Local Piper failed",
                "piper not found on this system",
            )

        ssh_cmd = ["ssh", f"{pi_user}@{pi_host}", _build_remote_cmd(model_path, config_path, speaker)]
        return _run_cmd_with_stdin(
            ssh_cmd,
            text_bytes,
            "SSH/Piper failed",
            "ssh not found on this system",
        )

    settings = _coqui_settings()
    text = _sanitize_text_for_coqui(text)
    if not text:
        raise ValueError("text is empty after Coqui sanitization")
    if _is_local_host(pi_host):
        os.makedirs(settings["work_dir"], exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="xtts_local_", dir=settings["work_dir"]) as tmp:
            out_path = os.path.join(tmp, "tts.wav")
            cmd = [
                settings["tts_bin"],
                "--text",
                text.strip(),
                "--model_name",
                settings["model"],
                "--language_idx",
                settings["language"],
                "--out_path",
                out_path,
            ]
            if settings["speaker_wav"]:
                cmd.extend(["--speaker_wav", settings["speaker_wav"]])
            else:
                cmd.extend(["--speaker_idx", settings["speaker"]])
            try:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except FileNotFoundError as exc:
                raise RuntimeError("Coqui TTS binary not found") from exc
            if proc.returncode != 0:
                raise RuntimeError(_format_err("Local Coqui XTTS failed", proc.stderr))
            with open(out_path, "rb") as wav_f:
                return wav_f.read()

    remote_parts = [
        shlex.quote(settings["tts_bin"]),
        "--text",
        shlex.quote(text.strip()),
        "--model_name",
        shlex.quote(settings["model"]),
        "--language_idx",
        shlex.quote(settings["language"]),
    ]
    if settings["speaker_wav"]:
        remote_parts.extend(["--speaker_wav", shlex.quote(settings["speaker_wav"])])
    else:
        remote_parts.extend(["--speaker_idx", shlex.quote(settings["speaker"])])
    remote_parts.extend(["--out_path", '"$tmp"'])
    remote_cmd = (
        "set -e; "
        "mkdir -p "
        + shlex.quote(settings["work_dir"])
        + "; "
        "tmp=$(mktemp "
        + shlex.quote(os.path.join(settings["work_dir"], "xtts_XXXXXX.wav"))
        + "); "
        'trap \'rm -f "$tmp"\' EXIT; '
        + " ".join(remote_parts)
        + ' >/dev/null 2>&1; cat "$tmp"'
    )
    ssh_cmd = ["ssh", f"{pi_user}@{pi_host}", remote_cmd]
    return _run_cmd_capture(
        ssh_cmd,
        "SSH/Coqui XTTS failed",
        "ssh not found on this system",
    )


def merge_wavs(wav_chunks: Iterable[bytes]) -> bytes:
    chunks = list(wav_chunks)
    if not chunks:
        raise ValueError("no wav data to merge")

    pause_raw = os.environ.get("TTS_CHUNK_PAUSE_SEC", "0.65").strip()
    try:
        pause_seconds = max(0.0, float(pause_raw))
    except ValueError:
        pause_seconds = 0.65

    out_buffer = io.BytesIO()
    params = None
    with wave.open(out_buffer, "wb") as out_wav:
        for idx, chunk in enumerate(chunks):
            with wave.open(io.BytesIO(chunk), "rb") as in_wav:
                if params is None:
                    params = in_wav.getparams()
                    out_wav.setparams(params)
                else:
                    # Best-effort merge: keep the first file's params and append frames.
                    # This avoids hard failures if Piper outputs slightly different headers.
                    pass
                out_wav.writeframes(in_wav.readframes(in_wav.getnframes()))
                if idx < len(chunks) - 1 and params is not None and pause_seconds > 0.0:
                    pause_frames = int(params.framerate * pause_seconds)
                    if pause_frames > 0:
                        silence = b"\x00" * (pause_frames * params.nchannels * params.sampwidth)
                        out_wav.writeframes(silence)
    return out_buffer.getvalue()


def play_wav_bytes(wav_bytes: bytes) -> None:
    enabled_raw = os.environ.get("TTS_ENABLE_PLAYBACK", "1").strip().lower()
    if enabled_raw in {"0", "false", "no", "off"}:
        return

    temp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            temp_path = tmp.name
            tmp.write(wav_bytes)

        if sys.platform == "darwin":
            player_cmds = [["afplay", temp_path]]
        else:
            player_cmds = [
                ["aplay", "-q", temp_path],
                ["paplay", temp_path],
                ["ffplay", "-autoexit", "-nodisp", "-loglevel", "error", temp_path],
            ]

        errors: List[str] = []
        available = 0
        for cmd in player_cmds:
            if shutil.which(cmd[0]) is None:
                continue
            available += 1
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode == 0:
                return
            errors.append(_format_err(f"{cmd[0]} failed", proc.stderr))

        if available == 0:
            raise RuntimeError("no supported audio player found")
        raise RuntimeError("; ".join(errors))
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def speak(
    text: str,
    pi_host: str,
    pi_user: str,
    model_path: Optional[str] = None,
    config_path: Optional[str] = None,
    speaker: Optional[int] = None,
) -> None:
    sentences = split_sentences(text)
    if not sentences:
        raise ValueError("text must be a non-empty string")
    wavs = [
        synthesize_wav(sentence, pi_host, pi_user, model_path, config_path, speaker)
        for sentence in sentences
    ]
    merged = merge_wavs(wavs)
    play_wav_bytes(merged)
