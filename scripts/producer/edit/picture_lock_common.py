"""Shared canonical-hash primitives for P2 picture-lock artifacts."""
from __future__ import annotations

import hashlib

from cross_runtime_canonical_json import (
    CrossRuntimeCanonicalJsonError,
    canonical_compact_json,
)


class PictureLockError(ValueError):
    """Picture-lock authority or preservation evidence is invalid."""


def canonical_json(value: object) -> str:
    """Return the repository's compact deterministic JSON representation."""
    try:
        return canonical_compact_json(value)
    except CrossRuntimeCanonicalJsonError as exc:
        raise PictureLockError("picture-lock value is not canonical JSON") from exc


def content_hash(value: object) -> str:
    """Return SHA-256 over canonical JSON UTF-8 bytes."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def require_hash(value: str, label: str) -> str:
    """Return one validated lowercase SHA-256."""
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise PictureLockError(f"{label} must be a lowercase SHA-256")
    return value
