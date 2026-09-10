"""Explicit local source-timing review CLI and the actual cut-gate consumer.

Request/decision files are reference data, not evidence that a person listened.
Only invoke ``record`` for an explicit human submission after source audition.
No command edits media/transcripts/plans, runs ASR, or approves delivery.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from typing import Callable

from color.deadline import wall_budget
from cut_preview_io import digest, read_bytes
from transcript_cut_evidence import source_evidence
from transcript_cut_quality import inspect_output, timing_review_error
from transcript_timing_review_authority import ReviewCapture, ReviewInput, capture, recheck, verify_sources
from transcript_timing_review_contract import MAX_RECORD_BYTES, parse_json, submission
import transcript_timing_review_store as store

WORK_SECONDS = 120


def _guard(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise RuntimeError("source timing review exceeded its original 120-second work budget")


def _unchanged(value: ReviewCapture, request: dict, chain: list[dict], guard: Callable[[], None]) -> None:
    current_request, current_chain = store.read_current(value)
    if digest(current_request) != digest(request) or digest(current_chain) != digest(chain):
        raise RuntimeError("source timing review decisions changed during readback")
    recheck(value, guard)
    guard()


def _resolution(request: dict, chain: list[dict]) -> dict:
    last = chain[-1] if chain else None
    rows = last["submission"]["reviews"] if last else []
    resolved = [row["anomalyHash"] for row in rows if row["disposition"] != "unresolved"]
    return {"state": "resolved" if len(resolved) == len(request["anomalies"]) else "unresolved",
            "requestHash": request["requestHash"],
            "decisionHash": last["decisionHash"] if last else None,
            "resolvedAnomalyHashes": resolved,
            "unresolvedCount": len(request["anomalies"]) - len(resolved),
            "scope": "explicit-source-window-timing-review-not-cut-or-delivery-approval"}


def consume(inputs: ReviewInput, report: dict, errors: list[str]) -> tuple[dict, list[str]]:
    """Clear only matching timing findings after current source/decision verification."""
    findings = report["suspiciousWordSpans"]
    if not findings:
        return report, errors
    started = time.monotonic()
    guard = lambda: _guard(started + WORK_SECONDS)
    try:
        with wall_budget(started + WORK_SECONDS):
            value = capture(inputs, findings, guard)
            if not os.path.lexists(store.directory(value)):
                return {**report, "timingReview": {"state": "not-prepared", "elapsedMs":
                        round((time.monotonic() - started) * 1000, 3)}}, errors
            request, chain = store.read_current(value)
            verify_sources(value, guard)  # One fresh source hash pass, never a stat-only cache.
            resolution = _resolution(request, chain)
            remaining = list(errors)
            for row in request["anomalies"]:
                if row["anomalyHash"] in resolution["resolvedAnomalyHashes"]:
                    remaining.remove(timing_review_error(row["finding"]))
            _unchanged(value, request, chain, guard)
            resolution["elapsedMs"] = round((time.monotonic() - started) * 1000, 3)
            guard()
            return {**report, "timingReview": resolution}, remaining
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, IndexError) as exc:
        failure = {"state": "blocked", "error": str(exc)[:1000],
                   "elapsedMs": round((time.monotonic() - started) * 1000, 3)}
        return {**report, "timingReview": failure}, [*errors, f"source timing review blocked: {exc}"]


def _load_inputs(paths: tuple[str, str, str]) -> ReviewInput:
    plan_path, transcripts_dir, manifest_path = (os.path.abspath(item) for item in paths)
    plan = json.loads(read_bytes(Path(plan_path)).decode("utf-8"))
    manifest = json.loads(read_bytes(Path(manifest_path)).decode("utf-8"))
    errors: list[str] = []
    used = {str(cut.get("sourceId", "")) for cut in plan.get("cutTrack", [])}
    sources, _files = source_evidence(manifest, manifest_path, transcripts_dir, used, errors)
    if errors:
        raise RuntimeError("timing review cannot bind transcript authority: " + "; ".join(errors))
    return ReviewInput(plan_path, manifest_path, transcripts_dir, plan, manifest, sources)


def _submitted(value: object) -> object:
    if isinstance(value, Path):
        return parse_json(read_bytes(value, MAX_RECORD_BYTES))
    return value


def _apply_command(command: str, value: ReviewCapture, sent: object, guard: Callable[[], None]) -> bool:
    if command == "prepare":
        return store.prepare(value, guard)[1]
    if command == "record":
        return store.append(value, sent, guard)[1]
    return False


def _validate_command(command: str, value: ReviewCapture, sent: object) -> None:
    if command == "prepare":
        return
    request, _chain = store.read_current(value)
    if command == "record":
        submission(sent, request)


def execute(command: str, paths: tuple[str, str, str], submitted: object = None) -> dict:
    """Prepare/inspect or record explicit human data; no automatic decision exists."""
    if command not in {"prepare", "record", "status"}:
        raise RuntimeError("unknown source timing review command")
    started = time.monotonic()
    guard = lambda: _guard(started + WORK_SECONDS)
    with wall_budget(started + WORK_SECONDS):
        sent = _submitted(submitted)
        inputs = _load_inputs(paths)
        report, _errors, _warnings = inspect_output(inputs.plan, inputs.sources, 0.015)
        value = capture(inputs, report["suspiciousWordSpans"], guard)
        _validate_command(command, value, sent)  # Reject before large source hashing.
        verify_sources(value, guard)
        replayed = _apply_command(command, value, sent, guard)
        request, chain = store.read_current(value)
        result = {"ok": True, "command": command, "request": request,
                  "review": _resolution(request, chain), "replayed": replayed,
                  "sourceFreshness": "actual-admitted-bytes-observed-this-invocation",
                  "subjectiveListening": "not-performed-by-system", "deliveryApproved": False}
        _unchanged(value, request, chain, guard)
        result["elapsedMs"] = round((time.monotonic() - started) * 1000, 3)
        guard()
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "record", "status"))
    for name in ("plan", "transcripts_dir", "manifest"):
        parser.add_argument(name)
    parser.add_argument("submission", nargs="?")
    args = parser.parse_args()
    if (args.command == "record") != bool(args.submission):
        parser.error("only record requires an explicit human submission JSON file")
    try:
        sent = Path(os.path.abspath(args.submission)) if args.submission else None
        result = execute(args.command, (args.plan, args.transcripts_dir, args.manifest), sent)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, IndexError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:1000],
                          "recordMayHaveBeenWritten": args.command == "record",
                          "deliveryApproved": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
