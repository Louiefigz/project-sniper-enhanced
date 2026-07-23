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
import functools
import json
import os
import time
from typing import Callable, Iterator, Protocol, TypeVar

JOURNAL_NAME = "stage_timings.jsonl"
_EVENTS = ("start", "end")
_T = TypeVar("_T")


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
    row = json.dumps({"stage": stage, "event": event,
                      "ts": time.time(), "mono": time.monotonic()},
                     ensure_ascii=False)
    try:
        fd = os.open(journal_path(producer_dir),
                     os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (row + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        return False
    return True


@contextlib.contextmanager
def stage_span(producer_dir: str, stage: str) -> Iterator[None]:
    """START/END rows around a block of work.

    END is written even when the block raises — the failing stage still ended,
    and the exception itself stays the loud signal (the journal never swallows
    or re-wraps it).
    """
    journal_event(producer_dir, stage, "start")
    try:
        yield
    finally:
        journal_event(producer_dir, stage, "end")


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
