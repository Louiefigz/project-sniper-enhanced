"""Current render receipt V4, separate from all historical archive versions."""
from __future__ import annotations

from dataclasses import dataclass
from .wire_identity import same_wire_value

import headless.render_build_receipt_semantics as common
from .render_build_manifest_v4_semantics import (
    RenderBuildManifestSchemaError,
    RenderBuildManifestV4,
    parse_render_build_manifest_v4,
)

RenderBuildReceiptSchemaError = common.RenderBuildReceiptSchemaError


@dataclass(frozen=True)
class RenderBuildReceiptV4:
    """Canonical source/tool declarations, not observed execution or quality."""

    build_digest: str
    manifest: RenderBuildManifestV4
    document_json: bytes


def parse_render_build_receipt_v4(raw: object) -> RenderBuildReceiptV4:
    """Require current receipt and manifest versions to match exactly."""
    document = common._document(raw)
    declared = document.get("buildDigest")
    valid = set(document) == common._KEYS
    valid = valid and type(document.get("schemaVersion")) is int
    valid = valid and document.get("schemaVersion") == 4
    valid = valid and type(declared) is str and common._DIGEST.fullmatch(declared)
    valid = valid and type(document.get("manifest")) is dict
    if not valid:
        raise RenderBuildReceiptSchemaError("render V4 receipt envelope is invalid")
    try:
        manifest = parse_render_build_manifest_v4(common._canonical(document["manifest"]))
    except RenderBuildManifestSchemaError as exc:
        raise RenderBuildReceiptSchemaError("render V4 receipt manifest is invalid") from exc
    if manifest.build_digest != declared:
        raise RenderBuildReceiptSchemaError("render V4 digest does not match manifest")
    return RenderBuildReceiptV4(declared, manifest, raw)


def validate_render_build_receipt_v4(value: object) -> None:
    """Reparse all retained fields and reject caller-defined equality tricks."""
    if type(value) is not RenderBuildReceiptV4:
        raise RenderBuildReceiptSchemaError("render V4 receipt instance is invalid")
    parsed = parse_render_build_receipt_v4(value.document_json)
    if not same_wire_value(value, parsed):
        raise RenderBuildReceiptSchemaError("render V4 receipt was forged")
