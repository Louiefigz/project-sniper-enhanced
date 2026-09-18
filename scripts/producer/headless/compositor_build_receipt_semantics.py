"""Exact parser for newline-terminated compositor build receipt V1."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .compositor_build_manifest_semantics import (
    CompositorBuildManifestSchemaError,
    CompositorBuildManifestV1,
    parse_compositor_build_manifest_v1,
)
from .wire_identity import same_wire_value

_DIGEST = re.compile(r"[0-9a-f]{64}")
_KEYS = frozenset("buildDigest manifest schemaVersion".split())
_MAX_BYTES = 2 * 1024 * 1024


class CompositorBuildReceiptSchemaError(RuntimeError):
    """Retained compositor build receipt bytes are not exact frozen V1."""


class _DuplicateKey(ValueError):
    pass


@dataclass(frozen=True)
class CompositorBuildReceiptV1:
    """Canonical receipt containing one recomputed static source manifest."""

    build_digest: str
    manifest: CompositorBuildManifestV1
    document_json: bytes


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    document = {}
    for key, value in pairs:
        if key in document:
            raise _DuplicateKey(key)
        document[key] = value
    return document


def _constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _canonical(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CompositorBuildReceiptSchemaError(
            "compositor build receipt cannot be canonicalized"
        ) from exc
    return text.encode("ascii")


def _document(raw: object) -> dict:
    valid = type(raw) is bytes and 0 < len(raw) <= _MAX_BYTES
    valid = valid and raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    if not valid:
        raise CompositorBuildReceiptSchemaError(
            "compositor build receipt bytes are invalid"
        )
    try:
        value = json.loads(
            raw[:-1], object_pairs_hook=_pairs, parse_constant=_constant
        )
    except _DuplicateKey as exc:
        raise CompositorBuildReceiptSchemaError(
            "compositor build receipt has duplicate keys"
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CompositorBuildReceiptSchemaError(
            "compositor build receipt is invalid JSON"
        ) from exc
    if type(value) is not dict or _canonical(value) + b"\n" != raw:
        raise CompositorBuildReceiptSchemaError(
            "compositor build receipt is not exact canonical JSON"
        )
    return value


def parse_compositor_build_receipt_v1(raw: object) -> CompositorBuildReceiptV1:
    """Parse exact receipt bytes and independently recompute their digest."""
    document = _document(raw)
    declared = document.get("buildDigest")
    valid = set(document) == _KEYS
    valid = valid and type(document.get("schemaVersion")) is int
    valid = valid and document.get("schemaVersion") == 1
    valid = valid and type(declared) is str and _DIGEST.fullmatch(declared)
    valid = valid and type(document.get("manifest")) is dict
    if not valid:
        raise CompositorBuildReceiptSchemaError(
            "compositor build receipt envelope is invalid"
        )
    try:
        manifest = parse_compositor_build_manifest_v1(
            _canonical(document["manifest"])
        )
    except CompositorBuildManifestSchemaError as exc:
        raise CompositorBuildReceiptSchemaError(
            "compositor build receipt manifest is invalid"
        ) from exc
    if manifest.build_digest != declared:
        raise CompositorBuildReceiptSchemaError(
            "compositor build digest does not match manifest"
        )
    return CompositorBuildReceiptV1(declared, manifest, raw)


def validate_compositor_build_receipt_v1(value: object) -> None:
    """Reject forged dataclass instances even when equality is overloaded."""
    valid = type(value) is CompositorBuildReceiptV1
    valid = valid and type(getattr(value, "document_json", None)) is bytes
    if not valid:
        raise CompositorBuildReceiptSchemaError(
            "compositor build receipt instance is invalid"
        )
    parsed = parse_compositor_build_receipt_v1(value.document_json)
    if not same_wire_value(value, parsed):
        raise CompositorBuildReceiptSchemaError(
            "compositor build receipt was forged"
        )
