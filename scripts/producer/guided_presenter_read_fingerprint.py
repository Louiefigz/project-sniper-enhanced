"""Private, detached metadata fences; never a persisted receipt/hash domain.

Callers first validate their original JSON and file-reference contracts. These
snapshots then compare every callback without serializing those receipts again.
They neither read files nor replace the caller's source, namespace or clock
checks. Frozen dataclasses are copied field by field, not trusted by identity.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
import math
import struct


@dataclass(frozen=True, slots=True)
class _MetadataSnapshot:
    """Type-tagged immutable scalar or recursively detached child nodes."""

    kind: type
    form: str
    value: object


def hold_read_metadata(value: object) -> _MetadataSnapshot:
    """Capture exact types and values without creating execution authority."""
    kind = type(value)
    if kind is float:
        if not math.isfinite(value):
            raise ValueError("presenter read metadata must be finite")
        return _MetadataSnapshot(kind, "float", struct.pack("!d", value))
    if kind in (type(None), bool, int, str, bytes):
        return _MetadataSnapshot(kind, "scalar", value)
    if kind in (list, tuple):
        return _MetadataSnapshot(kind, "sequence", tuple(hold_read_metadata(row) for row in value))
    if kind is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("presenter read metadata keys must be strings")
        return _MetadataSnapshot(kind, "mapping", tuple((key, hold_read_metadata(row)) for key, row in value.items()))
    if is_dataclass(value) and not isinstance(value, type):
        return _MetadataSnapshot(kind, "record", tuple(
            (row.name, hold_read_metadata(getattr(value, row.name))) for row in fields(value)))
    raise ValueError("presenter read metadata has an unsupported type")


def same_read_metadata(value: object, held: _MetadataSnapshot) -> bool:
    """Compare original detached fields, including equal-valued numeric drift."""
    if type(value) is not held.kind:
        return False
    if held.form == "scalar":
        return value == held.value
    if held.form == "float":
        return struct.pack("!d", value) == held.value
    if held.form == "sequence":
        return len(value) == len(held.value) and all(
            same_read_metadata(row, expected) for row, expected in zip(value, held.value))
    if held.form == "mapping":
        return len(value) == len(held.value) and all(type(key) is str for key in value) and all(
            key in value and same_read_metadata(value[key], expected) for key, expected in held.value)
    if held.form == "record":
        return all(hasattr(value, key) and same_read_metadata(getattr(value, key), expected)
                   for key, expected in held.value)
    raise RuntimeError("presenter read private metadata snapshot is malformed")
