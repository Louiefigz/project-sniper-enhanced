"""Types for the attempt-owned graphic render receipt set store."""

from __future__ import annotations

from dataclasses import dataclass

from .graphic_render_receipt_semantics import GraphicRenderReceiptV1

GRAPHIC_RECEIPT_SET_STATUS = (
    "GRAPHIC_RENDER_RECEIPTS_RETAINED_NOT_EXECUTION_AUTHORIZED"
)


class GraphicRenderReceiptStoreError(RuntimeError):
    """Retained graphic receipt bytes are absent, stale, or unsafe."""


@dataclass(frozen=True)
class GraphicRenderReceiptExpectedV1:
    """One receipt identity derived from retained admission source bytes."""

    ordinal: int
    graphic_id: str
    kind: str
    render_intent_digest: str
    render_input_key: str
    source_snapshot_sha256: str


@dataclass(frozen=True)
class GraphicRenderReceiptSetExpectationV1:
    """Controller-derived shared authority for one complete receipt set."""

    authority_id: str
    attempt_id: str
    admission_artifact_digest: str
    request_digest: str
    quality_policy_id: str
    render_build_digest: str
    runtime_image_id: str
    proof_ffmpeg_sha256: str
    proof_ffprobe_sha256: str
    receipts: tuple[GraphicRenderReceiptExpectedV1, ...]


@dataclass(frozen=True)
class GraphicRenderReceiptSetLocatorV1:
    """Path-free identity for one atomically retained receipt set."""

    manifest_sha256: str
    receipt_count: int


@dataclass(frozen=True)
class StoredGraphicRenderReceiptSetV1:
    """Reparsed retained receipts plus whether an existing set was replayed."""

    locator: GraphicRenderReceiptSetLocatorV1
    receipts: tuple[GraphicRenderReceiptV1, ...]
    replayed: bool


@dataclass(frozen=True)
class AdmittedGraphicRenderReceiptOutcomeV1:
    """Path-free non-authorizing controller result."""

    status: str
    locator: GraphicRenderReceiptSetLocatorV1
    receipts: tuple[GraphicRenderReceiptV1, ...]
    replayed: bool
    receipt_bytes_retained: bool
    admission_bound: bool
    source_records_bound: bool
    build_bound: bool
    media_bytes_reobserved: bool
    execution_attested: bool
    execution_authorized: bool
    publication_authorized: bool
