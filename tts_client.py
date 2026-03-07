import io
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import wave
from typing import Iterable, List, Optional


DEFAULT_MODEL_PATH = "/mnt/tts/models/thorsten/de_DE-thorsten-high.onnx"
DEFAULT_CONFIG_PATH = "/mnt/tts/models/thorsten/de_DE-thorsten-high.onnx.json"
DEFAULT_COQUI_PYTHON = "/home/pi/Coqui/.venv/bin/python"
DEFAULT_COQUI_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"

COQUI_REMOTE_SCRIPT = textwrap.dedent(
    """
    import json
    import sys
    import traceback

    import soundfile as sf
    from TTS.api import TTS

    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        tts = TTS(model_name=payload["model_name"], gpu=False)
        kwargs = {}
        if payload.get("speaker"):
            kwargs["speaker"] = payload["speaker"]
        if payload.get("language"):
            kwargs["language"] = payload["language"]
        if payload.get("speaker_wav"):
            kwargs["speaker_wav"] = payload["speaker_wav"]
        wav = tts.tts(
            text=payload["text"],
            split_sentences=payload.get("split_sentences", True),
            **kwargs,
        )
        sample_rate = getattr(getattr(tts, "synthesizer", None), "output_sample_rate", 24000)
        sf.write(sys.stdout.buffer, wav, sample_rate, format="WAV", subtype="PCM_16")
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    """
).strip()


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


def _build_remote_cmd(model_path: str, config_path: str, speaker: Optional[int]) -> str:
    return shlex.join(_build_piper_cmd(model_path, config_path, speaker))


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

        if stdin_data:
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


def _run_ssh_command(pi_host: str, pi_user: str, remote_command: str, stdin_bytes: bytes) -> bytes:
    return _run_cmd_with_stdin(
        ["ssh", f"{pi_user}@{pi_host}", remote_command],
        stdin_bytes,
        "SSH command failed",
        "ssh not found on this system",
    )


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
            out.append(line)
            continue

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
    text_bytes = (text.strip() + "\n").encode("utf-8")

    model_path = model_path or DEFAULT_MODEL_PATH
    config_path = config_path or DEFAULT_CONFIG_PATH
    if speaker is not None:
        try:
            speaker = int(speaker)
        except (TypeError, ValueError) as exc:
            raise ValueError("speaker must be an integer") from exc

    if _is_local_host(pi_host):
        return _run_cmd_with_stdin(
            _build_piper_cmd(model_path, config_path, speaker),
            text_bytes,
            "Local Piper failed",
            "piper not found on this system",
        )

    return _run_ssh_command(
        pi_host,
        pi_user,
        _build_remote_cmd(model_path, config_path, speaker),
        text_bytes,
    )


def synthesize_coqui_wav(
    text: str,
    pi_host: str,
    pi_user: str,
    coqui_python: Optional[str] = None,
    model_name: Optional[str] = None,
    speaker: Optional[str] = None,
    language: Optional[str] = None,
    speaker_wav: Optional[List[str]] = None,
    split_sentences: bool = True,
) -> bytes:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")

    cleaned_speaker = speaker.strip() if isinstance(speaker, str) else None
    cleaned_language = language.strip() if isinstance(language, str) else None
    cleaned_wavs = [path.strip() for path in (speaker_wav or []) if isinstance(path, str) and path.strip()]

    payload = {
        "text": text.strip(),
        "model_name": (model_name or DEFAULT_COQUI_MODEL).strip(),
        "speaker": cleaned_speaker or None,
        "language": cleaned_language or None,
        "speaker_wav": cleaned_wavs or None,
        "split_sentences": bool(split_sentences),
    }

    python_bin = coqui_python or DEFAULT_COQUI_PYTHON
    stdin_bytes = json.dumps(payload).encode("utf-8")
    if _is_local_host(pi_host):
        return _run_cmd_with_stdin(
            [python_bin, "-c", COQUI_REMOTE_SCRIPT],
            stdin_bytes,
            "Local Coqui failed",
            "coqui python not found on this system",
        )

    remote_cmd = shlex.quote(python_bin)
    remote_cmd += " -c "
    remote_cmd += shlex.quote(COQUI_REMOTE_SCRIPT)
    return _run_ssh_command(pi_host, pi_user, remote_cmd, stdin_bytes)


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

    source_path: Optional[str] = None
    play_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            source_path = tmp.name
            tmp.write(wav_bytes)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            play_path = tmp.name

        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            source_path,
            "-c:a",
            "pcm_s16le",
            play_path,
        ]
        ffmpeg_proc = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ffmpeg_proc.returncode != 0:
            err = ffmpeg_proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ffmpeg playback conversion failed: {err}")

        if sys.platform == "darwin":
            player_cmds = [["afplay", play_path]]
        else:
            player_cmds = [
                ["aplay", "-q", play_path],
                ["paplay", play_path],
                ["ffplay", "-autoexit", "-nodisp", "-loglevel", "error", play_path],
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
        if source_path and os.path.exists(source_path):
            try:
                os.remove(source_path)
            except OSError:
                pass
        if play_path and os.path.exists(play_path):
            try:
                os.remove(play_path)
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
