"""Content-based media classification for transcription inputs."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


class TranscribeInputError(RuntimeError):
    """The supplied file cannot provide a supported transcription stream."""


@dataclass(frozen=True)
class TranscribeInput:
    """Stream facts needed by the transcription worker."""

    is_video: bool
    is_audio: bool


def probe_transcribe_input(path: str) -> TranscribeInput:
    """Classify media by ffprobe streams, independent of its filename suffix."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "stream=codec_type",
                "-of", "json", path,
            ],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TranscribeInputError(
            f"could not inspect transcription input: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[-500:]
        raise TranscribeInputError(
            f"unsupported or unreadable transcription input: {detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise TranscribeInputError(
            "transcription input probe returned malformed JSON") from exc
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list):
        raise TranscribeInputError(
            "transcription input probe exposed no stream inventory")
    kinds = {
        row.get("codec_type") for row in streams if isinstance(row, dict)
    }
    if "audio" not in kinds:
        raise TranscribeInputError(
            "transcription input has no audio stream")
    return TranscribeInput(is_video="video" in kinds, is_audio=True)
