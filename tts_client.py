import io
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import wave
from typing import Iterable, List, Optional


DEFAULT_MODEL_PATH = "/mnt/tts/models/thorsten/de_DE-thorsten-high.onnx"
DEFAULT_CONFIG_PATH = "/mnt/tts/models/thorsten/de_DE-thorsten-high.onnx.json"


def _build_piper_cmd(model_path: str, config_path: str, speaker: Optional[int]) -> List[str]:
    sentence_silence = os.environ.get("TTS_SENTENCE_SILENCE", "0.35").strip()
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


def split_sentences(text: str) -> List[str]:
    if not isinstance(text, str):
        return []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    out: List[str] = []

    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("- "):
            line = line[2:].strip()
            if not line:
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


def merge_wavs(wav_chunks: Iterable[bytes]) -> bytes:
    chunks = list(wav_chunks)
    if not chunks:
        raise ValueError("no wav data to merge")

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
