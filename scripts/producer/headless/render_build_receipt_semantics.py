"""Exact wire parser for retained render-build-receipt-v1 bytes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .render_build_manifest_semantics import (
    RenderBuildManifestSchemaError,
    RenderBuildManifestV1,
    parse_render_build_manifest_v1,
)
from .wire_identity import same_wire_value

_DIGEST = re.compile(r"[0-9a-f]{64}")
_KEYS = frozenset("buildDigest manifest schemaVersion".split())
_MAX_BYTES = 2 * 1024 * 1024


class RenderBuildReceiptSchemaError(RuntimeError):
    """Retained render-build receipt bytes are malformed or inconsistent."""


class _DuplicateKey(ValueError):
    pass


@dataclass(frozen=True)
class RenderBuildReceiptV1:
    """Canonical retained receipt with a recomputed static manifest digest."""

    build_digest: str
    manifest: RenderBuildManifestV1
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
        raise RenderBuildReceiptSchemaError(
            "render build receipt cannot be canonicalized"
        ) from exc
    return text.encode("ascii")


def _document(raw: object) -> dict:
    valid = type(raw) is bytes and 0 < len(raw) <= _MAX_BYTES
    valid = valid and raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    if not valid:
        raise RenderBuildReceiptSchemaError(
            "render build receipt bytes are invalid"
        )
    try:
        document = json.loads(
            raw[:-1], object_pairs_hook=_pairs, parse_constant=_constant
        )
    except _DuplicateKey as exc:
        raise RenderBuildReceiptSchemaError(
            "render build receipt has duplicate keys"
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RenderBuildReceiptSchemaError(
            "render build receipt is invalid JSON"
        ) from exc
    if type(document) is not dict or _canonical(document) + b"\n" != raw:
        raise RenderBuildReceiptSchemaError(
            "render build receipt is not exact canonical JSON"
        )
    return document


def parse_render_build_receipt_v1(raw: object) -> RenderBuildReceiptV1:
    """Parse retained bytes and recompute the declared render build digest."""
    document = _document(raw)
    declared = document.get("buildDigest")
    valid = set(document) == _KEYS
    valid = valid and type(document.get("schemaVersion")) is int
    valid = valid and document.get("schemaVersion") == 1
    valid = valid and type(declared) is str and _DIGEST.fullmatch(declared)
    valid = valid and type(document.get("manifest")) is dict
    if not valid:
        raise RenderBuildReceiptSchemaError(
            "render build receipt envelope is invalid"
        )
    try:
        manifest = parse_render_build_manifest_v1(
            _canonical(document["manifest"])
        )
    except RenderBuildManifestSchemaError as exc:
        raise RenderBuildReceiptSchemaError(
            "render build receipt manifest is invalid"
        ) from exc
    if manifest.build_digest != declared:
        raise RenderBuildReceiptSchemaError(
            "render build digest does not match manifest"
        )
    return RenderBuildReceiptV1(declared, manifest, raw)


def validate_render_build_receipt_v1(value: object) -> None:
    """Reject direct construction and equality-overload receipt forgeries."""
    valid = type(value) is RenderBuildReceiptV1
    valid = valid and type(getattr(value, "document_json", None)) is bytes
    if not valid:
        raise RenderBuildReceiptSchemaError(
            "render build receipt instance is invalid"
        )
    parsed = parse_render_build_receipt_v1(value.document_json)
    if not same_wire_value(value, parsed):
        raise RenderBuildReceiptSchemaError("render build receipt was forged")
