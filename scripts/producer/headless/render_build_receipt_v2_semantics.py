"""Current render-build-receipt-v2; never an implicit V1 archive upgrade."""

from __future__ import annotations

from dataclasses import dataclass

import headless.render_build_receipt_semantics as common
from .render_build_manifest_v2_semantics import (
    RenderBuildManifestSchemaError,
    RenderBuildManifestV2,
    parse_render_build_manifest_v2,
)
from .wire_identity import same_wire_value

RenderBuildReceiptSchemaError = common.RenderBuildReceiptSchemaError


@dataclass(frozen=True)
class RenderBuildReceiptV2:
    """Canonical receipt with recomputed declarations, not live observation."""

    build_digest: str
    manifest: RenderBuildManifestV2
    document_json: bytes


def parse_render_build_receipt_v2(raw: object) -> RenderBuildReceiptV2:
    """Parse V2 only; an old policy or mixed-version envelope fails closed."""
    document = common._document(raw)
    declared = document.get("buildDigest")
    valid = set(document) == common._KEYS
    valid = valid and type(document.get("schemaVersion")) is int
    valid = valid and document.get("schemaVersion") == 2
    valid = valid and type(declared) is str and common._DIGEST.fullmatch(declared)
    valid = valid and type(document.get("manifest")) is dict
    if not valid:
        raise RenderBuildReceiptSchemaError("render V2 receipt envelope is invalid")
    try:
        manifest = parse_render_build_manifest_v2(common._canonical(document["manifest"]))
    except RenderBuildManifestSchemaError as exc:
        raise RenderBuildReceiptSchemaError("render V2 receipt manifest is invalid") from exc
    if manifest.build_digest != declared:
        raise RenderBuildReceiptSchemaError("render V2 digest does not match manifest")
    return RenderBuildReceiptV2(declared, manifest, raw)


def validate_render_build_receipt_v2(value: object) -> None:
    """Validate exact immutable fields against their retained wire bytes."""
    if type(value) is not RenderBuildReceiptV2:
        raise RenderBuildReceiptSchemaError("render V2 receipt instance is invalid")
    parsed = parse_render_build_receipt_v2(value.document_json)
    if not same_wire_value(value, parsed):
        raise RenderBuildReceiptSchemaError("render V2 receipt was forged")
