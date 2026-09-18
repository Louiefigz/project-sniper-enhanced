"""Deterministic least-disruptive selection for proved repair candidates."""
from __future__ import annotations

from edit.picture_lock_common import PictureLockError, content_hash, require_hash

_METHOD_ORDER = {
    "audio-lj-overlap": 0,
    "extend-and-reclaim-silence": 1,
}


def _range_cost(value: object, label: str) -> int:
    if not isinstance(value, list):
        raise PictureLockError(f"{label} must be an array")
    total = 0
    for index, row in enumerate(value):
        if not isinstance(row, dict) or set(row) != {
                "startFrame", "endFrameExclusive"}:
            raise PictureLockError(f"{label}[{index}] is malformed")
        start, end = row["startFrame"], row["endFrameExclusive"]
        if type(start) is not int or type(end) is not int \
                or start < 0 or end <= start:
            raise PictureLockError(f"{label}[{index}] is empty")
        total += end - start
    return total


def _rank(value: object) -> tuple[tuple, dict]:
    if not isinstance(value, dict) or set(value) != {
            "operation", "operationHash"}:
        raise PictureLockError("repair candidate envelope is malformed")
    operation = value["operation"]
    if not isinstance(operation, dict):
        raise PictureLockError("repair candidate operation is malformed")
    operation_hash = require_hash(
        value["operationHash"], "repair candidate operation hash")
    if content_hash(operation) != operation_hash:
        raise PictureLockError("repair candidate operation hash is stale")
    method = operation.get("method")
    if method not in _METHOD_ORDER:
        raise PictureLockError("repair candidate method is unsupported")
    extension = operation.get("extensionFrames")
    if type(extension) is not int or extension <= 0:
        raise PictureLockError("repair candidate extension is malformed")
    picture = _range_cost(
        operation.get("pictureDirtyWindows"), "picture dirty windows")
    audio = _range_cost(
        operation.get("audioDirtyWindows"), "audio dirty windows")
    return (
        (_METHOD_ORDER[method], picture, audio, extension, operation_hash),
        value,
    )


def select_restore_candidate(rows: object) -> dict:
    """Select the same minimum-impact candidate regardless of input order."""
    if not isinstance(rows, list) or not rows:
        raise PictureLockError("eligible repair has no candidates")
    ranked = [_rank(row) for row in rows]
    hashes = [row[0][-1] for row in ranked]
    if len(set(hashes)) != len(hashes):
        raise PictureLockError("repair candidates contain duplicate operations")
    selected = min(ranked, key=lambda row: row[0])[1]
    policy = {
        "schemaVersion": 1,
        "kind": "cut-repair-selection-policy",
        "order": [
            "audio-only-before-picture",
            "fewest-picture-dirty-frames",
            "fewest-audio-dirty-frames",
            "shortest-source-extension",
            "operation-hash-tiebreak",
        ],
    }
    return {
        **selected,
        "selectionPolicy": policy,
        "selectionPolicyHash": content_hash(policy),
    }
