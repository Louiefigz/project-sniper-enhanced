"""Small attempt-owned fixture for graphic receipt store tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from _build_receipt_semantics_fixture import build_receipt_fixture
from headless.graphic_render_receipt_semantics import GraphicRenderReceiptV1
from headless.graphic_render_receipt_store_types import (
    GraphicRenderReceiptExpectedV1,
    GraphicRenderReceiptSetExpectationV1,
)

ATTEMPT = "22222222-2222-4222-8222-222222222222"


@dataclass(frozen=True)
class GraphicReceiptStoreFixtureV1:
    """One private attempt plus a matching receipt and set expectation."""

    attempt_root: str
    expectation: GraphicRenderReceiptSetExpectationV1
    receipt: GraphicRenderReceiptV1


def graphic_receipt_store_fixture(root: Path) -> GraphicReceiptStoreFixtureV1:
    """Create an empty private attempt and derive expectation from real bytes."""
    attempt = root / "attempt"
    attempt.mkdir(mode=0o700)
    (attempt / "work").mkdir(mode=0o700)
    value = build_receipt_fixture()
    receipt = value.graphic_receipts[0]
    row = GraphicRenderReceiptExpectedV1(
        receipt.ordinal,
        receipt.graphic_id,
        receipt.kind,
        receipt.render_intent_digest,
        receipt.render_input_key,
        receipt.source_snapshot_sha256,
    )
    expectation = GraphicRenderReceiptSetExpectationV1(
        "authority-mp4-v1",
        ATTEMPT,
        receipt.admission_artifact_digest,
        receipt.request_digest,
        receipt.quality_policy_id,
        receipt.render_build_digest,
        receipt.runtime_image_id,
        receipt.tools.ffmpeg_sha256,
        receipt.tools.ffprobe_sha256,
        (row,),
    )
    return GraphicReceiptStoreFixtureV1(str(attempt), expectation, receipt)
