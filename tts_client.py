import io
import os
import re
import subprocess
import tempfile
import wave
from typing import Iterable, List, Optional


DEFAULT_MODEL_PATH = "/mnt/tts/models/thorsten/de_DE-thorsten-high.onnx"
DEFAULT_CONFIG_PATH = "/mnt/tts/models/thorsten/de_DE-thorsten-high.onnx.json"


def _build_remote_cmd(model_path: str, config_path: str, speaker: Optional[int]) -> str:
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
    cmd.extend(["--output_file", "-"])
    return " ".join(cmd)


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
    cleaned = re.sub(r"\s+", " ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [p.strip() for p in parts if p.strip()]


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

    ssh_cmd = [
        "ssh",
        f"{pi_user}@{pi_host}",
        _build_remote_cmd(model_path, config_path, speaker),
    ]

    try:
        ssh_proc = subprocess.Popen(
            ssh_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ssh not found on this system") from exc

    ssh_stderr: Optional[bytes] = None
    output = bytearray()

    try:
        if ssh_proc.stdin is None or ssh_proc.stdout is None:
            raise RuntimeError("failed to open ssh stdin/stdout")

        ssh_proc.stdin.write(text.encode("utf-8"))
        ssh_proc.stdin.close()

        while True:
            chunk = ssh_proc.stdout.read(65536)
            if not chunk:
                break
            output.extend(chunk)

        ssh_proc.wait()
        if ssh_proc.stderr is not None:
            ssh_stderr = ssh_proc.stderr.read()
    finally:
        if ssh_proc.poll() is None:
            ssh_proc.kill()

    if ssh_proc.returncode != 0:
        raise RuntimeError(_format_err("SSH/Piper failed", ssh_stderr))

    return bytes(output)


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
    temp_path: Optional[str] = None
    afplay_stderr: Optional[bytes] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            temp_path = tmp.name
            tmp.write(wav_bytes)

        try:
            afplay_proc = subprocess.Popen(
                ["afplay", temp_path],
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("afplay not found on this system") from exc

        afplay_proc.wait()
        if afplay_proc.stderr is not None:
            afplay_stderr = afplay_proc.stderr.read()

        if afplay_proc.returncode != 0:
            raise RuntimeError(_format_err("afplay failed", afplay_stderr))
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
