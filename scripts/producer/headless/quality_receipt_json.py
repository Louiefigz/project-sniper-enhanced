"""Canonical JSON and leaf validators for immutable quality receipts."""

from __future__ import annotations

import json
import re
import uuid

from . import artifact_contract as artifacts
from .wire_identity import same_wire_value as same_typed_value

ArtifactRefV1 = artifacts.ArtifactRefV1

__all__ = [
    "ArtifactRefV1",
    "QualityReceiptSchemaError",
    "artifact",
    "authority",
    "canonical_document",
    "canonical_uuid",
    "digest",
    "exact",
    "same_typed_value",
]

_DIGEST = re.compile(r"[0-9a-f]{64}")
_AUTHORITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_ARTIFACT_KEYS = frozenset("path sha256 sizeBytes".split())


class QualityReceiptSchemaError(RuntimeError):
    """Canonical receipt bytes or semantic bindings are invalid."""


class _DuplicateKey(ValueError):
    pass


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise QualityReceiptSchemaError("receipt cannot be canonicalized") from exc
    return encoded.encode("ascii")


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    document = {}
    for key, value in pairs:
        if key in document:
            raise _DuplicateKey(key)
        document[key] = value
    return document


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def canonical_document(raw: object, label: str) -> dict:
    """Decode only immutable exact-canonical object bytes."""
    if type(raw) is not bytes:
        raise QualityReceiptSchemaError(f"{label} must be canonical bytes")
    try:
        document = json.loads(
            raw, object_pairs_hook=_pairs, parse_constant=_reject_constant
        )
    except _DuplicateKey as exc:
        raise QualityReceiptSchemaError(f"{label} has duplicate JSON keys") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise QualityReceiptSchemaError(f"{label} is invalid JSON") from exc
    if type(document) is not dict or _canonical(document) != raw:
        raise QualityReceiptSchemaError(f"{label} is not exact canonical JSON")
    return document


def exact(value: object, keys: frozenset[str], label: str) -> dict:
    """Require an object with exactly the named keys."""
    if type(value) is not dict or set(value) != keys:
        raise QualityReceiptSchemaError(f"{label} keys are invalid")
    return value


def digest(value: object, label: str) -> str:
    """Require an exact lowercase SHA-256 string."""
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise QualityReceiptSchemaError(f"{label} must be lowercase SHA-256")
    return value


def canonical_uuid(value: object, label: str) -> str:
    """Require canonical lowercase UUID text."""
    if type(value) is not str:
        raise QualityReceiptSchemaError(f"{label} must be a canonical UUID")
    try:
        parsed = str(uuid.UUID(value))
    except ValueError as exc:
        raise QualityReceiptSchemaError(f"{label} must be a canonical UUID") from exc
    if parsed != value:
        raise QualityReceiptSchemaError(f"{label} must use canonical UUID form")
    return value


def authority(value: object) -> str:
    """Require the same closed authority syntax as the generation commit."""
    if type(value) is not str or not _AUTHORITY.fullmatch(value):
        raise QualityReceiptSchemaError("authority ID is invalid")
    return value


def artifact(value: object) -> ArtifactRefV1:
    """Parse one exact immutable generation-relative artifact reference."""
    row = exact(value, _ARTIFACT_KEYS, "artifact reference")
    parsed = ArtifactRefV1(row["path"], row["sha256"], row["sizeBytes"])
    try:
        artifacts.validate_artifact_ref(parsed)
    except artifacts.ArtifactContractError as exc:
        raise QualityReceiptSchemaError(str(exc)) from exc
    return parsed
