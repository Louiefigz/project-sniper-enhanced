"""Bounded, unambiguous transcription-worker NDJSON completion parsing.

This validates the worker transport, not source identity, word timing, model
quality, or process cleanup. Those remain the caller's independent gates.
"""
from __future__ import annotations

import io
import json
import math
from typing import Callable

MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_COUNT_CHUNK = 64 * 1024
_PROGRESS = frozenset({
    "extracting_audio", "audio_extracted", "transcribing_chunk",
    "chunking_audio", "chunking_complete", "local_whisper_cpu_fallback",
    "local_whisper_timing_retry",
})
Guard = Callable[[], None] | None


def _guard(guard: Guard) -> None:
    """Observe an optional original caller clock without creating a deadline."""
    if guard is not None:
        guard()


def _bounded_output(stdout: str, guard: Guard) -> None:
    """Count UTF-8 bytes in bounded chunks before allocating parsed objects."""
    _guard(guard)
    if not isinstance(stdout, str) or len(stdout) > MAX_OUTPUT_BYTES:
        raise RuntimeError("transcription output must be text within 16 MiB")
    total = 0
    for offset in range(0, len(stdout), _COUNT_CHUNK):
        _guard(guard)
        try:
            total += len(stdout[offset:offset + _COUNT_CHUNK].encode("utf-8"))
        except UnicodeError as error:
            raise RuntimeError("transcription output is not valid UTF-8 text") from error
        if total > MAX_OUTPUT_BYTES:
            raise RuntimeError("transcription output exceeds 16 MiB")
    _guard(guard)


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    """Reject duplicate keys at every JSON object depth."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError("transcription output has duplicate JSON keys")
        result[key] = value
    return result


def _constant(value: str) -> object:
    """JSON's nonstandard NaN/Infinity spellings are never valid evidence."""
    raise RuntimeError(f"transcription output contains nonfinite JSON: {value}")


def _float(value: str) -> float:
    """Reject finite-looking exponential literals that overflow to infinity."""
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError("transcription output contains nonfinite JSON numbers")
    return number


def _row(line: str, guard: Guard) -> dict:
    """Parse one complete object row without truncation or malformed-line skips."""
    _guard(guard)
    try:
        row = json.loads(line, object_pairs_hook=_pairs,
                         parse_constant=_constant, parse_float=_float)
    except (ValueError, RecursionError) as error:
        raise RuntimeError("transcription output contains malformed JSON") from error
    _guard(guard)
    if not isinstance(row, dict):
        raise RuntimeError("transcription output rows must be JSON objects")
    if "error" in row:
        raise RuntimeError("transcription worker reported an error")
    status = row.get("status")
    if not isinstance(status, str) or status not in _PROGRESS | {"done"}:
        raise RuntimeError("transcription output has an unknown status")
    if status == "done" and not isinstance(row.get("transcript"), list):
        raise RuntimeError("transcription completion requires a transcript list")
    if status != "done" and "transcript" in row:
        raise RuntimeError("transcription progress cannot contain a completion")
    return row


def parse_transcription_output(stdout: str, guard: Guard = None) -> dict:
    """Require exactly one final done row after only known progress records."""
    _bounded_output(stdout, guard)
    result = None
    for raw in io.StringIO(stdout):
        _guard(guard)
        if not raw.strip():
            continue
        if result is not None:
            raise RuntimeError("transcription output has records after completion")
        row = _row(raw, guard)
        if row["status"] == "done":
            result = row
    _guard(guard)
    if result is None:
        raise RuntimeError("transcription output has no final completion")
    return result
