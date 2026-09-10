"""Exact current compositor receipt V2; historical V1 is never reinterpreted."""
from __future__ import annotations

from dataclasses import dataclass

import headless.compositor_build_receipt_semantics as common
from .compositor_build_manifest_v2_semantics import (
    CompositorBuildManifestSchemaError,
    CompositorBuildManifestV2,
    parse_compositor_build_manifest_v2,
)
from .wire_identity import same_wire_value

CompositorBuildReceiptSchemaError = common.CompositorBuildReceiptSchemaError


@dataclass(frozen=True)
class CompositorBuildReceiptV2:
    """Canonical declarations, not live execution or output-quality evidence."""

    build_digest: str
    manifest: CompositorBuildManifestV2
    document_json: bytes


def parse_compositor_build_receipt_v2(raw: object) -> CompositorBuildReceiptV2:
    """Require the same exact version in outer receipt and inner manifest."""
    document = common._document(raw)
    declared = document.get("buildDigest")
    valid = set(document) == common._KEYS
    valid = valid and type(document.get("schemaVersion")) is int
    valid = valid and document.get("schemaVersion") == 2
    valid = valid and type(declared) is str and common._DIGEST.fullmatch(declared)
    valid = valid and type(document.get("manifest")) is dict
    if not valid:
        raise CompositorBuildReceiptSchemaError("compositor V2 receipt envelope is invalid")
    try:
        manifest = parse_compositor_build_manifest_v2(common._canonical(document["manifest"]))
    except CompositorBuildManifestSchemaError as exc:
        raise CompositorBuildReceiptSchemaError("compositor V2 receipt manifest is invalid") from exc
    if manifest.build_digest != declared:
        raise CompositorBuildReceiptSchemaError("compositor V2 digest does not match manifest")
    return CompositorBuildReceiptV2(declared, manifest, raw)


def validate_compositor_build_receipt_v2(value: object) -> None:
    """Reparse exact retained bytes; no caller-defined equality is authority."""
    if type(value) is not CompositorBuildReceiptV2:
        raise CompositorBuildReceiptSchemaError("compositor V2 receipt instance is invalid")
    parsed = parse_compositor_build_receipt_v2(value.document_json)
    if not same_wire_value(value, parsed):
        raise CompositorBuildReceiptSchemaError("compositor V2 receipt was forged")
