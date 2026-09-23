#!/usr/bin/env python3
"""Fail-closed local transcription through whisper.cpp.

This module never downloads a model and never falls back to a network provider.
It converts media to 16 kHz PCM, runs ``whisper-cli`` with experimental
word-level timestamps, and shapes the result into the Deepgram-compatible
utterance/word contract used by SEGMENTER, CLIPPER, and PRODUCER.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional
from local_asr_deadline import (LocalAsrDeadline, LocalWhisperError, configured_timeout,
                                current_local_asr_deadline, use_local_asr_deadline)
from local_whisper_io import hash_provenance, read_whisper_json, run_local_tool
from local_whisper_parser import PARSER_POLICY
from transcript_timing_quality import timing_quality_report
from local_whisper_speech_edges import tighten_speech_edges
from asr_policy import (PROVIDER_ENV, EXECUTION_MODE_ENV, DEEPGRAM_PROVIDER,
                        LOCAL_PROVIDER, VALID_PROVIDERS, AsrPolicyError,
                        transcription_provider as _provider)

from local_whisper_timing import (
    TimingContext,
    WhisperTimingError,
    accept_or_retry,
)


Emit = Optional[Callable[[dict], None]]


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


def _sha256(path: str) -> str:
    """Retain the shared guarded full-byte provenance reader."""
    return hash_provenance(path)


def _runtime_provenance(runtime: WhisperRuntime) -> dict:
    settings = {
        "language": runtime.language,
        "threads": runtime.threads,
        "timeoutSeconds": runtime.timeout_s,
        "forceCpu": runtime.force_cpu,
    }
    encoded = json.dumps(
        settings, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()
    return {
        "schemaVersion": 1,
        "provider": LOCAL_PROVIDER,
        "runtimeSha256": _sha256(runtime.binary),
        "modelSha256": _sha256(runtime.model),
        "settingsSha256": hashlib.sha256(encoded).hexdigest(),
    }


def transcription_provider(environ: Optional[Mapping[str, str]] = None) -> str:
    """Reexport the shared local-only default without changing local error APIs."""
    try:
        return _provider(environ)
    except AsrPolicyError as exc:
        raise LocalWhisperError(str(exc)) from exc


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
    timeout_s = configured_timeout(env)
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
    proc = run_local_tool(cmd)
    if proc.returncode != 0:
        raise LocalWhisperError(proc.stderr.strip() or "ffprobe failed")
    data = json.loads(proc.stdout)
    current_local_asr_deadline().guard()
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
    proc = run_local_tool(cmd)
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
    current_local_asr_deadline().guard()
    output_path = Path(prefix + ".json")
    output_path.unlink(missing_ok=True)
    proc = run_local_tool(_whisper_command(runtime, wav_path, prefix, cpu))
    tail = (proc.stderr or proc.stdout or "").strip()[-1500:]
    if proc.returncode != 0 or not output_path.is_file():
        return None, f"exit={proc.returncode}; {tail or 'no JSON output'}"
    try:
        return read_whisper_json(output_path), ""
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"invalid whisper JSON: {exc}"


def _run_whisper(
    runtime: WhisperRuntime,
    wav_path: str,
    prefix: str,
    emit: Emit,
) -> tuple[dict, bool]:
    attempts = [True] if runtime.force_cpu else [False, True]
    errors: list[str] = []
    for cpu in attempts:
        payload, error = _attempt_whisper(runtime, wav_path, prefix, cpu)
        if payload is not None:
            return payload, cpu
        errors.append(("cpu" if cpu else "gpu") + ": " + error)
        if not cpu and emit:
            emit({"status": "local_whisper_cpu_fallback", "reason": error[-300:]})
    raise LocalWhisperError("whisper-cli failed; " + " | ".join(errors))


def _transcribe_media(request: LocalTranscribeRequest, emit: Emit) -> dict:
    """Run unchanged local media/timing semantics within the held aggregate clock."""
    path = str(Path(request.path).expanduser().resolve())
    if not Path(path).is_file():
        raise LocalWhisperError(f"media not found: {path}")
    probed_offset, probed_duration = _probe_audio(path)
    timeline_offset = probed_offset if request.timeline_offset is None else request.timeline_offset
    duration = probed_duration if request.duration is None else request.duration
    runtime = resolve_runtime()
    provenance = _runtime_provenance(runtime)
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
        prefix = str(Path(work) / "result")
        payload, cpu = _run_whisper(runtime, wav_path, prefix, emit)
        try:
            payload, transcript, cpu, quality = accept_or_retry(
                payload, cpu, TimingContext(
                    timeline_offset, request.speaker, emit),
                lambda: _attempt_whisper(
                    runtime, wav_path, prefix, True))
        except WhisperTimingError as exc:
            raise LocalWhisperError(str(exc)) from exc
        # whisper's token times touch end to end, so a pause is invisible until the
        # real speech edges are measured. Keeping the unrefined transcript is the
        # fail-closed answer: it is what every earlier release shipped.
        unrefined = copy.deepcopy(transcript)
        transcript, edges = tighten_speech_edges(transcript, wav_path, timeline_offset)
        if edges.get("applied"):
            recheck = timing_quality_report({"transcript": transcript})
            if recheck["status"] == "pass":
                quality = recheck
            else:
                transcript = unrefined
                edges = {**edges, "applied": False,
                         "reason": "refined timing failed the quality check: "
                                   + ",".join(v["code"] for v in recheck["violations"])}
    if _runtime_provenance(runtime) != provenance:
        raise LocalWhisperError("whisper runtime or model changed during transcription")
    return _completed_result(runtime, (payload, transcript, cpu, quality),
                             {**provenance, "speechEdges": edges}, duration)


def _completed_result(runtime: WhisperRuntime, transcription: tuple[dict, list, bool, dict],
                      provenance: dict, duration: float) -> dict:
    """Build the existing result only after complete provenance and timing checks."""
    payload, transcript, cpu, quality = transcription
    if not math.isfinite(duration) or duration <= 0:
        duration = transcript[-1]["end"]
    language = payload.get("result", {}).get("language") or runtime.language
    model_type = payload.get("model", {}).get("type") or Path(runtime.model).stem
    payload_bytes = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()
    current_local_asr_deadline().guard()
    return {
        "status": "done", "transcript": transcript, "duration": duration,
        "fps": 0, "language": language, "model": f"whisper.cpp:{model_type}",
        "provenance": {
            **provenance,
            "executionPath": "cpu" if cpu else "gpu",
            "timingQualityPolicy": quality["policy"],
            "parserPolicy": PARSER_POLICY,
            "resultSha256": hashlib.sha256(payload_bytes).hexdigest(),
        },
    }


def transcribe_media(request: LocalTranscribeRequest, emit: Emit = None,
                     deadline: LocalAsrDeadline | None = None) -> dict:
    """Transcribe locally under one deadline shared by extraction and both attempts."""
    if deadline is not None and type(deadline) is not LocalAsrDeadline:
        raise LocalWhisperError("local ASR deadline must be a LocalAsrDeadline")
    clock = LocalAsrDeadline.start(parent_expires_at=deadline.expires_at if deadline else None)
    with use_local_asr_deadline(clock):
        result = _transcribe_media(request, emit)
        clock.guard()
        return result
