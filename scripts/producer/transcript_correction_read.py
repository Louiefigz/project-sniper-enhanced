"""Strong timing-correction consumption at the actual transcript cut gate.

A renewed sourceMediaAuthority digest alone is not a human correction record.
Use the immutable correction transaction against its exact original parents;
never accept copied/staged corrected files as original correction authority.
The caller still owes ordinary cut validation, review and preview acceptance.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import math
import os
from pathlib import Path
import signal
import threading
import time
from typing import Iterator

from color.deadline import wall_budget
from cut_preview_io import MAX_JSON, digest, read_bytes, real_directory
from transcript_timing_correction import inspect_current
from transcript_timing_correction_authority import CorrectionInput
from transcript_timing_correction_contract import identifier, proposal
from transcript_timing_review_contract import closed, hash_value, parse_json

WORK_SECONDS = 120
MANIFEST_PREFIX = "asset_manifest.timing-"
AUTHORITY_KEYS = {"timingCorrectionAuthority", "sourceWordCorrectionAuthority"}


def _guard(deadline: float) -> None:
    """Borrow an existing work clock; a transcript read cannot extend it."""
    if time.monotonic() >= deadline:
        raise RuntimeError("corrected transcript read exceeded its original work budget")


def _authority(payload: dict) -> dict:
    """Require one explicit correction kind; never merge two authority markers."""
    keys = AUTHORITY_KEYS.intersection(payload)
    if len(keys) != 1:
        raise RuntimeError("corrected transcript requires exactly one correction authority")
    value = payload[next(iter(keys))]
    if type(value) is not dict:
        raise RuntimeError("corrected transcript correction authority is malformed")
    return value


def _expired(_signal: int, _frame: object) -> None:
    """Interrupt blocking reads, including when the caller's alarm is longer."""
    raise RuntimeError("corrected transcript read exceeded its original work budget")


@contextmanager
def _work_budget() -> Iterator[float]:
    """Shorten any parent alarm temporarily, restoring its absolute expiry only."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("corrected transcript read requires a main-thread work deadline")
    started = time.monotonic()
    remaining, interval = signal.getitimer(signal.ITIMER_REAL)
    if interval:
        raise RuntimeError("corrected transcript read cannot borrow a repeating alarm")
    deadline = started + min(WORK_SECONDS, remaining) if remaining else started + WORK_SECONDS
    if not remaining:
        with wall_budget(deadline):
            yield deadline
        return
    parent_expiry, previous = started + remaining, signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _expired)
    try:
        _guard(deadline)
        signal.setitimer(signal.ITIMER_REAL, deadline - time.monotonic())
        yield deadline
        _guard(deadline)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        left = parent_expiry - time.monotonic()
        if left > 0:
            signal.setitimer(signal.ITIMER_REAL, left)
        else:
            raise RuntimeError("corrected transcript caller work deadline expired")


def _manifest_requires(source: dict, path: Path, manifest_path: str | None) -> bool:
    """A published timing-manifest cannot disguise the selected revision as ASR."""
    if manifest_path is None or not Path(manifest_path).name.startswith(MANIFEST_PREFIX):
        return False
    manifest = Path(os.path.abspath(manifest_path))
    if manifest.suffix != ".json":
        raise RuntimeError("corrected manifest filename is malformed")
    request_id = identifier(manifest.stem.removeprefix(MANIFEST_PREFIX))
    root = manifest.parent / ".sniper-timing-corrections" / request_id
    request = parse_json(read_bytes(root / "request.json", MAX_JSON))
    proposed = proposal(request.get("proposal") if type(request) is dict else None)
    if proposed["requestId"] != request_id:
        raise RuntimeError("corrected manifest request identity changed")
    current = parse_json(read_bytes(manifest, MAX_JSON))
    rows = current.get("sources") if type(current) is dict else None
    if type(rows) is not list:
        raise RuntimeError("corrected manifest lost its source list")
    selected = [row for row in rows if type(row) is dict and row.get("id") == proposed["sourceId"]]
    expected = (root / "corrected-transcript.json").relative_to(manifest.parent).as_posix()
    if len(selected) != 1 or selected[0].get("transcriptPath") != expected:
        raise RuntimeError("corrected manifest lost its committed transcript pointer")
    if source.get("id") != proposed["sourceId"]:
        return False
    if path != root / "corrected-transcript.json":
        raise RuntimeError("corrected manifest lost its committed transcript pointer")
    return True


def _parents(request: dict) -> CorrectionInput:
    """Resolve bounded request data only; the strong reader rederives its authority."""
    binding = request.get("binding")
    if type(binding) is not dict:
        raise RuntimeError("corrected transcript request binding is malformed")
    parents = closed(binding.get("parents"), {"plan", "manifest", "transcript"}, "correction parent paths")
    paths = []
    for name in ("plan", "manifest", "transcript"):
        row = closed(parents[name], {"path", "sha256"}, "correction parent")
        hash_value(row["sha256"], "correction parent hash")
        if type(row["path"]) is not str or not Path(row["path"]).is_absolute():
            raise RuntimeError("corrected transcript parent path is not absolute")
        paths.append(Path(row["path"]))
    return CorrectionInput(*paths)


def _current_source(source: dict, request: dict) -> None:
    """Reject transplantation into another source identity or different duration."""
    held = request["binding"].get("source")
    if type(held) is not dict:
        raise RuntimeError("corrected transcript source binding is malformed")
    fields = {"id": "sourceId", "path": "path", "sourceSha256": "sha256", "sourceSizeBytes": "sizeBytes"}
    if any(source.get(key) != held.get(mapped) for key, mapped in fields.items()):
        raise RuntimeError("corrected transcript current source differs from reviewed source")
    duration = source.get("duration")
    if type(duration) not in (int, float) or not math.isfinite(duration) \
            or duration != held.get("duration"):
        raise RuntimeError("corrected transcript current duration differs from reviewed source")


def _capture(payload: dict, source: dict, path: Path) -> tuple[CorrectionInput, dict, bytes]:
    """Read exact canonical transaction location; linked or transplanted copies fail."""
    real_directory(path.parent)
    if path.name != "corrected-transcript.json" or path.parent.parent.name != ".sniper-timing-corrections":
        raise RuntimeError("corrected transcript must use its committed original path")
    identifier(path.parent.name)
    raw = read_bytes(path, MAX_JSON)
    if digest(parse_json(raw)) != digest(payload):
        raise RuntimeError("corrected transcript payload changed during loading")
    request = parse_json(read_bytes(path.parent / "request.json", MAX_JSON))
    if type(request) is not dict:
        raise RuntimeError("corrected transcript request is not an object")
    proposed = proposal(request.get("proposal"))
    inputs = _parents(request)
    if inputs.manifest_path.parent != path.parent.parent.parent \
            or proposed["requestId"] != path.parent.name:
        raise RuntimeError("corrected transcript escaped its original admitted source directory")
    _current_source(source, request)
    return inputs, proposed, raw


def _consume(payload: dict, source: dict, path: Path, deadline: float) -> None:
    """Require current explicit decision and exact reconstructed timing-only bytes."""
    inputs, proposed, raw = _capture(payload, source, path)
    guard = lambda: _guard(deadline)
    verified = inspect_current(inputs, proposed, guard)
    revision, authority = verified.get("revision"), _authority(payload)
    if verified.get("ok") is not True or verified.get("state") != "committed" \
            or type(revision) is not dict or type(authority) is not dict:
        raise RuntimeError("corrected transcript has no freshly verified committed review")
    if revision["path"] != str(path) or revision["sha256"] != hashlib.sha256(raw).hexdigest() \
            or revision["recordHash"] != authority.get("recordHash") \
            or verified["request"]["requestHash"] != authority.get("requestHash") \
            or revision["sourceBindingDigest"] != payload.get("sourceMediaAuthority", {}).get("bindingDigest"):
        raise RuntimeError("corrected transcript differs from its committed review authority")
    if read_bytes(path, MAX_JSON) != raw:
        raise RuntimeError("corrected transcript changed during strong readback")
    guard()


def require_correction(payload: object, source: dict, transcript_path: str,
                       manifest_path: str | None = None) -> None:
    """Verify optional correction lineage without altering ordinary ASR transcripts."""
    path = Path(os.path.abspath(transcript_path))
    marked = type(payload) is dict and bool(AUTHORITY_KEYS.intersection(payload))
    reserved = ".sniper-timing-corrections" in path.parts
    named = manifest_path is not None and Path(manifest_path).name.startswith(MANIFEST_PREFIX)
    if not marked and not reserved and not named:
        return
    with _work_budget() as deadline:
        required = _manifest_requires(source, path, manifest_path) or reserved
        if not marked and required:
            raise RuntimeError("corrected transcript cannot omit its correction authority")
        if not marked:
            return
        _authority(payload)
        _guard(deadline)
        _consume(payload, source, path, deadline)


def correction_error(payload: object, source: dict, transcript_path: str,
                     manifest_path: str | None = None) -> str | None:
    """Return a cut-gate finding instead of accepting a consistent but unreviewed hash."""
    try:
        require_correction(payload, source, transcript_path, manifest_path)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        return f"timing correction authority blocked: {exc}"
    return None
