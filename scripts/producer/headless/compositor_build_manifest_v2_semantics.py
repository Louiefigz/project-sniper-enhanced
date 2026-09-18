"""Pure compositor V2 parser; V1 meaning and its legacy digest stay frozen."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import headless.compositor_build_manifest_semantics as common
from .compositor_build_manifest_v2_contract import (
    COMPOSITOR_BUILD_V2_DIGEST_DOMAIN,
    COMPOSITOR_BUILD_V2_IMPLEMENTATION_PATHS,
    COMPOSITOR_BUILD_V2_POLICY,
)
from .wire_identity import same_wire_value

CompositorBuildManifestSchemaError = common.CompositorBuildManifestSchemaError


@dataclass(frozen=True)
class CompositorBuildManifestV2(common.CompositorBuildManifestV1):
    """Same immutable row shape, but a distinct exact wire type and digest."""


def _source_rows(value: object) -> tuple[common.CompositorBuildSourceRowV1, ...]:
    """Require every V2 row at its fixed position without accepting extra keys."""
    expected = COMPOSITOR_BUILD_V2_IMPLEMENTATION_PATHS
    if type(value) is not list or len(value) != len(expected):
        raise CompositorBuildManifestSchemaError("compositor V2 source count is invalid")
    rows = []
    for item, path in zip(value, expected):
        valid = type(item) is dict and set(item) == common._SOURCE_KEYS
        valid = valid and type(item["path"]) is str and item["path"] == path
        valid = valid and type(item["sha256"]) is str and common._DIGEST.fullmatch(item["sha256"])
        valid = valid and type(item["sizeBytes"]) is int and item["sizeBytes"] > 0
        if not valid:
            raise CompositorBuildManifestSchemaError("compositor V2 closed source row is invalid")
        rows.append(common.CompositorBuildSourceRowV1(path, item["sha256"], item["sizeBytes"]))
    return tuple(rows)


def parse_compositor_build_manifest_v2(raw: object) -> CompositorBuildManifestV2:
    """Bind the entire canonical V2 document, not V1's basename-only digest."""
    document = common._document(raw)
    valid = set(document) == common._TOP_KEYS
    valid = valid and type(document.get("schemaVersion")) is int
    valid = valid and document.get("schemaVersion") == 2
    valid = valid and document.get("policy") == COMPOSITOR_BUILD_V2_POLICY
    if not valid:
        raise CompositorBuildManifestSchemaError("compositor V2 manifest envelope is invalid")
    rows = _source_rows(document["implementation"])
    digest = hashlib.sha256(COMPOSITOR_BUILD_V2_DIGEST_DOMAIN + raw).hexdigest()
    return CompositorBuildManifestV2(rows, raw, digest)


def validate_compositor_build_manifest_v2(value: object) -> None:
    """Reject forged instances and hostile equality without live source reads."""
    if type(value) is not CompositorBuildManifestV2:
        raise CompositorBuildManifestSchemaError("compositor V2 manifest instance is invalid")
    parsed = parse_compositor_build_manifest_v2(value.document_json)
    if not same_wire_value(value, parsed):
        raise CompositorBuildManifestSchemaError("compositor V2 manifest was forged")
