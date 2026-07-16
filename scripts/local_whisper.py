#!/usr/bin/env python3
"""Fail-closed local transcription through whisper.cpp.

This module never downloads a model and never falls back to a network provider.
It converts media to 16 kHz PCM, runs ``whisper-cli`` with experimental
word-level timestamps, and shapes the result into the Deepgram-compatible
utterance/word contract used by SEGMENTER, CLIPPER, and PRODUCER.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

from local_whisper_parser import WhisperParseError, parse_whisper_json


PROVIDER_ENV = "SNIPER_TRANSCRIBE_PROVIDER"
EXECUTION_MODE_ENV = "SNIPER_EXECUTION_MODE"
DEEPGRAM_PROVIDER = "deepgram"
LOCAL_PROVIDER = "local-whisper"
VALID_PROVIDERS = {DEEPGRAM_PROVIDER, LOCAL_PROVIDER}
Emit = Optional[Callable[[dict], None]]


class LocalWhisperError(RuntimeError):
    """A local-ASR preflight, execution, or output-contract failure."""


@dataclass(frozen=True)
class WhisperRuntime:
    """Resolved local binaries/model and bounded execution settings."""

    binary: str
    model: str
    language: str
    threads: int
    timeout_s: int
    force_cpu: bool


@dataclass(frozen=True)
class LocalTranscribeRequest:
    """One media input plus optional timeline facts supplied by its caller."""

    path: str
    timeline_offset: Optional[float] = None
    duration: Optional[float] = None
    speaker: Optional[int] = None


def transcription_provider(environ: Optional[Mapping[str, str]] = None) -> str:
    """Resolve provider; local execution defaults fail-closed to local Whisper."""
    env = os.environ if environ is None else environ
    explicit = env.get(PROVIDER_ENV, "").strip().lower()
    local_mode = env.get(EXECUTION_MODE_ENV, "").strip().lower() == "local"
    provider = explicit or (LOCAL_PROVIDER if local_mode else DEEPGRAM_PROVIDER)
    if provider not in VALID_PROVIDERS:
        choices = "|".join(sorted(VALID_PROVIDERS))
        raise LocalWhisperError(f"{PROVIDER_ENV} must be {choices} (got {provider!r})")
    return provider


def _explicit_path(env: Mapping[str, str], name: str) -> Optional[Path]:
    raw = env.get(name, "").strip()
    return Path(raw).expanduser() if raw else None


def resolve_whisper_binary(environ: Optional[Mapping[str, str]] = None) -> str:
    """Resolve whisper-cli locally; an invalid explicit override fails loudly."""
    env = os.environ if environ is None else environ
    explicit = _explicit_path(env, "WHISPER_CPP_BIN")
    if explicit:
        if explicit.is_file() and os.access(explicit, os.X_OK):
            return str(explicit)
        raise LocalWhisperError(f"WHISPER_CPP_BIN is not executable: {explicit}")
    found = shutil.which("whisper-cli")
    if found:
        return found
    for candidate in (Path("/opt/homebrew/bin/whisper-cli"), Path("/usr/local/bin/whisper-cli")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise LocalWhisperError("whisper-cli not found; install whisper.cpp or set WHISPER_CPP_BIN")


def resolve_whisper_model(environ: Optional[Mapping[str, str]] = None) -> str:
    """Resolve an existing model only; model downloads are deliberately forbidden."""
    env = os.environ if environ is None else environ
    explicit = _explicit_path(env, "WHISPER_CPP_MODEL")
    if explicit:
        if explicit.is_file():
            return str(explicit)
        raise LocalWhisperError(f"WHISPER_CPP_MODEL does not exist: {explicit}")
    project_root = Path(__file__).resolve().parents[1]
    candidates = (
        Path.home() / ".cache/hyperframes/whisper/models/ggml-small.en.bin",
        project_root / "models/ggml-small.en.bin",
        Path("/opt/homebrew/share/whisper-cpp/models/ggml-small.en.bin"),
        Path("/usr/local/share/whisper-cpp/models/ggml-small.en.bin"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise LocalWhisperError("local Whisper model not found; set WHISPER_CPP_MODEL (no auto-download)")


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError as exc:
        raise LocalWhisperError(f"{name} must be an integer") from exc
    if value <= 0:
        raise LocalWhisperError(f"{name} must be positive")
    return value


def resolve_runtime(environ: Optional[Mapping[str, str]] = None) -> WhisperRuntime:
    """Preflight the complete local whisper.cpp runtime."""
    env = os.environ if environ is None else environ
    threads = _positive_int(env, "WHISPER_CPP_THREADS", min(8, os.cpu_count() or 4))
    timeout_s = _positive_int(env, "WHISPER_CPP_TIMEOUT_SECONDS", 3600)
    return WhisperRuntime(
        binary=resolve_whisper_binary(env),
        model=resolve_whisper_model(env),
        language=env.get("WHISPER_CPP_LANGUAGE", "en").strip() or "en",
        threads=threads,
        timeout_s=timeout_s,
        force_cpu=env.get("WHISPER_CPP_NO_GPU") == "1",
    )


def _probe_audio(path: str) -> tuple[float, float]:
    cmd = ["ffprobe", "-v", "error", "-show_entries",
           "format=duration:stream=start_time,codec_type", "-of", "json", path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise LocalWhisperError(proc.stderr.strip() or "ffprobe failed")
    data = json.loads(proc.stdout)
    duration = float(data.get("format", {}).get("duration", 0) or 0)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if audio is None:
        raise LocalWhisperError(f"media has no audio stream: {path}")
    raw_start = audio.get("start_time")
    start = float(raw_start) if raw_start not in (None, "N/A") else 0.0
    return start, duration


def _extract_pcm(path: str, wav_path: str) -> None:
    cmd = ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
           "-i", path, "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
           "-c:a", "pcm_s16le", wav_path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise LocalWhisperError(proc.stderr.strip()[-1000:] or "ffmpeg PCM extraction failed")


def _whisper_command(runtime: WhisperRuntime, wav_path: str, prefix: str, cpu: bool) -> list[str]:
    cmd = [runtime.binary, "-m", runtime.model, "-f", wav_path,
           "-l", runtime.language, "-t", str(runtime.threads), "-ml", "1",
           "-sow", "-ojf", "-of", prefix, "-np"]
    if cpu:
        cmd.insert(1, "--no-gpu")
    return cmd


def _attempt_whisper(runtime: WhisperRuntime, wav_path: str, prefix: str, cpu: bool) -> tuple[Optional[dict], str]:
    output_path = Path(prefix + ".json")
    output_path.unlink(missing_ok=True)
    try:
        proc = subprocess.run(_whisper_command(runtime, wav_path, prefix, cpu),
                              capture_output=True, text=True, timeout=runtime.timeout_s)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {runtime.timeout_s}s"
    tail = (proc.stderr or proc.stdout or "").strip()[-1500:]
    if proc.returncode != 0 or not output_path.is_file():
        return None, f"exit={proc.returncode}; {tail or 'no JSON output'}"
    try:
        return json.loads(output_path.read_text()), ""
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"invalid whisper JSON: {exc}"


def _run_whisper(runtime: WhisperRuntime, wav_path: str, prefix: str, emit: Emit) -> dict:
    attempts = [True] if runtime.force_cpu else [False, True]
    errors: list[str] = []
    for cpu in attempts:
        payload, error = _attempt_whisper(runtime, wav_path, prefix, cpu)
        if payload is not None:
            return payload
        errors.append(("cpu" if cpu else "gpu") + ": " + error)
        if not cpu and emit:
            emit({"status": "local_whisper_cpu_fallback", "reason": error[-300:]})
    raise LocalWhisperError("whisper-cli failed; " + " | ".join(errors))


def transcribe_media(request: LocalTranscribeRequest, emit: Emit = None) -> dict:
    """Transcribe one media file locally, returning a Deepgram-compatible payload."""
    path = str(Path(request.path).expanduser().resolve())
    if not Path(path).is_file():
        raise LocalWhisperError(f"media not found: {path}")
    probed_offset, probed_duration = _probe_audio(path)
    timeline_offset = probed_offset if request.timeline_offset is None else request.timeline_offset
    duration = probed_duration if request.duration is None else request.duration
    runtime = resolve_runtime()
    if emit:
        emit({"status": "extracting_audio", "provider": LOCAL_PROVIDER})
    with tempfile.TemporaryDirectory(prefix="sniper-whisper-") as work:
        wav_path = str(Path(work) / "audio.wav")
        _extract_pcm(path, wav_path)
        if emit:
            size_mb = round(Path(wav_path).stat().st_size / (1024 * 1024), 1)
            emit({"status": "audio_extracted", "size_mb": size_mb,
                  "audio_offset": timeline_offset})
            emit({"status": "transcribing_chunk", "chunk": 1, "total": 1,
                  "provider": LOCAL_PROVIDER})
        payload = _run_whisper(runtime, wav_path, str(Path(work) / "result"), emit)
    try:
        transcript = parse_whisper_json(payload, timeline_offset, request.speaker)
    except WhisperParseError as exc:
        raise LocalWhisperError(str(exc)) from exc
    if not math.isfinite(duration) or duration <= 0:
        duration = transcript[-1]["end"]
    language = payload.get("result", {}).get("language") or runtime.language
    model_type = payload.get("model", {}).get("type") or Path(runtime.model).stem
    return {"status": "done", "transcript": transcript, "duration": duration,
            "fps": 0, "language": language, "model": f"whisper.cpp:{model_type}"}
