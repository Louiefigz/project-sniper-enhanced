"""Exact non-authorizing runtime capability manifest for deterministic MP4 R0."""

from __future__ import annotations

from dataclasses import dataclass

from . import quality_receipt_json as wire
from .artifact_contract import ArtifactRefV1

RuntimeCapabilitySchemaError = wire.QualityReceiptSchemaError

_TOP_KEYS = frozenset(
    "builds closure qualityPolicyId realizationKind requestDigest schemaVersion "
    "status tools".split()
)
_TOOL_SET_KEYS = frozenset("ffmpeg ffprobe".split())
_TOOL_KEYS = frozenset("roles sha256".split())
_BUILD_SET_KEYS = frozenset("compositor render".split())
_BUILD_KEYS = frozenset("artifact buildDigest".split())
_CLOSURE_KEYS = frozenset(
    "dynamicLibraryClosure executableReobservation executionAttestation "
    "staticManifest".split()
)
_FFMPEG_ROLES = (
    "compositor",
    "full-decode",
    "effect-proof",
    "audit-b",
)
_FFPROBE_ROLES = (
    "media-probe",
    "full-decode-counts",
    "effect-proof",
    "audit-b",
)


@dataclass(frozen=True)
class RuntimeToolCapabilityV1:
    """One declared executable hash and its closed semantic roles."""

    sha256: str
    roles: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeBuildCapabilityV1:
    """One build identity and its exact generation-manifest receipt ref."""

    artifact: ArtifactRefV1
    build_digest: str


@dataclass(frozen=True)
class RuntimeClosureDispositionV1:
    """Claims intentionally unavailable from the current structural card."""

    static_manifest: str
    executable_reobservation: str
    dynamic_library_closure: str
    execution_attestation: str


@dataclass(frozen=True)
class RuntimeCapabilityManifestV1:
    """Canonical declared runtime/build closure without execution authority."""

    request_digest: str
    quality_policy_id: str
    ffmpeg: RuntimeToolCapabilityV1
    ffprobe: RuntimeToolCapabilityV1
    compositor_build: RuntimeBuildCapabilityV1
    render_build: RuntimeBuildCapabilityV1
    closure: RuntimeClosureDispositionV1
    document_json: bytes


def _tool(value: object, roles: tuple[str, ...]) -> RuntimeToolCapabilityV1:
    row = wire.exact(value, _TOOL_KEYS, "runtime tool capability")
    actual_roles = row["roles"]
    if type(actual_roles) is not list or actual_roles != list(roles):
        raise RuntimeCapabilitySchemaError("runtime tool roles are invalid")
    return RuntimeToolCapabilityV1(
        wire.digest(row["sha256"], "runtime tool digest"), roles
    )


def _tools(value: object) -> tuple[RuntimeToolCapabilityV1, ...]:
    row = wire.exact(value, _TOOL_SET_KEYS, "runtime tool set")
    ffmpeg = _tool(row["ffmpeg"], _FFMPEG_ROLES)
    ffprobe = _tool(row["ffprobe"], _FFPROBE_ROLES)
    if ffmpeg.sha256 == ffprobe.sha256:
        raise RuntimeCapabilitySchemaError("runtime tool byte roles alias")
    return ffmpeg, ffprobe


def _build(value: object, label: str) -> RuntimeBuildCapabilityV1:
    row = wire.exact(value, _BUILD_KEYS, f"{label} build capability")
    return RuntimeBuildCapabilityV1(
        wire.artifact(row["artifact"]),
        wire.digest(row["buildDigest"], f"{label} build digest"),
    )


def _builds(value: object) -> tuple[RuntimeBuildCapabilityV1, ...]:
    row = wire.exact(value, _BUILD_SET_KEYS, "runtime build set")
    compositor = _build(row["compositor"], "compositor")
    render = _build(row["render"], "render")
    refs = (compositor.artifact, render.artifact)
    valid = len({ref.relative_path for ref in refs}) == 2
    valid = valid and len({ref.sha256 for ref in refs}) == 2
    valid = valid and compositor.build_digest != render.build_digest
    if not valid:
        raise RuntimeCapabilitySchemaError("runtime build roles alias")
    return compositor, render


def _closure(value: object) -> RuntimeClosureDispositionV1:
    row = wire.exact(value, _CLOSURE_KEYS, "runtime closure disposition")
    actual = (
        row["staticManifest"],
        row["executableReobservation"],
        row["dynamicLibraryClosure"],
        row["executionAttestation"],
    )
    expected = ("declared", "not-proved", "not-proved", "not-proved")
    if actual != expected:
        raise RuntimeCapabilitySchemaError("runtime closure overclaims authority")
    return RuntimeClosureDispositionV1(*actual)


def parse_runtime_capability_manifest_v1(raw: object) -> RuntimeCapabilityManifestV1:
    """Parse only the closed canonical non-authorizing R0 runtime card."""
    document = wire.canonical_document(raw, "runtime capability manifest")
    wire.exact(document, _TOP_KEYS, "runtime capability manifest")
    envelope = (
        type(document["schemaVersion"]),
        document["schemaVersion"],
        document["status"],
        document["realizationKind"],
    )
    if envelope != (int, 1, "declared-not-runtime-verified", "deterministic-mp4"):
        raise RuntimeCapabilitySchemaError("runtime capability envelope is invalid")
    ffmpeg, ffprobe = _tools(document["tools"])
    compositor, render = _builds(document["builds"])
    role_digests = {
        ffmpeg.sha256,
        ffprobe.sha256,
        compositor.artifact.sha256,
        render.artifact.sha256,
        compositor.build_digest,
        render.build_digest,
    }
    if len(role_digests) != 6:
        raise RuntimeCapabilitySchemaError("runtime digest roles alias")
    return RuntimeCapabilityManifestV1(
        wire.digest(document["requestDigest"], "runtime request digest"),
        wire.digest(document["qualityPolicyId"], "runtime quality policy ID"),
        ffmpeg,
        ffprobe,
        compositor,
        render,
        _closure(document["closure"]),
        raw,
    )


def validate_runtime_capability_manifest_v1(value: object) -> None:
    """Reject direct construction, hostile equality, and non-current bytes."""
    valid = type(value) is RuntimeCapabilityManifestV1
    valid = valid and type(getattr(value, "document_json", None)) is bytes
    if not valid:
        raise RuntimeCapabilitySchemaError("runtime capability instance is invalid")
    parsed = parse_runtime_capability_manifest_v1(value.document_json)
    if not wire.same_typed_value(value, parsed):
        raise RuntimeCapabilitySchemaError("runtime capability construction is invalid")
