"""Closed semantic parser for retained compositor build manifests."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass

from .compositor_build_manifest_v1_contract import (
    COMPOSITOR_BUILD_V1_DIGEST_DOMAIN,
    COMPOSITOR_BUILD_V1_IMPLEMENTATION_PATHS,
    COMPOSITOR_BUILD_V1_POLICY,
)
from .wire_identity import same_wire_value

_DIGEST = re.compile(r"[0-9a-f]{64}")
_TOP_KEYS = frozenset("implementation policy schemaVersion".split())
_SOURCE_KEYS = frozenset("path sha256 sizeBytes".split())
_MAX_BYTES = 2 * 1024 * 1024


class CompositorBuildManifestSchemaError(RuntimeError):
    """A compositor build manifest is malformed or outside frozen V1."""


class _DuplicateKey(ValueError):
    pass


@dataclass(frozen=True)
class CompositorBuildSourceRowV1:
    """One exact source identity in the declared compositor closure."""

    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class CompositorBuildManifestV1:
    """Canonical static source manifest with a recomputed legacy digest."""

    implementation: tuple[CompositorBuildSourceRowV1, ...]
    document_json: bytes
    build_digest: str


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
        raise CompositorBuildManifestSchemaError(
            "compositor build manifest cannot be canonicalized"
        ) from exc
    return text.encode("ascii")


def _document(raw: object) -> dict:
    if type(raw) is not bytes or not 0 < len(raw) <= _MAX_BYTES:
        raise CompositorBuildManifestSchemaError(
            "compositor build manifest bytes are invalid"
        )
    try:
        value = json.loads(
            raw, object_pairs_hook=_pairs, parse_constant=_constant
        )
    except _DuplicateKey as exc:
        raise CompositorBuildManifestSchemaError(
            "compositor build manifest has duplicate keys"
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CompositorBuildManifestSchemaError(
            "compositor build manifest is invalid JSON"
        ) from exc
    if type(value) is not dict or _canonical(value) != raw:
        raise CompositorBuildManifestSchemaError(
            "compositor build manifest is not exact canonical JSON"
        )
    return value


def _source_rows(value: object) -> tuple[CompositorBuildSourceRowV1, ...]:
    if type(value) is not list:
        raise CompositorBuildManifestSchemaError(
            "compositor implementation is not an array"
        )
    rows = []
    for item in value:
        valid = type(item) is dict and set(item) == _SOURCE_KEYS
        digest = item.get("sha256") if valid else None
        size = item.get("sizeBytes") if valid else None
        valid = valid and type(digest) is str and _DIGEST.fullmatch(digest)
        valid = valid and type(size) is int and size > 0
        if not valid:
            raise CompositorBuildManifestSchemaError(
                "compositor source row is invalid"
            )
        rows.append(CompositorBuildSourceRowV1(item["path"], digest, size))
    paths = tuple(row.path for row in rows)
    if paths != COMPOSITOR_BUILD_V1_IMPLEMENTATION_PATHS:
        raise CompositorBuildManifestSchemaError(
            "compositor source order or closed path set is invalid"
        )
    return tuple(rows)


def _manifest_digest(rows: tuple[CompositorBuildSourceRowV1, ...]) -> str:
    digest = hashlib.sha256(COMPOSITOR_BUILD_V1_DIGEST_DOMAIN)
    for row in rows:
        digest.update(os.path.basename(row.path).encode("utf-8") + b"\0")
        digest.update(bytes.fromhex(row.sha256))
    return digest.hexdigest()


def parse_compositor_build_manifest_v1(
    raw: object,
) -> CompositorBuildManifestV1:
    """Parse frozen V1 rows and recompute their historical build digest."""
    document = _document(raw)
    valid = set(document) == _TOP_KEYS
    valid = valid and type(document.get("schemaVersion")) is int
    valid = valid and document.get("schemaVersion") == 1
    valid = valid and document.get("policy") == COMPOSITOR_BUILD_V1_POLICY
    if not valid:
        raise CompositorBuildManifestSchemaError(
            "compositor build manifest envelope is invalid"
        )
    rows = _source_rows(document["implementation"])
    return CompositorBuildManifestV1(rows, raw, _manifest_digest(rows))


def validate_compositor_build_manifest_v1(value: object) -> None:
    """Reject forged dataclass values and overloaded equality tricks."""
    valid = type(value) is CompositorBuildManifestV1
    valid = valid and type(getattr(value, "document_json", None)) is bytes
    if not valid:
        raise CompositorBuildManifestSchemaError(
            "compositor build manifest instance is invalid"
        )
    parsed = parse_compositor_build_manifest_v1(value.document_json)
    if not same_wire_value(value, parsed):
        raise CompositorBuildManifestSchemaError(
            "compositor build manifest was forged"
        )
