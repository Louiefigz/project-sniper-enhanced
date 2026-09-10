"""Immutable timing requests and bounded append-only explicit decision history."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Callable
from uuid import uuid4

from cut_preview_io import digest, read_bytes, real_directory, write_new
from transcript_timing_review_authority import ReviewCapture, recheck, request_for
from transcript_timing_review_contract import (
    MAX_DECISIONS, MAX_RECORD_BYTES, POLICY, closed, decision, parse_json, record_bytes, submission,
)


def directory(value: ReviewCapture) -> Path:
    """Derive one fixed authority namespace; callers cannot supply a store path."""
    return Path(value.binding["manifestPath"]).parent / ".sniper-timing-reviews" / digest(value.binding)


def _mkdir(path: Path) -> None:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    real_directory(path)


def _json(path: Path) -> dict:
    raw = read_bytes(path, MAX_RECORD_BYTES)
    value = parse_json(raw)
    if type(value) is not dict:
        raise RuntimeError("timing review record is not an object")
    if record_bytes(value) != raw:
        raise RuntimeError("timing review record bytes are not its canonical representation")
    return value


def _new_plan(path: Path, raw: bytes) -> None:
    real_directory(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _head(request: dict, chain: list[dict]) -> dict:
    return {"schemaVersion": 1, "kind": "source-timing-review-head",
            "requestHash": request["requestHash"], "sequence": len(chain),
            "decisionHash": chain[-1]["decisionHash"] if chain else None}


def _require_head(root: Path, expected: dict) -> None:
    observed = closed(_json(root / "head.json"), set(expected), "head")
    if digest(observed) != digest(expected):
        raise RuntimeError("timing review head differs from the exact retained decision count/tip")


def _advance_head(root: Path, previous: dict, current: dict, guard: Callable[[], None]) -> None:
    """Advance only selection metadata; a partial append stays blocked, never rolled back."""
    _require_head(root, previous)
    temporary = root / f".head-{uuid4()}.tmp"
    write_new(temporary, current)
    _require_head(root, previous)
    guard()
    os.replace(temporary, root / "head.json")
    _sync_directory(root)


def prepare(value: ReviewCapture, guard: Callable[[], None]) -> tuple[dict, bool]:
    """Create a new private request, or revalidate its exact existing identity."""
    root = directory(value)
    if os.path.lexists(root):
        request, _chain = read_current(value)
        return request, True
    _mkdir(root.parent)
    root.mkdir(mode=0o700)  # A racing or partial preparation is never overwritten.
    _mkdir(root / "decisions")
    request = request_for(value, value.plan_bytes)
    record_bytes(request)
    recheck(value, guard)
    _new_plan(root / "original-plan.json", value.plan_bytes)
    write_new(root / "request.json", request)
    write_new(root / "head.json", _head(request, []))
    _sync_directory(root)
    _sync_directory(root.parent)
    return read_current(value)[0], False


def _chain(root: Path, request: dict) -> list[dict]:
    folder = root / "decisions"
    real_directory(folder)
    names = sorted(os.listdir(folder))
    if len(names) > MAX_DECISIONS or names != [f"{index:04d}.json" for index in range(1, len(names) + 1)]:
        raise RuntimeError("timing review decision chain is oversized, partial, or forked")
    records, seen = [], set()
    previous = None
    for index, name in enumerate(names, 1):
        row = decision(_json(folder / name), request)
        identifier = row["submission"]["idempotencyKey"]
        if row["sequence"] != index or row["previousDecisionHash"] != previous \
                or identifier in seen or (records and row["recordedAt"] < records[-1]["recordedAt"]):
            raise RuntimeError("timing review decision chain lost exact ancestry/identity")
        seen.add(identifier)
        records.append(row)
        previous = row["decisionHash"]
    return records


def read_current(value: ReviewCapture) -> tuple[dict, list[dict]]:
    """Reconstruct all authority from current parents, never file presence alone."""
    root = directory(value)
    real_directory(root)
    if set(os.listdir(root)) != {"original-plan.json", "request.json", "decisions", "head.json"}:
        raise RuntimeError("timing review request directory is incomplete or has unknown files")
    original = read_bytes(root / "original-plan.json")
    expected = request_for(value, original)
    observed = _json(root / "request.json")
    if digest(observed) != digest(expected):
        raise RuntimeError("timing review request source/cut/anomaly/window binding is stale")
    chain = _chain(root, expected)
    _require_head(root, _head(expected, chain))
    return expected, chain


def append(value: ReviewCapture, submitted: object, guard: Callable[[], None]) -> tuple[dict, bool]:
    """Record only a supplied explicit decision; exact replay never creates a row."""
    request, chain = read_current(value)
    sent = submission(submitted, request)
    prior = next((row for row in chain if row["submission"]["idempotencyKey"] == sent["idempotencyKey"]), None)
    if prior is not None:
        if digest(prior["submission"]) != digest(sent):
            raise RuntimeError("timing review idempotency key names a different decision")
        return prior, True
    previous = chain[-1]["decisionHash"] if chain else None
    if sent["expectedPreviousDecisionHash"] != previous or len(chain) >= MAX_DECISIONS:
        raise RuntimeError("timing review expected previous decision is stale or chain is full")
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if chain and now < chain[-1]["recordedAt"]:
        raise RuntimeError("timing review clock moved backward")
    body = {"schemaVersion": 1, "kind": "source-timing-review-decision", "policy": POLICY,
            "actor": "explicit-local-operator-attestation", "requestHash": request["requestHash"],
            "sequence": len(chain) + 1, "previousDecisionHash": previous,
            "recordedAt": now, "submission": sent}
    row = decision({**body, "decisionHash": digest(body)}, request)
    record_bytes(row)
    root = directory(value)
    recheck(value, guard)
    _require_head(root, _head(request, chain))
    guard()
    write_new(root / "decisions" / f"{row['sequence']:04d}.json", row)
    _sync_directory(root / "decisions")
    guard()
    _advance_head(root, _head(request, chain), _head(request, [*chain, row]), guard)
    return row, False
