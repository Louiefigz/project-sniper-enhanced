"""Types for non-authorizing graphic render receipt binding."""

from __future__ import annotations

from dataclasses import dataclass

from .artifact_contract import ArtifactRefV1, MediaRefV1
from .graphic_render_receipt_semantics import GraphicRenderReceiptV1
from .render_build_receipt_semantics import RenderBuildReceiptV1
from .runtime_capability_binding import RuntimeCapabilityBindingV1
from .runtime_capability_binding_inputs import CheckedRuntimeCapabilityV1

GRAPHIC_RENDER_RECEIPT_STATUS = "GRAPHIC_RENDER_RECEIPTS_BOUND_NOT_EXECUTION_VERIFIED"


class GraphicRenderReceiptBindingError(RuntimeError):
    """Graphic receipt bytes contradict current generation authority."""


@dataclass(frozen=True)
class GraphicRenderReceiptBindingV1:
    """Current structural authority, plan bytes, and ordered receipts."""

    runtime_binding: RuntimeCapabilityBindingV1
    render_build_receipt: RenderBuildReceiptV1
    plan_json: bytes
    receipts: tuple[GraphicRenderReceiptV1, ...]
    admission_manifest_json: bytes
    admission_request_json: bytes
    source_seal_jsons: tuple[bytes, ...]


@dataclass(frozen=True)
class BoundGraphicRenderReceiptV1:
    """One receipt artifact plus externally bound stable identities."""

    ordinal: int
    graphic_id: str
    selection_id: str
    artifact: ArtifactRefV1
    media: MediaRefV1
    admission_artifact_digest: str
    render_intent_digest: str
    render_input_key: str
    source_snapshot_sha256: str
    render_build_digest: str


@dataclass(frozen=True)
class GraphicRenderReceiptBindingReportV1:
    """Narrow structural result that cannot authorize render or publication."""

    status: str
    receipts: tuple[BoundGraphicRenderReceiptV1, ...]
    plan_intents_bound: bool
    media_refs_bound: bool
    receipt_artifacts_bound: bool
    build_identity_bound: bool
    tool_identities_bound: bool
    admission_artifact_bound: bool
    source_seals_bound: bool
    render_key_bound: bool
    media_bytes_reobserved: bool
    source_snapshot_reobserved: bool
    runtime_verified: bool
    dynamic_library_closure_verified: bool
    execution_attested: bool
    execution_authorized: bool
    publication_authorized: bool


@dataclass(frozen=True)
class CheckedGraphicRenderBindingV1:
    """Reparsed upstream records safe for primitive-field comparisons."""

    runtime: CheckedRuntimeCapabilityV1
    build: RenderBuildReceiptV1
    plan_json: bytes
    receipts: tuple[GraphicRenderReceiptV1, ...]
    admission_manifest_json: bytes
    admission_request_json: bytes
    source_seal_jsons: tuple[bytes, ...]
