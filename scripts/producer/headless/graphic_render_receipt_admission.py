"""Bind graphic receipts to exact pre-admission manifest and source seals."""

from __future__ import annotations

import hashlib

from . import quality_receipt_json as wire
from .graphic_render_receipt_binding_types import (
    CheckedGraphicRenderBindingV1,
    GraphicRenderReceiptBindingError,
)
from .graphic_render_source_semantics import validate_graphic_source_semantics
from .overlay_source_seal import (
    effective_render_intent,
    render_intents_equal,
)
from .quality_evidence_manifest_binding import (
    artifact_for_bytes,
    same_artifact,
)
from .request_artifact import (
    canonical_request_document,
    decode_request_document,
)

_MAX_BYTES = 8 * 1024 * 1024
_MANIFEST_KEYS = frozenset(
    "buildDigest files operation requestDocumentDigest schemaVersion".split()
)
_FILE_KEYS = frozenset("mode path sha256 sizeBytes".split())
_SOURCE_KEYS = frozenset(
    "buildDigest composition compositionHtml expectedAssetBindings expectedCopy "
    "expectedDimensions expectedFormat expectedKey extension intent schemaVersion "
    "selectionId snapshotManifest snapshotSha256 sourceCompositionSha256".split()
)


def _document(raw: object, label: str) -> dict:
    if type(raw) is not bytes or not 1 < len(raw) <= _MAX_BYTES:
        raise GraphicRenderReceiptBindingError(f"{label} bytes are invalid")
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise GraphicRenderReceiptBindingError(f"{label} framing is invalid")
    try:
        return wire.canonical_document(raw[:-1], label)
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        raise GraphicRenderReceiptBindingError(f"{label} is invalid") from exc


def _artifact_digest(raw: bytes) -> str:
    return hashlib.sha256(b"sniper-render-admission-artifact-v1\0" + raw).hexdigest()


def _selection_directory(selection_id: str) -> str:
    return hashlib.sha256(
        b"sniper-render-selection-v1\0" + selection_id.encode("ascii")
    ).hexdigest()


def _render_key(snapshot: str, build: str) -> str:
    material = snapshot.encode("ascii") + b"\0" + build.encode("ascii")
    return hashlib.sha256(b"sniper-overlay-key-v2\0" + material).hexdigest()


def _manifest_rows(value: object) -> dict[str, dict]:
    if type(value) is not list:
        raise GraphicRenderReceiptBindingError("render admission file rows are invalid")
    rows = tuple(value)
    valid = all(_valid_manifest_row(row) for row in rows)
    paths = tuple(row["path"] for row in rows) if valid else ()
    valid = valid and paths == tuple(sorted(paths))
    valid = valid and len(paths) == len(set(paths))
    if not valid:
        raise GraphicRenderReceiptBindingError("render admission file rows are invalid")
    return {row["path"]: row for row in rows}


def _valid_manifest_row(value: object) -> bool:
    if type(value) is not dict or set(value) != _FILE_KEYS:
        return False
    valid = type(value["path"]) is str and bool(value["path"])
    valid = valid and type(value["mode"]) is int and value["mode"] >= 0
    valid = valid and type(value["sizeBytes"]) is int and value["sizeBytes"] >= 0
    try:
        wire.digest(value["sha256"], "render admission file")
    except RuntimeError:
        return False
    return valid


def _manifest(
    value: CheckedGraphicRenderBindingV1, groups: dict
) -> tuple[dict, dict[str, dict], str]:
    raw = value.admission_manifest_json
    document = _document(raw, "render admission manifest")
    if set(document) != _MANIFEST_KEYS:
        raise GraphicRenderReceiptBindingError(
            "render admission manifest keys are invalid"
        )
    actual = (
        type(document["schemaVersion"]),
        document["schemaVersion"],
        document["operation"],
        document["buildDigest"],
    )
    expected = (int, 1, "render-overlays", value.build.build_digest)
    if actual != expected:
        raise GraphicRenderReceiptBindingError(
            "render admission manifest identity is stale"
        )
    try:
        wire.digest(document["requestDocumentDigest"], "render admission request")
    except RuntimeError as exc:
        raise GraphicRenderReceiptBindingError(
            "render admission request identity is invalid"
        ) from exc
    rows = _manifest_rows(document["files"])
    descriptor_ref = value.runtime.descriptor.provenance.admission_inputs
    observed = artifact_for_bytes(descriptor_ref.relative_path, raw)
    manifest_rows = groups.get("admission-inputs-v1", ())
    manifest_refs = {(row.path, row.sha256, row.size_bytes) for row in manifest_rows}
    if (
        not same_artifact(observed, descriptor_ref)
        or (
            observed.relative_path,
            observed.sha256,
            observed.size_bytes,
        )
        not in manifest_refs
    ):
        raise GraphicRenderReceiptBindingError(
            "render admission manifest bytes are stale"
        )
    return document, rows, _artifact_digest(raw)


def _source_row(rows: dict[str, dict], selection_id: str) -> dict:
    child = _selection_directory(selection_id)
    path = f"overlays/{child}/source-seal.json"
    row = rows.get(path)
    if row is None:
        raise GraphicRenderReceiptBindingError(
            "graphic source seal is absent from admission manifest"
        )
    return row


def _bind_request(
    value: CheckedGraphicRenderBindingV1,
    manifest: dict,
    rows: dict[str, dict],
    plan_rows: tuple[dict, ...],
) -> None:
    expected = {
        "schemaVersion": 1,
        "operation": "render-overlays",
        "overlays": [
            {"overlayId": receipt.selection_id, "entry": plan_row}
            for receipt, plan_row in zip(value.receipts, plan_rows)
        ],
    }
    try:
        request = decode_request_document(value.admission_request_json)
        _frozen, expected_raw, digest = canonical_request_document(expected)
    except RuntimeError as exc:
        raise GraphicRenderReceiptBindingError(
            "render admission request is invalid"
        ) from exc
    row = rows.get("request.json") or {}
    observed = (
        0o600,
        len(value.admission_request_json),
        hashlib.sha256(value.admission_request_json).hexdigest(),
    )
    claimed = (row.get("mode"), row.get("sizeBytes"), row.get("sha256"))
    valid = request == expected and value.admission_request_json == expected_raw
    valid = valid and manifest["requestDocumentDigest"] == digest
    if not valid or observed != claimed:
        raise GraphicRenderReceiptBindingError(
            "render admission request differs from approved plan"
        )


def _bind_render_build(value: CheckedGraphicRenderBindingV1, rows: dict) -> None:
    raw = value.build.document_json
    row = rows.get("render-build.json") or {}
    observed = (0o600, len(raw), hashlib.sha256(raw).hexdigest())
    claimed = (row.get("mode"), row.get("sizeBytes"), row.get("sha256"))
    if observed != claimed:
        raise GraphicRenderReceiptBindingError(
            "render admission build receipt bytes are stale"
        )


def _source_identity(
    value: CheckedGraphicRenderBindingV1,
    source: dict,
    index: int,
    snapshot: str,
) -> bool:
    receipt = value.receipts[index]
    expected_key = _render_key(snapshot, value.build.build_digest)
    actual = (
        type(source.get("schemaVersion")),
        source.get("schemaVersion"),
        source.get("selectionId"),
        source.get("buildDigest"),
        source.get("expectedFormat"),
        source.get("extension"),
        source.get("expectedKey"),
        receipt.render_input_key,
        receipt.source_snapshot_sha256,
    )
    expected = (
        int,
        1,
        receipt.selection_id,
        value.build.build_digest,
        "mov",
        "mov",
        expected_key,
        expected_key,
        snapshot,
    )
    return actual == expected


def _bind_source(
    value: CheckedGraphicRenderBindingV1,
    rows: dict[str, dict],
    plan_row: dict,
    index: int,
) -> None:
    receipt = value.receipts[index]
    raw = value.source_seal_jsons[index]
    source = _document(raw, "graphic source seal")
    manifest_row = _source_row(rows, receipt.selection_id)
    observed = (0o600, len(raw), hashlib.sha256(raw).hexdigest())
    expected = (
        manifest_row["mode"],
        manifest_row["sizeBytes"],
        manifest_row["sha256"],
    )
    if observed != expected or set(source) != _SOURCE_KEYS:
        raise GraphicRenderReceiptBindingError("graphic source seal bytes are stale")
    try:
        snapshot = wire.digest(source.get("snapshotSha256"), "graphic source snapshot")
        validate_graphic_source_semantics(source, plan_row, receipt.media)
        intent_matches = render_intents_equal(
            source["intent"], effective_render_intent(plan_row)
        )
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        raise GraphicRenderReceiptBindingError(
            "graphic source intent is invalid"
        ) from exc
    if not intent_matches or not _source_identity(value, source, index, snapshot):
        raise GraphicRenderReceiptBindingError(
            "graphic receipt source identity is stale"
        )
    tar_path = manifest_row["path"].replace("source-seal.json", "render-input.tar")
    tar = rows.get(tar_path) or {}
    tar_identity = (tar.get("mode"), tar.get("sha256"), tar.get("sizeBytes"))
    if tar_identity[:2] != (0o400, snapshot) or not (
        type(tar_identity[2]) is int and tar_identity[2] > 0
    ):
        raise GraphicRenderReceiptBindingError("graphic source snapshot row is stale")


def bind_graphic_admission_evidence(
    value: CheckedGraphicRenderBindingV1,
    groups: dict,
    plan_rows: tuple[dict, ...],
) -> None:
    """Bind admitted manifest, ordered source seals, snapshot, and render key."""
    if len(value.source_seal_jsons) != len(plan_rows):
        raise GraphicRenderReceiptBindingError("graphic source seal count is stale")
    manifest, rows, admission_digest = _manifest(value, groups)
    _bind_request(value, manifest, rows, plan_rows)
    _bind_render_build(value, rows)
    if any(
        receipt.admission_artifact_digest != admission_digest
        for receipt in value.receipts
    ):
        raise GraphicRenderReceiptBindingError(
            "graphic receipt admission artifact is stale"
        )
    for index, plan_row in enumerate(plan_rows):
        _bind_source(value, rows, plan_row, index)
    expected_paths = {"request.json", "render-build.json"}
    expected_paths.update(
        f"overlays/{_selection_directory(receipt.selection_id)}/{name}"
        for receipt in value.receipts
        for name in ("render-input.tar", "source-seal.json")
    )
    if set(rows) != expected_paths:
        raise GraphicRenderReceiptBindingError(
            "render admission manifest closure is not exact"
        )
