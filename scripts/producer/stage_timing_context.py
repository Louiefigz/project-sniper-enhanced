"""Process-local timing lineage shared with the TypeScript controller."""
from __future__ import annotations

import contextvars
import os
import uuid

PARENT_SPAN: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sniper_timing_parent_span", default=None)
_WRITER_ID = str(uuid.uuid4())
_TEXT_KEYS = ("provider", "model", "effort", "phase", "cache")
_NUMBER_KEYS = ("round", "packetBytes", "evidenceImages", "exitCode")


def timing_context() -> dict:
    """Resolve explicit child lineage; label standalone execution honestly."""
    attempt = os.environ.get("SNIPER_TIMING_ATTEMPT_NO", "1")
    number = int(attempt) if attempt.isdecimal() and len(attempt) <= 8 else 1
    fields = {
        "schemaVersion": 2,
        "runId": os.environ.get("SNIPER_TIMING_RUN_ID") or f"standalone:{_WRITER_ID}",
        "attemptId": os.environ.get("SNIPER_TIMING_ATTEMPT_ID") or _WRITER_ID,
        "attemptNo": max(1, number),
        "writerId": f"{_WRITER_ID}:{os.getpid()}",
        "writerPid": os.getpid(),
        "clock": "process-monotonic",
    }
    parent = PARENT_SPAN.get() or os.environ.get("SNIPER_TIMING_PARENT_SPAN_ID")
    if parent:
        fields["parentSpanId"] = parent
    return fields


def timing_metadata(value: dict | None) -> dict:
    """Whitelist bounded non-content fields; reject arbitrary diagnostic payloads."""
    source = value or {}
    result = {key: source[key] for key in _TEXT_KEYS
              if isinstance(source.get(key), str) and len(source[key]) <= 128}
    for key in _NUMBER_KEYS:
        item = source.get(key)
        if (isinstance(item, (int, float)) and not isinstance(item, bool)
                and abs(item) <= 2**53 - 1):
            result[key] = item
    return result


def timing_environment() -> dict[str, str]:
    """Forward the current parent span to nested Python subprocesses explicitly."""
    context = timing_context()
    return {**os.environ,
            "SNIPER_TIMING_RUN_ID": context["runId"],
            "SNIPER_TIMING_ATTEMPT_ID": context["attemptId"],
            "SNIPER_TIMING_ATTEMPT_NO": str(context["attemptNo"]),
            "SNIPER_TIMING_PARENT_SPAN_ID": context.get("parentSpanId", "")}
