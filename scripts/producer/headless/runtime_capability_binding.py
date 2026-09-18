"""Structural binding for runtime, tool, build, assembly, and QC evidence claims."""

from __future__ import annotations

from dataclasses import dataclass

from .approved_parent_assembly_binding import bind_approved_parent_assembly_receipt
from .approved_parent_binding import validate_descriptor_identity
from .artifact_contract import ArtifactRefV1
from .generation_profile import verify_r0_generation_profile
from .quality_evidence_manifest_binding import artifact_for_bytes, same_artifact
from .quality_receipt_json import same_typed_value
from .runtime_capability_binding_inputs import (
    CheckedRuntimeCapabilityV1,
    RuntimeCapabilityBindingV1 as RuntimeCapabilityBindingV1,
    RuntimeCapabilityInputError,
    checked_runtime_capability,
)

RUNTIME_STRUCTURAL_STATUS = "STRUCTURAL_RUNTIME_BOUND_NOT_EXECUTION_VERIFIED"

__all__ = (
    "RUNTIME_STRUCTURAL_STATUS",
    "RuntimeAuthorityRequirementV1",
    "RuntimeCapabilityBindingError",
    "RuntimeCapabilityBindingReportV1",
    "RuntimeCapabilityBindingV1",
    "bind_runtime_capability_manifest",
)


class RuntimeCapabilityBindingError(RuntimeError):
    """Runtime/build structural claims contradict immutable generation bytes."""


@dataclass(frozen=True)
class RuntimeAuthorityRequirementV1:
    """One runtime authority unavailable from current generation records."""

    code: str
    required_proof: str


@dataclass(frozen=True)
class RuntimeCapabilityBindingReportV1:
    """Explicitly non-authorizing result of structural runtime binding."""

    status: str
    runtime_manifest: ArtifactRefV1
    compositor_build_receipt: ArtifactRefV1
    render_build_receipt: ArtifactRefV1
    unresolved_authority: tuple[RuntimeAuthorityRequirementV1, ...]
    structural_manifest_bound: bool
    runtime_verified: bool
    execution_reobserved: bool
    dynamic_library_closure_verified: bool
    publication_authorized: bool


UNRESOLVED_RUNTIME_AUTHORITY = (
    RuntimeAuthorityRequirementV1(
        "EXECUTABLE_REOBSERVATION_AND_INODE_STABILITY",
        "open admitted ffmpeg/ffprobe before execution and prove stable bytes/inodes after",
    ),
    RuntimeAuthorityRequirementV1(
        "DYNAMIC_LIBRARY_AND_AUXILIARY_RUNTIME_CLOSURE",
        "seal and reobserve loaders, libraries, fonts, browser, models, and conditional runtimes",
    ),
    RuntimeAuthorityRequirementV1(
        "BUILD_RECEIPT_SEMANTICS",
        "parse compositor/render build receipt bytes and recompute both build digests",
    ),
    RuntimeAuthorityRequirementV1(
        "PROCESS_EXECUTION_ATTESTATION",
        "prove the exact admitted executables and builds produced each observed artifact",
    ),
    RuntimeAuthorityRequirementV1(
        "MEASUREMENT_REOBSERVATION",
        "reobserve decode, effect pixels, contrast, protected regions, Audit-B, and YDIF",
    ),
)


def _require_ref(ref: ArtifactRefV1, artifact_class: str, groups: dict) -> None:
    matches = tuple(
        row
        for row in groups.get(artifact_class, ())
        if (row.path, row.sha256, row.size_bytes)
        == (ref.relative_path, ref.sha256, ref.size_bytes)
    )
    if len(matches) != 1:
        raise RuntimeCapabilityBindingError(
            f"runtime artifact does not match class {artifact_class}"
        )


def _identity(value: CheckedRuntimeCapabilityV1) -> None:
    try:
        validate_descriptor_identity(value.descriptor, value.commit)
    except RuntimeError as exc:
        raise RuntimeCapabilityBindingError(
            "runtime generation identity is invalid"
        ) from exc
    expected = (
        value.descriptor.identity.request_digest,
        value.descriptor.policies.quality_policy_id,
    )
    identities = (
        (value.runtime.request_digest, value.runtime.quality_policy_id),
        (value.assembly.request_digest, value.assembly.quality_policy_id),
        (
            value.evidence.effect_proof.request_digest,
            value.evidence.effect_proof.quality_policy_id,
        ),
        (
            value.descriptor.identity.request_digest,
            value.evidence.full_decode.quality_policy_id,
        ),
        (
            value.descriptor.identity.request_digest,
            value.evidence.audit.quality_policy_id,
        ),
    )
    if any(identity != expected for identity in identities):
        raise RuntimeCapabilityBindingError("runtime request or policy is stale")


def _reject_role_aliases(
    value: CheckedRuntimeCapabilityV1, runtime_ref: ArtifactRefV1
) -> None:
    refs = (
        runtime_ref,
        value.runtime.compositor_build.artifact,
        value.runtime.render_build.artifact,
        value.descriptor.output.assembly_receipt,
        value.descriptor.quality.full_decode,
        value.descriptor.quality.effect_proof,
        value.descriptor.quality.audit,
    )
    paths = tuple(ref.relative_path for ref in refs)
    digests = tuple(ref.sha256 for ref in refs)
    counts = tuple(
        sum(row.sha256 == digest for row in value.commit.files) for digest in digests
    )
    if len(set(paths)) != len(paths) or len(set(digests)) != len(digests):
        raise RuntimeCapabilityBindingError("runtime artifact roles alias")
    if counts != (1,) * len(refs):
        raise RuntimeCapabilityBindingError("runtime role bytes alias manifest rows")


def _raw_roles(value: CheckedRuntimeCapabilityV1, groups: dict) -> ArtifactRefV1:
    runtime_ref = artifact_for_bytes(
        value.descriptor.provenance.runtime_capability_manifest.relative_path,
        value.runtime.document_json,
    )
    fixed = (
        (runtime_ref, "runtime-capability-manifest-v1"),
        (value.runtime.compositor_build.artifact, "compositor-build-receipt-v1"),
        (value.runtime.render_build.artifact, "render-build-receipt-v1"),
    )
    if not same_artifact(
        runtime_ref, value.descriptor.provenance.runtime_capability_manifest
    ):
        raise RuntimeCapabilityBindingError("runtime manifest bytes are stale")
    _reject_role_aliases(value, runtime_ref)
    for ref, artifact_class in fixed:
        _require_ref(ref, artifact_class, groups)
    return runtime_ref


def _evidence_roles(value: CheckedRuntimeCapabilityV1, groups: dict) -> None:
    rows = (
        (
            value.descriptor.output.assembly_receipt,
            value.assembly.document_json,
            "assembly-receipt-v1",
        ),
        (
            value.descriptor.quality.full_decode,
            value.evidence.full_decode.document_json,
            "full-decode-proof-v1",
        ),
        (
            value.descriptor.quality.effect_proof,
            value.evidence.effect_proof.document_json,
            "effect-proof-v1",
        ),
        (
            value.descriptor.quality.audit,
            value.evidence.audit.document_json,
            "audit-b-receipt-v1",
        ),
    )
    for expected, raw, artifact_class in rows:
        actual = artifact_for_bytes(expected.relative_path, raw)
        if not same_artifact(actual, expected):
            raise RuntimeCapabilityBindingError("runtime evidence bytes are stale")
        _require_ref(actual, artifact_class, groups)


def _tool_and_runtime_claims(value: CheckedRuntimeCapabilityV1) -> None:
    runtime_ref = value.descriptor.provenance.runtime_capability_manifest
    evidence = value.evidence
    runtime_refs = (
        evidence.full_decode.runtime_capability_manifest,
        evidence.effect_proof.runtime_capability_manifest,
        evidence.audit.runtime_capability_manifest,
    )
    if any(not same_artifact(ref, runtime_ref) for ref in runtime_refs):
        raise RuntimeCapabilityBindingError("quality evidence runtime ref is stale")
    expected_tools = (value.runtime.ffmpeg.sha256, value.runtime.ffprobe.sha256)
    claimed_tools = (
        (
            value.assembly.compositor.ffmpeg_sha256,
            value.assembly.compositor.ffprobe_sha256,
        ),
        (
            evidence.full_decode.tools.ffmpeg_sha256,
            evidence.full_decode.tools.ffprobe_sha256,
        ),
    )
    if any(tools != expected_tools for tools in claimed_tools):
        raise RuntimeCapabilityBindingError("runtime tool identity is stale")


def _build_claims(value: CheckedRuntimeCapabilityV1) -> None:
    expected = value.runtime.compositor_build.build_digest
    if value.assembly.compositor.build_digest != expected:
        raise RuntimeCapabilityBindingError("compositor build identity is stale")
    assets = value.assembly.assets
    descriptor_assets = value.descriptor.graphics.assets
    if not same_typed_value(assets, descriptor_assets) or len(assets) != 1:
        raise RuntimeCapabilityBindingError("runtime graphic asset set is stale")
    render_digest = value.runtime.render_build.build_digest
    if any(asset.render_build_digest != render_digest for asset in assets):
        raise RuntimeCapabilityBindingError("render build identity is stale")


def bind_runtime_capability_manifest(value: object) -> RuntimeCapabilityBindingReportV1:
    """Structurally bind runtime claims without authorizing execution/publication."""
    try:
        checked = checked_runtime_capability(value)
    except RuntimeCapabilityInputError as exc:
        raise RuntimeCapabilityBindingError(str(exc)) from exc
    _identity(checked)
    try:
        bind_approved_parent_assembly_receipt(
            checked.descriptor, checked.commit, checked.assembly
        )
        groups = dict(verify_r0_generation_profile(checked.commit))
    except RuntimeError as exc:
        raise RuntimeCapabilityBindingError(
            "runtime upstream authority is invalid"
        ) from exc
    runtime_ref = _raw_roles(checked, groups)
    _evidence_roles(checked, groups)
    _tool_and_runtime_claims(checked)
    _build_claims(checked)
    return RuntimeCapabilityBindingReportV1(
        RUNTIME_STRUCTURAL_STATUS,
        runtime_ref,
        checked.runtime.compositor_build.artifact,
        checked.runtime.render_build.artifact,
        UNRESOLVED_RUNTIME_AUTHORITY,
        True,
        False,
        False,
        False,
        False,
    )
