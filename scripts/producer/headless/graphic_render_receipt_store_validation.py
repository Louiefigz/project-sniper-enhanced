"""Exact receipt-to-controller expectation checks for the private store."""

from __future__ import annotations

from .graphic_render_receipt_semantics import (
    GraphicRenderReceiptSchemaError,
    GraphicRenderReceiptV1,
    validate_graphic_render_receipt_v1,
)
from .graphic_render_receipt_set_manifest import validate_expectation
from .graphic_render_receipt_store_types import (
    GraphicRenderReceiptSetExpectationV1,
    GraphicRenderReceiptStoreError,
)


def receipt_matches(
    receipt: GraphicRenderReceiptV1,
    expected: GraphicRenderReceiptSetExpectationV1,
    index: int,
) -> None:
    """Bind one parsed receipt to its exact ordered controller expectation."""
    row = expected.receipts[index]
    actual = (
        receipt.ordinal,
        receipt.graphic_id,
        receipt.selection_id,
        receipt.kind,
        receipt.admission_artifact_digest,
        receipt.request_digest,
        receipt.quality_policy_id,
        receipt.render_build_digest,
        receipt.runtime_image_id,
        receipt.tools.ffmpeg_sha256,
        receipt.tools.ffprobe_sha256,
        receipt.render_intent_digest,
        receipt.render_input_key,
        receipt.source_snapshot_sha256,
        receipt.media.artifact.relative_path,
    )
    wanted = (
        index,
        row.graphic_id,
        row.graphic_id,
        row.kind,
        expected.admission_artifact_digest,
        expected.request_digest,
        expected.quality_policy_id,
        expected.render_build_digest,
        expected.runtime_image_id,
        expected.proof_ffmpeg_sha256,
        expected.proof_ffprobe_sha256,
        row.render_intent_digest,
        row.render_input_key,
        row.source_snapshot_sha256,
        f"graphics/{row.graphic_id}.mov",
    )
    if actual != wanted:
        raise GraphicRenderReceiptStoreError(
            "graphic receipt identity is stale"
        )


def checked_receipts(
    receipts: object, expectation: GraphicRenderReceiptSetExpectationV1
) -> tuple[GraphicRenderReceiptV1, ...]:
    """Reject direct receipt construction, stale order, and count drift."""
    checked = validate_expectation(expectation)
    if type(receipts) is not tuple or len(receipts) != len(checked.receipts):
        raise GraphicRenderReceiptStoreError(
            "graphic receipt set count is stale"
        )
    for index, receipt in enumerate(receipts):
        try:
            validate_graphic_render_receipt_v1(receipt)
        except GraphicRenderReceiptSchemaError as exc:
            raise GraphicRenderReceiptStoreError(
                "graphic receipt set contains invalid bytes"
            ) from exc
        receipt_matches(receipt, checked, index)
    return receipts
