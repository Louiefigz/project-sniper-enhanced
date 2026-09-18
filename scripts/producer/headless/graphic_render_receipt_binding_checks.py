"""Exact cross-checks used by graphic render receipt binding."""

from __future__ import annotations

from fingerprints import base_plan_digest, plan_content_hash

from . import quality_receipt_json as wire
from .artifact_contract import ArtifactRefV1
from .generation_profile import verify_r0_generation_profile
from .graphic_render_receipt_binding_types import (
    BoundGraphicRenderReceiptV1,
    CheckedGraphicRenderBindingV1,
    GraphicRenderReceiptBindingError,
    GraphicRenderReceiptBindingV1,
)
from .graphic_render_receipt_semantics import (
    GraphicRenderReceiptSchemaError,
    validate_graphic_render_receipt_v1,
)
from .quality_evidence_manifest_binding import (
    artifact_for_bytes,
    same_artifact,
)
from .quality_pass_contract import graphic_render_intent_digest
from .render_build_receipt_semantics import (
    RenderBuildReceiptSchemaError,
    validate_render_build_receipt_v1,
)
from .repair_intent import approved_plan_digest
from .runtime_capability_binding import (
    RuntimeCapabilityBindingError,
    bind_runtime_capability_manifest,
)
from .runtime_capability_binding_inputs import (
    RuntimeCapabilityInputError,
    checked_runtime_capability,
)


def checked_binding(value: object) -> CheckedGraphicRenderBindingV1:
    """Reparse the entire upstream graph before comparing any fields."""
    if type(value) is not GraphicRenderReceiptBindingV1:
        raise GraphicRenderReceiptBindingError(
            "graphic receipt binding input is invalid"
        )
    exact_types = (
        type(value.plan_json) is bytes,
        type(value.receipts) is tuple,
        type(value.admission_manifest_json) is bytes,
        type(value.admission_request_json) is bytes,
        type(value.source_seal_jsons) is tuple,
    )
    if not all(exact_types):
        raise GraphicRenderReceiptBindingError(
            "graphic receipt binding values are invalid"
        )
    if not value.receipts:
        raise GraphicRenderReceiptBindingError("graphic receipt set is empty")
    try:
        report = bind_runtime_capability_manifest(value.runtime_binding)
        runtime = checked_runtime_capability(value.runtime_binding)
        validate_render_build_receipt_v1(value.render_build_receipt)
        for receipt in value.receipts:
            validate_graphic_render_receipt_v1(receipt)
    except (
        GraphicRenderReceiptSchemaError,
        RenderBuildReceiptSchemaError,
        RuntimeCapabilityBindingError,
        RuntimeCapabilityInputError,
    ) as exc:
        raise GraphicRenderReceiptBindingError(
            "graphic receipt upstream authority is invalid"
        ) from exc
    if not report.structural_manifest_bound or report.publication_authorized:
        raise GraphicRenderReceiptBindingError(
            "graphic receipt runtime disposition is invalid"
        )
    return CheckedGraphicRenderBindingV1(
        runtime,
        value.render_build_receipt,
        value.plan_json,
        value.receipts,
        value.admission_manifest_json,
        value.admission_request_json,
        value.source_seal_jsons,
    )


def _require_ref(ref: ArtifactRefV1, artifact_class: str, groups: dict) -> None:
    matches = tuple(
        row
        for row in groups.get(artifact_class, ())
        if (row.path, row.sha256, row.size_bytes)
        == (ref.relative_path, ref.sha256, ref.size_bytes)
    )
    if len(matches) != 1:
        raise GraphicRenderReceiptBindingError(
            f"graphic receipt role {artifact_class} is stale"
        )


def _plan(value: CheckedGraphicRenderBindingV1, groups: dict) -> dict:
    try:
        document = wire.canonical_document(value.plan_json, "graphic receipt plan")
        descriptor = value.runtime.descriptor
        actual = artifact_for_bytes(
            descriptor.plan.artifact.relative_path, value.plan_json
        )
        identities = (
            approved_plan_digest(document),
            plan_content_hash(document),
            base_plan_digest(document),
        )
    except RuntimeError as exc:
        raise GraphicRenderReceiptBindingError(
            "graphic receipt plan is invalid"
        ) from exc
    expected = (
        descriptor.plan.approved_plan_digest,
        descriptor.plan.content_hash,
        descriptor.plan.base_projection_digest,
    )
    if identities != expected or not same_artifact(actual, descriptor.plan.artifact):
        raise GraphicRenderReceiptBindingError("graphic receipt plan identity is stale")
    _require_ref(actual, "plan-v1", groups)
    return document


def plan_rows(
    value: CheckedGraphicRenderBindingV1,
) -> tuple[dict, tuple[dict, ...]]:
    """Return verified commit groups and exact ordered plan rows."""
    try:
        groups = dict(verify_r0_generation_profile(value.runtime.commit))
    except RuntimeError as exc:
        raise GraphicRenderReceiptBindingError(
            "graphic receipt commit profile is invalid"
        ) from exc
    plan = _plan(value, groups)
    rows = plan.get("graphicsTrack") if type(plan) is dict else None
    if type(rows) is not list or len(rows) != len(value.receipts) or not rows:
        raise GraphicRenderReceiptBindingError(
            "graphic receipt count differs from approved plan"
        )
    if any(type(row) is not dict for row in rows):
        raise GraphicRenderReceiptBindingError("approved graphic rows are invalid")
    identities = tuple(row.get("id") for row in rows)
    if len(identities) != len(set(identities)):
        raise GraphicRenderReceiptBindingError("approved graphic identities alias")
    return groups, tuple(rows)


def _receipt_ref(
    value: CheckedGraphicRenderBindingV1, index: int, groups: dict
) -> ArtifactRefV1:
    descriptor_asset = value.runtime.descriptor.graphics.assets[index]
    assembly_asset = value.runtime.assembly.assets[index]
    expected = descriptor_asset.receipt
    raw = value.receipts[index].document_json
    actual = artifact_for_bytes(expected.relative_path, raw)
    valid = same_artifact(actual, expected)
    valid = valid and same_artifact(actual, assembly_asset.receipt)
    if not valid:
        raise GraphicRenderReceiptBindingError("graphic render receipt bytes are stale")
    _require_ref(actual, "graphic-render-receipt-v1", groups)
    return actual


def _identity(value: CheckedGraphicRenderBindingV1, row: dict, index: int) -> None:
    receipt = value.receipts[index]
    asset = value.runtime.descriptor.graphics.assets[index]
    assembly = value.runtime.assembly.assets[index]
    try:
        intent = graphic_render_intent_digest(row)
    except RuntimeError as exc:
        raise GraphicRenderReceiptBindingError(
            "graphic render plan intent is invalid"
        ) from exc
    expected = (
        index,
        row.get("id"),
        row.get("kind"),
        row.get("id"),
        value.runtime.runtime.request_digest,
        value.runtime.runtime.quality_policy_id,
        intent,
    )
    actual = (
        receipt.ordinal,
        receipt.graphic_id,
        receipt.kind,
        receipt.selection_id,
        receipt.request_digest,
        receipt.quality_policy_id,
        receipt.render_intent_digest,
    )
    external = (
        asset.graphic_id,
        asset.render_intent_digest,
        assembly.graphic_id,
        assembly.render_intent_digest,
    )
    if actual != expected or external != (row.get("id"), intent) * 2:
        raise GraphicRenderReceiptBindingError(
            "graphic render receipt intent is stale or reordered"
        )


def _media_and_build(value: CheckedGraphicRenderBindingV1, index: int) -> None:
    receipt = value.receipts[index]
    asset = value.runtime.descriptor.graphics.assets[index]
    assembly = value.runtime.assembly.assets[index]
    same_media = wire.same_typed_value(receipt.media, asset.media)
    same_media = same_media and wire.same_typed_value(receipt.media, assembly.media)
    artifact = receipt.media.artifact.sha256
    media_digests = (
        receipt.render_artifact_digest,
        asset.render_artifact_digest,
        assembly.render_artifact_digest,
    )
    build_digests = (
        receipt.render_build_digest,
        asset.render_build_digest,
        assembly.render_build_digest,
        value.runtime.runtime.render_build.build_digest,
        value.build.build_digest,
    )
    if not same_media or media_digests != (artifact,) * 3:
        raise GraphicRenderReceiptBindingError("graphic render media is stale")
    if len(set(build_digests)) != 1:
        raise GraphicRenderReceiptBindingError("graphic render build is stale")


def _tools_and_image(value: CheckedGraphicRenderBindingV1, index: int) -> None:
    receipt = value.receipts[index]
    rows = {row.label: row.sha256 for row in value.build.manifest.tools}
    actual = (
        receipt.runtime_image_id,
        receipt.tools.ffmpeg_sha256,
        receipt.tools.ffprobe_sha256,
    )
    expected = (
        value.build.manifest.image_id,
        rows["proof-ffmpeg"],
        rows["proof-ffprobe"],
    )
    runtime_tools = (
        value.runtime.runtime.ffmpeg.sha256,
        value.runtime.runtime.ffprobe.sha256,
    )
    if actual != expected or actual[1:] != runtime_tools:
        raise GraphicRenderReceiptBindingError(
            "graphic render proof tools or image are stale"
        )


def bind_one(
    value: CheckedGraphicRenderBindingV1,
    row: dict,
    index: int,
    groups: dict,
) -> BoundGraphicRenderReceiptV1:
    """Bind one receipt at its exact plan/asset ordinal."""
    _identity(value, row, index)
    _media_and_build(value, index)
    _tools_and_image(value, index)
    artifact = _receipt_ref(value, index, groups)
    receipt = value.receipts[index]
    return BoundGraphicRenderReceiptV1(
        index,
        receipt.graphic_id,
        receipt.selection_id,
        artifact,
        receipt.media,
        receipt.admission_artifact_digest,
        receipt.render_intent_digest,
        receipt.render_input_key,
        receipt.source_snapshot_sha256,
        receipt.render_build_digest,
    )
