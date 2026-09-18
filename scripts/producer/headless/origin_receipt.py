"""Exact private receipt for a generation initialized without a parent."""

from __future__ import annotations

from dataclasses import dataclass

from . import approved_parent_schema_sections as sections
from . import approved_parent_schema_values as values
from . import quality_receipt_json as wire

InitializationOriginReceiptSchemaError = wire.QualityReceiptSchemaError
ArtifactRefV1 = values.ArtifactRefV1
MediaRefV1 = values.MediaRefV1
_TOP_KEYS = frozenset(
    "base buildRuntime expectedParent graphics identity operation output plan "
    "policies quality realizationKind schemaVersion status".split()
)
_POLICY_KEYS = frozenset(
    "fallbackPolicyId initializationExecutionPolicyId qualityPolicyId "
    "repairPolicyId".split()
)
_OPERATION_KEYS = frozenset("artifact digest kind snapshotAuthority snapshotId".split())
_BUILD_KEYS = frozenset(
    "compositorBuildReceipt renderBuildReceipt runtimeCapabilityManifest".split()
)
_OUTPUT_KEYS = frozenset("cover coverProof final proxyDisposition".split())


@dataclass(frozen=True)
class OriginPoliciesV1:
    """Commit policies with an explicitly initialization-scoped execution ID."""

    initialization_execution_policy_id: str
    repair_policy_id: str
    quality_policy_id: str
    fallback_policy_id: str


@dataclass(frozen=True)
class OriginOperationV1:
    """Exact initialize operation and its separately persisted snapshot authority."""

    kind: str
    artifact: ArtifactRefV1
    digest: str
    snapshot_authority: ArtifactRefV1
    snapshot_id: str


@dataclass(frozen=True)
class OriginBuildRuntimeV1:
    """Build and runtime records named by the initialized generation."""

    render_build_receipt: ArtifactRefV1
    compositor_build_receipt: ArtifactRefV1
    runtime_capability_manifest: ArtifactRefV1


@dataclass(frozen=True)
class OriginOutputV1:
    """Genesis output roles; intentionally has no assembly-receipt field."""

    final: MediaRefV1
    cover: ArtifactRefV1
    cover_proof: ArtifactRefV1
    proxy_disposition: str


@dataclass(frozen=True)
class InitializationOriginReceiptV1:
    """Acyclic genesis receipt with no publication claim."""

    status: str
    realization_kind: str
    expected_parent: None
    identity: sections.ApprovedParentIdentityV1
    policies: OriginPoliciesV1
    operation: OriginOperationV1
    plan: sections.ApprovedParentPlanV1
    base: sections.ApprovedParentBaseV1
    graphics: sections.ApprovedParentGraphicsV1
    build_runtime: OriginBuildRuntimeV1
    output: OriginOutputV1
    quality: sections.ApprovedParentQualityV1
    document_json: bytes


def _policies(value: object) -> OriginPoliciesV1:
    row = wire.exact(value, _POLICY_KEYS, "origin policies")
    return OriginPoliciesV1(
        wire.digest(
            row["initializationExecutionPolicyId"],
            "initialization execution policy ID",
        ),
        wire.digest(row["repairPolicyId"], "origin repair policy ID"),
        wire.digest(row["qualityPolicyId"], "origin quality policy ID"),
        wire.digest(row["fallbackPolicyId"], "origin fallback policy ID"),
    )


def _operation(value: object) -> OriginOperationV1:
    row = wire.exact(value, _OPERATION_KEYS, "origin operation")
    if row["kind"] != "initialize":
        raise InitializationOriginReceiptSchemaError("origin operation kind is invalid")
    return OriginOperationV1(
        row["kind"],
        wire.artifact(row["artifact"]),
        wire.digest(row["digest"], "origin operation digest"),
        wire.artifact(row["snapshotAuthority"]),
        wire.digest(row["snapshotId"], "origin snapshot ID"),
    )


def _build_runtime(value: object) -> OriginBuildRuntimeV1:
    row = wire.exact(value, _BUILD_KEYS, "origin build/runtime")
    return OriginBuildRuntimeV1(
        wire.artifact(row["renderBuildReceipt"]),
        wire.artifact(row["compositorBuildReceipt"]),
        wire.artifact(row["runtimeCapabilityManifest"]),
    )


def _output(value: object) -> OriginOutputV1:
    row = wire.exact(value, _OUTPUT_KEYS, "origin output")
    if row["proxyDisposition"] != "omitted-by-policy":
        raise InitializationOriginReceiptSchemaError(
            "origin proxy disposition is invalid"
        )
    try:
        final = values.parse_media(row["final"])
    except values.ApprovedParentSchemaError as exc:
        raise InitializationOriginReceiptSchemaError(str(exc)) from exc
    return OriginOutputV1(
        final,
        wire.artifact(row["cover"]),
        wire.artifact(row["coverProof"]),
        row["proxyDisposition"],
    )


def _sections(document: dict) -> tuple:
    try:
        return (
            sections.parse_identity(document["identity"]),
            sections.parse_plan(document["plan"]),
            sections.parse_base(document["base"]),
            sections.parse_graphics(document["graphics"]),
            sections.parse_quality(document["quality"]),
        )
    except values.ApprovedParentSchemaError as exc:
        raise InitializationOriginReceiptSchemaError(str(exc)) from exc


def _parsed(document: dict, raw: bytes) -> InitializationOriginReceiptV1:
    wire.exact(document, _TOP_KEYS, "initialization origin receipt")
    valid = (
        type(document["schemaVersion"]) is int
        and document["schemaVersion"] == 1
        and document["status"] == "complete-private-initialization-origin"
        and document["realizationKind"] == "deterministic-mp4"
        and document["expectedParent"] is None
    )
    if not valid:
        raise InitializationOriginReceiptSchemaError(
            "initialization origin envelope is invalid"
        )
    identity, plan, base, graphics, quality = _sections(document)
    return InitializationOriginReceiptV1(
        document["status"],
        document["realizationKind"],
        None,
        identity,
        _policies(document["policies"]),
        _operation(document["operation"]),
        plan,
        base,
        graphics,
        _build_runtime(document["buildRuntime"]),
        _output(document["output"]),
        quality,
        raw,
    )


def _exact_media_timing(value: InitializationOriginReceiptV1) -> None:
    media = (value.base.media, value.output.final) + tuple(
        asset.media for asset in value.graphics.assets
    )
    if any(type(item.facts.duration_seconds) is not float for item in media):
        raise InitializationOriginReceiptSchemaError(
            "initialization origin media timing types are invalid"
        )


def parse_initialization_origin_receipt_v1(
    raw: object,
) -> InitializationOriginReceiptV1:
    """Parse exact canonical genesis bytes with no assembly/publication aliases."""
    document = wire.canonical_document(raw, "initialization origin receipt")
    parsed = _parsed(document, raw)
    _exact_media_timing(parsed)
    paths = tuple(ref.relative_path.casefold() for ref in values.artifact_refs(parsed))
    if len(paths) != len(set(paths)):
        raise InitializationOriginReceiptSchemaError(
            "initialization origin artifact paths alias"
        )
    return parsed


def validate_initialization_origin_receipt_v1(value: object) -> None:
    """Reject direct construction that differs from authoritative receipt bytes."""
    valid = (
        type(value) is InitializationOriginReceiptV1
        and type(value.document_json) is bytes
    )
    if not valid:
        raise InitializationOriginReceiptSchemaError(
            "initialization origin receipt instance is invalid"
        )
    parsed = parse_initialization_origin_receipt_v1(value.document_json)
    if not wire.same_typed_value(value, parsed):
        raise InitializationOriginReceiptSchemaError(
            "initialization origin receipt construction is invalid"
        )
