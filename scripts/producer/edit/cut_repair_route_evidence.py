"""Closed acoustic evidence validation for cut-repair route contexts."""
from __future__ import annotations

import re

_HASH = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED = {
    "alignment": "pinned-bounded-evidence",
    "vad": "pinned-bounded-evidence",
    "audition": "operator-reported-damage",
    "audioIsolation": "dialogue-only-bounded-evidence",
}


class RouteEvidenceError(ValueError):
    """Cut-repair route evidence is absent or malformed."""


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise RouteEvidenceError(f"{label} must be an object")
    return value


def _closed(value: dict, allowed: set[str], label: str) -> None:
    extras = set(value) - allowed
    missing = allowed - set(value)
    if extras or missing:
        raise RouteEvidenceError(
            f"{label} fields are not closed: "
            f"extras={sorted(extras)}, missing={sorted(missing)}")


def _allowed_fields(key: str) -> set[str]:
    fields = {"status", "receiptSha256"}
    if key == "alignment":
        fields.update({"runtimeSha256", "modelSha256", "cacheSha256"})
    if key == "audioIsolation":
        fields.update({"runtimeSha256", "musicSfxOverlapCount"})
    return fields


def _validate_field(key: str, item: dict, name: str) -> None:
    if name == "musicSfxOverlapCount":
        if item[name] != 0:
            raise RouteEvidenceError(
                "context audio isolation has music/SFX overlap")
        return
    value = item[name]
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise RouteEvidenceError(
            f"context.evidence.{key}.{name} must be a lowercase SHA-256")


def _validate_item(row: dict, key: str, status: str) -> None:
    label = f"context.evidence.{key}"
    item = _object(row[key], label)
    allowed = _allowed_fields(key)
    _closed(item, allowed, label)
    if item["status"] != status:
        raise RouteEvidenceError(f"context {key} evidence is not qualified")
    for name in allowed - {"status"}:
        _validate_field(key, item, name)


def validate_route_evidence(value: object) -> None:
    """Require every pinned/operator evidence lane and exact hash binding."""
    row = _object(value, "context.evidence")
    _closed(row, set(_EXPECTED), "context.evidence")
    for key, status in _EXPECTED.items():
        _validate_item(row, key, status)
