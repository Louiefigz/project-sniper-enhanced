#!/usr/bin/env python3
"""Prepare/status/record immutable, explicitly human-reviewed word corrections.

One <=120-second work clock applies per command, including source verification;
it is not a generation budget or a human-wait clock. No command selects a new
transcript/manifest, edits a cut, runs ASR, or grants creative/delivery approval.
The supplied v1 timing or v2 text operation is explicit; neither is a fallback.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from color.deadline import wall_budget
from cut_preview_io import read_bytes
from cross_runtime_canonical_json import canonical_compact_json
from transcript_timing_correction_authority import (
    CorrectionCapture, CorrectionInput, capture, recheck, request_for, verify_sources,
)
from transcript_timing_correction_contract import MAX_INPUT_BYTES, parse_json, proposal, submission
import transcript_timing_correction_store as store

WORK_SECONDS = 120


def _deadline(inputs: CorrectionInput, started: float) -> float:
    """Keep one per-command cap, shortened by an earlier caller expiry."""
    parent = inputs.parent_deadline
    if parent is not None and (type(parent) not in (int, float) or not math.isfinite(parent)):
        raise RuntimeError("timing correction caller deadline is malformed")
    return min(started + WORK_SECONDS, parent) if parent is not None else started + WORK_SECONDS


def _guard(deadline: float) -> None:
    """Reject expired work without renewing generation or human-wait time."""
    if time.monotonic() >= deadline:
        raise RuntimeError("timing correction original per-command work deadline exceeded")


def _submitted(value: object) -> object:
    """Read bounded supplied bytes, or preserve an already supplied object."""
    return parse_json(read_bytes(value, MAX_INPUT_BYTES)) if isinstance(value, Path) else value


def _validate(command: str, value: CorrectionCapture, sent: object) -> None:
    """Validate explicit intent before full source observation or publication."""
    if command in {"status", "record"}:
        store.validate_existing(value)
    if command == "record":
        submission(sent, request_for(value))
    elif sent is not None:
        raise RuntimeError("only record accepts an explicit human submission")


def _result(value: CorrectionCapture, command: str, replayed: bool, started: float) -> tuple[dict, dict]:
    """Return a non-selecting status together with its held artifact bytes."""
    (request, _record, revision), artifacts = store.read_held(value)
    result = {"ok": True, "command": command, "state": "committed" if revision else "prepared",
              "request": request, "revision": revision, "replayed": replayed,
              "sourceFreshness": "actual-admitted-bytes-observed-this-invocation",
              "subjectiveListening": "not-performed-by-system", "selected": False,
              "cutApproved": False, "deliveryApproved": False,
              "elapsedMs": round((time.monotonic() - started) * 1000, 3)}
    canonical_compact_json(result)
    return result, artifacts


def inspect_current(inputs: CorrectionInput, proposed: dict, guard: Callable[[], None]) -> dict:
    """Strong read with the existing owner's guard; never install or reset a timer."""
    started = time.monotonic()
    guard()
    value = capture(inputs, proposal(proposed), guard)
    store.validate_existing(value)
    value = verify_sources(value, guard)
    result, artifacts = _result(value, "status", False, started)
    recheck(value, guard)
    store.recheck_artifacts(value, artifacts)
    guard()
    return result


def _mutate(command: str, value: CorrectionCapture, sent: object, guard: Callable[[], None]) -> bool:
    """Dispatch only the two explicitly requested new-only mutations."""
    if command == "prepare":
        return store.prepare(value, guard)
    if command == "record":
        return store.record(value, sent, guard)
    return False


def execute(command: str, inputs: CorrectionInput, proposed: object, submitted: object = None) -> dict:
    """Strong current source/lineage read, or new-only prepare/record under one clock."""
    started = time.monotonic()
    deadline = _deadline(inputs, started)
    guard = lambda: _guard(deadline)
    guard()
    if command not in {"prepare", "record", "status"}:
        raise RuntimeError("unknown timing correction command")
    with wall_budget(deadline):
        proposed, sent = proposal(_submitted(proposed)), _submitted(submitted)
        if command == "status" and sent is None:
            return inspect_current(inputs, proposed, guard)
        value = capture(inputs, proposed, guard)
        _validate(command, value, sent)
        value = verify_sources(value, guard)
        replayed = _mutate(command, value, sent, guard)
        recheck(value, guard)
        result, artifacts = _result(value, command, replayed, started)
        recheck(value, guard)
        store.recheck_artifacts(value, artifacts)
        guard()
        return result


def main() -> int:
    """Expose bounded explicit commands without media work or active selection."""
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("command", choices=("prepare", "record", "status"))
    for name in ("plan", "manifest", "transcript", "proposal"):
        parser.add_argument(name)
    parser.add_argument("submission", nargs="?")
    args = parser.parse_args()
    if (args.command == "record") != bool(args.submission):
        parser.error("only record requires explicit human submission JSON")
    deadline = started + WORK_SECONDS
    inputs = CorrectionInput(Path(args.plan), Path(args.manifest), Path(args.transcript), deadline)
    try:
        sent = Path(args.submission) if args.submission else None
        result = execute(args.command, inputs, Path(args.proposal), sent)
        with wall_budget(deadline):
            print(json.dumps(result, ensure_ascii=True, allow_nan=False), flush=True)
        return 0
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, IndexError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:1000],
                          "recordMayHaveBeenWritten": args.command == "record",
                          "selected": False, "cutApproved": False, "deliveryApproved": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
