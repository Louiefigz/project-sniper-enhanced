#!/usr/bin/env python3
"""stage_timing — append-only stage-timing journal (NDJSON) for wall-clock attribution.

The 2026-07 latency sweep found 57 of 102 real-run minutes UNATTRIBUTED because
no stage timings existed anywhere (PLAN_TIME_GEOMETRY_CONTRACT v3, build slot 0).
This journal is the fix: every long pipeline stage appends START/END rows to
``<dir>/stage_timings.jsonl`` so dark time can be attributed after the fact.

Row shape (one JSON object per line)::

    {"stage": str, "event": "start"|"end", "ts": <epoch float>, "mono": <monotonic float>}

``ts`` orders rows across processes; ``mono`` measures intra-process durations
immune to wall-clock steps. The TS controller (src/lib/server/stage-timing.ts)
appends the same shape to the same file.

Version-2 spans add run/attempt/writer/span/parent identity and optional
task/claim/host-turn lineage (stage_timing_context.py). ``record_handoff`` appends
point events for the task handoff vocabulary (dependencies satisfied → ready →
claim requested → host accepted → execution started → artifact published →
consumer accepted → terminal settlement). Manual markers from separate command
invocations use the same linked shape (stage_timing_markers.py). All of it is
diagnostics: authoritative task and claim transitions never read this journal.

Doctrine: the journal is pure TELEMETRY and must never fail the pipeline —
append errors return False instead of raising (the same warn-and-continue
doctrine as preview_proxy: a deliverable must not fail because observability
could not write). The file is opened O_APPEND|O_CREAT (mode 0600) and never
truncated; each row is one small single ``write()``, so concurrent appenders
(render.py, assemble.py, the detached TS worker) cannot interleave partial
lines on POSIX.
"""
from __future__ import annotations

import contextlib
import contextvars
import functools
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Iterator, Protocol, TypeVar

from stage_timing_context import PARENT_SPAN, handoff_problem, timing_context, timing_metadata

JOURNAL_NAME = "stage_timings.jsonl"
JOURNAL_UNWRITABLE = "journal-unwritable"  # the one handoff refusal that is not about content
_EVENTS = ("start", "end")
_T = TypeVar("_T")
# The journal directory of the innermost open span, so nested helpers can join it.
_JOURNAL_DIR: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sniper_timing_journal_dir", default=None)


@dataclass(frozen=True)
class HandoffEvent:
    """One observed task handoff; task/claim/host-turn lineage comes from the context."""

    stage: str
    phase: str
    artifact_sha256: str | None = None
    consumer_id: str | None = None  # consumer-accepted: which of several consumers accepted


class _HasOutDir(Protocol):
    """The first argument of a decorated renderer stage (render.py RenderCtx)."""

    out_dir: str


def journal_path(producer_dir: str) -> str:
    """Absolute path of the timing journal inside ``producer_dir``."""
    return os.path.join(producer_dir, JOURNAL_NAME)


def journal_event(producer_dir: str, stage: str, event: str) -> bool:
    """Append one timing row; best-effort telemetry.

    Args:
        producer_dir: Directory owning ``stage_timings.jsonl``.
        stage: Stage name (e.g. ``"cut_speed"``, ``"planning_round"``).
        event: ``"start"`` or ``"end"``.

    Returns:
        True when the row was appended; False when the filesystem refused
        (never raises OSError — a broken journal must not fail a render).

    Raises:
        ValueError: On an unknown ``event`` (programmer error, loud).
    """
    if event not in _EVENTS:
        raise ValueError(f"event must be one of {_EVENTS}, got {event!r}")
    return append_row(producer_dir, {"stage": stage, "event": event,
                                     "ts": time.time(), "mono": time.monotonic()})


def append_row(producer_dir: str, fields: dict) -> bool:
    """Append one bounded telemetry record without changing pipeline outcomes."""
    try:
        row = json.dumps(fields, ensure_ascii=False)
        fd = os.open(journal_path(producer_dir),
                     os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (row + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except (OSError, UnicodeError, ValueError, TypeError):
        return False
    return True


@contextlib.contextmanager
def stage_span(producer_dir: str, stage: str,
               metadata: dict | None = None) -> Iterator[None]:
    """Versioned START/END rows around a block; execution success is not QC approval.

    END is written even when the block raises — the failing stage still ended,
    and the exception itself stays the loud signal (the journal never swallows
    or re-wraps it).
    """
    began = time.monotonic()
    span_id = str(uuid.uuid4())
    fields = {**timing_context(), "stage": stage, "spanId": span_id,
              "metadata": timing_metadata(metadata)}
    append_row(producer_dir, {**fields, "event": "start",
                              "ts": time.time(), "mono": began})
    token = PARENT_SPAN.set(span_id)
    directory = _JOURNAL_DIR.set(producer_dir)
    status = "completed"
    try:
        yield
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    except SystemExit as exc:
        status = "completed" if exc.code is None or exc.code == 0 else "failed"
        raise
    except BaseException:
        status = "failed"
        raise
    finally:
        ended = time.monotonic()
        _JOURNAL_DIR.reset(directory)
        PARENT_SPAN.reset(token)
        append_row(producer_dir, {**fields, "event": "end", "status": status,
                                  "ts": time.time(), "mono": ended,
                                  "elapsedMs": (ended - began) * 1000})


def span_for_base(base_path: str, stage: str) -> Iterator[None]:
    """:func:`stage_span` anchored at the directory that owns ``base_path``.

    The assemble path's journal anchor: the producer-level directory holding
    the base render.
    """
    return stage_span(os.path.dirname(os.path.abspath(base_path)), stage)


def timed_stage(stage: str) -> Callable[[Callable[..., _T]], Callable[..., _T]]:
    """Decorator journaling a renderer stage function's wall time.

    The decorated function's FIRST positional argument must carry the journal
    anchor as ``.out_dir`` (render.py's RenderCtx) — 1-line wiring per stage.
    """
    def wrap(fn: Callable[..., _T]) -> Callable[..., _T]:
        @functools.wraps(fn)
        def inner(ctx: _HasOutDir, *args: object, **kwargs: object) -> _T:
            with stage_span(ctx.out_dir, stage):
                return fn(ctx, *args, **kwargs)
        return inner
    return wrap


def child_span(stage: str, metadata: dict | None = None) -> contextlib.AbstractContextManager:
    """A nested span in the enclosing span's journal; outside any span nothing is written.

    Shared helpers (native admission) run under many owners; only an owner that
    already journals its work (the export pipeline) receives their child spans.
    """
    directory = _JOURNAL_DIR.get()
    return stage_span(directory, stage, metadata) if directory else contextlib.nullcontext()


def _point_row(stage: str, kind: str, lineage: dict | None) -> dict:
    """A point event under the current lineage, or an explicit recorded one (manual markers)."""
    return {**(lineage or timing_context()), "event": kind, "stage": stage,
            "eventId": str(uuid.uuid4()), "ts": time.time(), "mono": time.monotonic()}


def _label_problem(stage: object) -> str | None:
    """A handoff is labelled like a stage: a 1-128 character string."""
    return None if isinstance(stage, str) and 1 <= len(stage) <= 128 else "invalid-stage-label"


def record_handoff(producer_dir: str, event: HandoffEvent, lineage: dict | None = None) -> dict:
    """Append one handoff event under the current lineage (see ``task_scope``).

    Timing never fails the work it records, so this never raises for event content.

    Returns:
        ``{"recorded": True, "row": row}`` when appended. Otherwise ``{"recorded": False,
        "reason": ...}``: an unknown phase or label, a missing task, claim epoch or artifact
        hash (nothing is written), or ``journal-unwritable`` when the filesystem refused.
    """
    row = {**_point_row(event.stage, "handoff", lineage), "handoffPhase": event.phase}
    optional = {"artifactSha256": event.artifact_sha256, "consumerId": event.consumer_id}
    row.update({key: value for key, value in optional.items() if value is not None})
    problem = _label_problem(event.stage) or handoff_problem(row)
    if problem:
        return {"recorded": False, "reason": problem}
    if not append_row(producer_dir, row):
        return {"recorded": False, "reason": JOURNAL_UNWRITABLE}
    return {"recorded": True, "row": row}


def main() -> None:
    """Mark operator/agent work in the existing journal; never imply quality approval."""
    from stage_timing_markers import main as markers
    markers()


if __name__ == '__main__':
    main()
