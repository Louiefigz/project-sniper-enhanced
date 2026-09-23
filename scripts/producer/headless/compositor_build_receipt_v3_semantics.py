"""Exact current compositor receipt V3; historical V1 is never reinterpreted."""
from __future__ import annotations

from dataclasses import dataclass
from .wire_identity import same_wire_value

import headless.compositor_build_receipt_semantics as common
from .compositor_build_manifest_v3_semantics import (
    CompositorBuildManifestSchemaError,
    CompositorBuildManifestV3,
    parse_compositor_build_manifest_v3,
)

CompositorBuildReceiptSchemaError = common.CompositorBuildReceiptSchemaError


@dataclass(frozen=True)
class CompositorBuildReceiptV3:
    """Canonical declarations, not live execution or output-quality evidence."""

    build_digest: str
    manifest: CompositorBuildManifestV3
    document_json: bytes


def parse_compositor_build_receipt_v3(raw: object) -> CompositorBuildReceiptV3:
    """Require the same exact version in outer receipt and inner manifest."""
    document = common._document(raw)
    declared = document.get("buildDigest")
    valid = set(document) == common._KEYS
    valid = valid and type(document.get("schemaVersion")) is int
    valid = valid and document.get("schemaVersion") == 3
    valid = valid and type(declared) is str and common._DIGEST.fullmatch(declared)
    valid = valid and type(document.get("manifest")) is dict
    if not valid:
        raise CompositorBuildReceiptSchemaError("compositor V3 receipt envelope is invalid")
    try:
        manifest = parse_compositor_build_manifest_v3(common._canonical(document["manifest"]))
    except CompositorBuildManifestSchemaError as exc:
        raise CompositorBuildReceiptSchemaError("compositor V3 receipt manifest is invalid") from exc
    if manifest.build_digest != declared:
        raise CompositorBuildReceiptSchemaError("compositor V3 digest does not match manifest")
    return CompositorBuildReceiptV3(declared, manifest, raw)


def validate_compositor_build_receipt_v3(value: object) -> None:
    """Reparse exact retained bytes; no caller-defined equality is authority."""
    if type(value) is not CompositorBuildReceiptV3:
        raise CompositorBuildReceiptSchemaError("compositor V3 receipt instance is invalid")
    parsed = parse_compositor_build_receipt_v3(value.document_json)
    if not same_wire_value(value, parsed):
        raise CompositorBuildReceiptSchemaError("compositor V3 receipt was forged")
