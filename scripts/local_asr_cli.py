"""Strict local-ASR CLI controls and guarded NDJSON publication.

The expiry is a same-host monotonic handoff, not an elapsed or wall timestamp.
Only an explicit parent-owned worker flag enables the shared process group.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import json
import math
from typing import Iterator

from local_asr_deadline import LocalAsrDeadline, LocalWhisperError, use_local_asr_deadline
from local_asr_worker import use_local_asr_worker_group


def _expiry(raw: str) -> float:
    """Bound numeric parsing and reject nonfinite/nonpositive clock values."""
    try:
        value = float(raw) if len(raw) <= 64 and raw.isascii() else math.nan
    except ValueError as exc:
        raise argparse.ArgumentTypeError("local ASR expiry must be a finite positive monotonic time") from exc
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("local ASR expiry must be a finite positive monotonic time")
    return value


def add_local_asr_arguments(parser: argparse.ArgumentParser) -> None:
    """Register exact private controls; callers must disable option abbreviation."""
    parser.add_argument("--local-asr-expires-at", type=_expiry, action="append", default=None,
                        help="Parent's absolute same-host monotonic work expiry")
    parser.add_argument("--local-asr-owned-worker", action="append_const", const=True, default=None,
                        help="Require this process to own its session/process group")


def parse_transcription_arguments(arguments: list[str]) -> argparse.Namespace:
    """Parse the post-provider argv fully before any source observation."""
    parser = argparse.ArgumentParser(description="Transcribe one local media path", allow_abbrev=False)
    parser.add_argument("media_path")
    add_local_asr_arguments(parser)
    return parser.parse_args(arguments)


def reject_local_controls(options: argparse.Namespace) -> None:
    """Private local ownership controls cannot alter an explicitly paid path."""
    if options.local_asr_expires_at is not None or options.local_asr_owned_worker:
        raise LocalWhisperError("local ASR controls require the local-whisper provider")


def _single_control(value: list | None, name: str) -> object:
    """Duplicated private controls are invalid, not last-argument-wins authority."""
    if value is None:
        return None
    if len(value) != 1:
        raise LocalWhisperError(f"{name} may only be supplied once")
    return value[0]


@contextmanager
def local_cli_context(options: argparse.Namespace) -> Iterator[LocalAsrDeadline]:
    """Start before source reads and enter shared ownership only when requested."""
    expires = _single_control(options.local_asr_expires_at, "--local-asr-expires-at")
    owned = _single_control(options.local_asr_owned_worker, "--local-asr-owned-worker")
    deadline = LocalAsrDeadline.start(parent_expires_at=expires)
    group = use_local_asr_worker_group() if owned else nullcontext()
    with group, use_local_asr_deadline(deadline) as held:
        yield held


def emit_local_result(result: dict, deadline: LocalAsrDeadline) -> None:
    """Charge serialization before emitting a final success line."""
    deadline.guard()
    serialized = json.dumps(result, allow_nan=False)
    deadline.guard()
    print(serialized, flush=True)
