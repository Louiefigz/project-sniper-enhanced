"""Non-authorizing semantic binding for retained headless build receipts."""

from __future__ import annotations

from dataclasses import dataclass

from .artifact_contract import ArtifactRefV1
from .compositor_build_receipt_semantics import (
    CompositorBuildReceiptSchemaError,
    CompositorBuildReceiptV1,
    validate_compositor_build_receipt_v1,
)
from .graphic_render_receipt_binding import (
    BoundGraphicRenderReceiptV1,
    GraphicRenderReceiptBindingError,
    GraphicRenderReceiptBindingV1,
    bind_graphic_render_receipts,
)
from .graphic_render_receipt_semantics import GraphicRenderReceiptV1
from .quality_evidence_manifest_binding import (
    artifact_for_bytes,
    same_artifact,
)
from .render_build_receipt_semantics import (
    RenderBuildReceiptSchemaError,
    RenderBuildReceiptV1,
    validate_render_build_receipt_v1,
)
from .runtime_capability_binding import (
    RuntimeCapabilityBindingError,
    RuntimeCapabilityBindingV1,
    bind_runtime_capability_manifest,
)

BUILD_RECEIPT_BLOCKED_STATUS = (
    "STATIC_BUILD_AND_GRAPHIC_RECEIPTS_BOUND_NOT_EXECUTION_VERIFIED"
)

__all__ = (
    "BUILD_RECEIPT_BLOCKED_STATUS",
    "BuildReceiptBindingError",
    "BuildReceiptBindingReportV1",
    "BuildReceiptBindingV1",
    "BuildReceiptRequirementV1",
    "BoundCompositorBuildReceiptV1",
    "bind_build_receipt_semantics",
    "require_build_receipt_execution_authorized",
)


class BuildReceiptBindingError(RuntimeError):
    """Build receipts contradict immutable generation or runtime claims."""


@dataclass(frozen=True)
class BuildReceiptRequirementV1:
    """One missing authority that prevents build receipt authorization."""

    code: str
    required_proof: str


@dataclass(frozen=True)
class BoundCompositorBuildReceiptV1:
    """Exact receipt artifact plus its parsed static closure identity."""

    artifact: ArtifactRefV1
    build_digest: str
    source_count: int
    semantic_status: str


@dataclass(frozen=True)
class BuildReceiptBindingV1:
    """Runtime, build, plan, admission, and graphic receipt records."""

    runtime_binding: RuntimeCapabilityBindingV1
    compositor_receipt: CompositorBuildReceiptV1
    render_receipt: RenderBuildReceiptV1
    plan_json: bytes
    graphic_receipts: tuple[GraphicRenderReceiptV1, ...]
    admission_manifest_json: bytes
    admission_request_json: bytes
    graphic_source_seal_jsons: tuple[bytes, ...]


@dataclass(frozen=True)
class BuildReceiptBindingReportV1:
    """Blocked result of all semantics the current receipts support."""

    status: str
    compositor_receipt: BoundCompositorBuildReceiptV1
    render_receipt: ArtifactRefV1
    render_build_digest: str
    graphic_receipts: tuple[BoundGraphicRenderReceiptV1, ...]
    unresolved_authority: tuple[BuildReceiptRequirementV1, ...]
    runtime_claims_bound: bool
    render_receipt_semantics_bound: bool
    compositor_receipt_semantics_bound: bool
    graphic_receipt_semantics_bound: bool
    source_bytes_reobserved: bool
    runtime_verified: bool
    execution_authorized: bool
    publication_authorized: bool


UNRESOLVED_BUILD_RECEIPT_AUTHORITY = (
    BuildReceiptRequirementV1(
        "BUILD_SOURCE_AND_TOOL_BYTES_NOT_REOBSERVED",
        "reopen retained sources/tools and compare every declared row",
    ),
    BuildReceiptRequirementV1(
        "BUILD_EXECUTION_ATTESTATION_UNAVAILABLE",
        "prove admitted builds and tools produced graphic and final media",
    ),
)


def _checked_input(value: object) -> BuildReceiptBindingV1:
    if type(value) is not BuildReceiptBindingV1:
        raise BuildReceiptBindingError("build receipt binding input is invalid")
    try:
        validate_compositor_build_receipt_v1(value.compositor_receipt)
        validate_render_build_receipt_v1(value.render_receipt)
    except (
        CompositorBuildReceiptSchemaError,
        RenderBuildReceiptSchemaError,
    ) as exc:
        raise BuildReceiptBindingError("build receipt is invalid") from exc
    return value


def _bind_runtime(value: BuildReceiptBindingV1) -> None:
    try:
        report = bind_runtime_capability_manifest(value.runtime_binding)
    except RuntimeCapabilityBindingError as exc:
        raise BuildReceiptBindingError("runtime build authority is invalid") from exc
    if not report.structural_manifest_bound or report.publication_authorized:
        raise BuildReceiptBindingError("runtime build report disposition is invalid")


def _receipt_ref(path: str, raw: bytes) -> ArtifactRefV1:
    try:
        return artifact_for_bytes(path, raw)
    except RuntimeError as exc:
        raise BuildReceiptBindingError("build receipt bytes cannot be bound") from exc


def _bind_receipt_refs(
    value: BuildReceiptBindingV1,
) -> tuple[BoundCompositorBuildReceiptV1, ArtifactRefV1]:
    runtime = value.runtime_binding.runtime_manifest
    compositor_expected = runtime.compositor_build.artifact
    compositor = _receipt_ref(
        compositor_expected.relative_path,
        value.compositor_receipt.document_json,
    )
    render_expected = runtime.render_build.artifact
    render = _receipt_ref(
        render_expected.relative_path, value.render_receipt.document_json
    )
    if not same_artifact(compositor, compositor_expected):
        raise BuildReceiptBindingError("compositor build receipt bytes are stale")
    if not same_artifact(render, render_expected):
        raise BuildReceiptBindingError("render build receipt bytes are stale")
    bound = BoundCompositorBuildReceiptV1(
        compositor,
        value.compositor_receipt.build_digest,
        len(value.compositor_receipt.manifest.implementation),
        "EXACT_STATIC_SOURCE_MANIFEST_BOUND",
    )
    return bound, render


def _bind_render_claims(value: BuildReceiptBindingV1) -> str:
    receipt = value.render_receipt
    runtime = value.runtime_binding.runtime_manifest
    descriptor = value.runtime_binding.descriptor
    expected = runtime.render_build.build_digest
    claimed = tuple(asset.render_build_digest for asset in descriptor.graphics.assets)
    if receipt.build_digest != expected or not claimed:
        raise BuildReceiptBindingError("render build digest is stale")
    if any(digest != receipt.build_digest for digest in claimed):
        raise BuildReceiptBindingError("graphic render build digest is stale")
    tools = {row.label: row.sha256 for row in receipt.manifest.tools}
    expected_tools = (runtime.ffmpeg.sha256, runtime.ffprobe.sha256)
    if (tools["proof-ffmpeg"], tools["proof-ffprobe"]) != expected_tools:
        raise BuildReceiptBindingError("render proof tool identities are stale")
    return receipt.build_digest


def _bind_compositor_claims(value: BuildReceiptBindingV1) -> None:
    runtime = value.runtime_binding.runtime_manifest
    assembly = value.runtime_binding.assembly_receipt
    receipt = value.compositor_receipt
    identities = (
        receipt.build_digest,
        runtime.compositor_build.build_digest,
        assembly.compositor.build_digest,
    )
    if len(set(identities)) != 1:
        raise BuildReceiptBindingError("compositor build digest is stale")


def _bind_graphics(
    value: BuildReceiptBindingV1,
) -> tuple[BoundGraphicRenderReceiptV1, ...]:
    graphic_input = GraphicRenderReceiptBindingV1(
        value.runtime_binding,
        value.render_receipt,
        value.plan_json,
        value.graphic_receipts,
        value.admission_manifest_json,
        value.admission_request_json,
        value.graphic_source_seal_jsons,
    )
    try:
        report = bind_graphic_render_receipts(graphic_input)
    except GraphicRenderReceiptBindingError as exc:
        raise BuildReceiptBindingError(
            "graphic render receipt authority is invalid"
        ) from exc
    invalid = report.execution_authorized or report.publication_authorized
    if invalid or not report.receipt_artifacts_bound:
        raise BuildReceiptBindingError("graphic render receipt disposition is invalid")
    return report.receipts


def bind_build_receipt_semantics(value: object) -> BuildReceiptBindingReportV1:
    """Bind both static build receipts without granting execution authority."""
    checked = _checked_input(value)
    _bind_runtime(checked)
    compositor, render = _bind_receipt_refs(checked)
    render_digest = _bind_render_claims(checked)
    _bind_compositor_claims(checked)
    graphics = _bind_graphics(checked)
    return BuildReceiptBindingReportV1(
        BUILD_RECEIPT_BLOCKED_STATUS,
        compositor,
        render,
        render_digest,
        graphics,
        UNRESOLVED_BUILD_RECEIPT_AUTHORITY,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
    )


def require_build_receipt_execution_authorized(value: object) -> None:
    """Keep the current blocked receipt slice outside every execution gate."""
    raise BuildReceiptBindingError(BUILD_RECEIPT_BLOCKED_STATUS)
