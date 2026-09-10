"""Current render receipt V3, separate from all historical archive versions."""
from __future__ import annotations

from dataclasses import dataclass

import headless.render_build_receipt_semantics as common
from .render_build_manifest_v3_semantics import (
    RenderBuildManifestSchemaError,
    RenderBuildManifestV3,
    parse_render_build_manifest_v3,
)
from .wire_identity import same_wire_value

RenderBuildReceiptSchemaError = common.RenderBuildReceiptSchemaError


@dataclass(frozen=True)
class RenderBuildReceiptV3:
    """Canonical source/tool declarations, not observed execution or quality."""

    build_digest: str
    manifest: RenderBuildManifestV3
    document_json: bytes


def parse_render_build_receipt_v3(raw: object) -> RenderBuildReceiptV3:
    """Require current receipt and manifest versions to match exactly."""
    document = common._document(raw)
    declared = document.get("buildDigest")
    valid = set(document) == common._KEYS
    valid = valid and type(document.get("schemaVersion")) is int
    valid = valid and document.get("schemaVersion") == 3
    valid = valid and type(declared) is str and common._DIGEST.fullmatch(declared)
    valid = valid and type(document.get("manifest")) is dict
    if not valid:
        raise RenderBuildReceiptSchemaError("render V3 receipt envelope is invalid")
    try:
        manifest = parse_render_build_manifest_v3(common._canonical(document["manifest"]))
    except RenderBuildManifestSchemaError as exc:
        raise RenderBuildReceiptSchemaError("render V3 receipt manifest is invalid") from exc
    if manifest.build_digest != declared:
        raise RenderBuildReceiptSchemaError("render V3 digest does not match manifest")
    return RenderBuildReceiptV3(declared, manifest, raw)


def validate_render_build_receipt_v3(value: object) -> None:
    """Reparse all retained fields and reject caller-defined equality tricks."""
    if type(value) is not RenderBuildReceiptV3:
        raise RenderBuildReceiptSchemaError("render V3 receipt instance is invalid")
    parsed = parse_render_build_receipt_v3(value.document_json)
    if not same_wire_value(value, parsed):
        raise RenderBuildReceiptSchemaError("render V3 receipt was forged")
