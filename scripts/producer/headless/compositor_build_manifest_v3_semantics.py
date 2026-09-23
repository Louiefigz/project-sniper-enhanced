"""Pure compositor V3 parser; V1 meaning and its legacy digest stay frozen."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from .wire_identity import same_wire_value

import headless.compositor_build_manifest_semantics as common
from .compositor_build_manifest_v2_contract import COMPOSITOR_BUILD_V2_IMPLEMENTATION_PATHS

COMPOSITOR_BUILD_V3_POLICY = "sniper-prebound-compositor-build-v3"
COMPOSITOR_BUILD_V3_DIGEST_DOMAIN = b"sniper-prebound-compositor-build-v3\0"
COMPOSITOR_BUILD_V3_IMPLEMENTATION_PATHS = (
    *COMPOSITOR_BUILD_V2_IMPLEMENTATION_PATHS,
    "scripts/producer/graphics/scene_contract.py",
    "scripts/producer/graphics/visual_source_policy.py",
    "scripts/producer/graphics/visual_source_receipt.py",
    "schemas/producer/visual-source-policy-v1.json",
    "scripts/producer/headless/compositor_build_manifest_v3_semantics.py",
    "scripts/producer/headless/compositor_build_receipt_v3_semantics.py",
)

CompositorBuildManifestSchemaError = common.CompositorBuildManifestSchemaError


@dataclass(frozen=True)
class CompositorBuildManifestV3(common.CompositorBuildManifestV1):
    """Current catalog-aware immutable rows with a distinct wire identity."""


def _source_rows(value: object) -> tuple[common.CompositorBuildSourceRowV1, ...]:
    """Require every V3 row at its fixed position without accepting extra keys."""
    expected = COMPOSITOR_BUILD_V3_IMPLEMENTATION_PATHS
    if type(value) is not list or len(value) != len(expected):
        raise CompositorBuildManifestSchemaError("compositor V3 source count is invalid")
    rows = []
    for item, path in zip(value, expected):
        valid = type(item) is dict and set(item) == common._SOURCE_KEYS
        valid = valid and type(item["path"]) is str and item["path"] == path
        valid = valid and type(item["sha256"]) is str and common._DIGEST.fullmatch(item["sha256"])
        valid = valid and type(item["sizeBytes"]) is int and item["sizeBytes"] > 0
        if not valid:
            raise CompositorBuildManifestSchemaError("compositor V3 closed source row is invalid")
        rows.append(common.CompositorBuildSourceRowV1(path, item["sha256"], item["sizeBytes"]))
    return tuple(rows)


def parse_compositor_build_manifest_v3(raw: object) -> CompositorBuildManifestV3:
    """Bind the entire canonical V3 document, not V1's basename-only digest."""
    document = common._document(raw)
    valid = set(document) == common._TOP_KEYS
    valid = valid and type(document.get("schemaVersion")) is int
    valid = valid and document.get("schemaVersion") == 3
    valid = valid and document.get("policy") == COMPOSITOR_BUILD_V3_POLICY
    if not valid:
        raise CompositorBuildManifestSchemaError("compositor V3 manifest envelope is invalid")
    rows = _source_rows(document["implementation"])
    digest = hashlib.sha256(COMPOSITOR_BUILD_V3_DIGEST_DOMAIN + raw).hexdigest()
    return CompositorBuildManifestV3(rows, raw, digest)


def validate_compositor_build_manifest_v3(value: object) -> None:
    """Reject forged instances and hostile equality without live source reads."""
    if type(value) is not CompositorBuildManifestV3:
        raise CompositorBuildManifestSchemaError("compositor V3 manifest instance is invalid")
    parsed = parse_compositor_build_manifest_v3(value.document_json)
    if not same_wire_value(value, parsed):
        raise CompositorBuildManifestSchemaError("compositor V3 manifest was forged")
