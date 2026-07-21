"""Exact genesis authority card that references origin, never assembly."""

from __future__ import annotations

from dataclasses import dataclass

from . import approved_parent_schema_sections as sections
from . import approved_parent_schema_values as values
from . import quality_receipt_json as wire

GenesisApprovedCardError = wire.QualityReceiptSchemaError
ArtifactRefV1 = values.ArtifactRefV1
MediaRefV1 = values.MediaRefV1
_TOP_KEYS = frozenset(
    "base expectedParent graphics identity origin output plan policies provenance "
    "quality realizationKind schemaVersion status".split()
)
_ORIGIN_KEYS = frozenset(
    "operation operationDigest receipt snapshotAuthority snapshotId".split()
)
_OUTPUT_KEYS = frozenset("cover coverProof final proxyDisposition".split())


@dataclass(frozen=True)
class GenesisOriginAuthorityV2:
    """Acyclic refs to the origin, operation, and presealed snapshot authority."""

    receipt: ArtifactRefV1
    operation: ArtifactRefV1
    operation_digest: str
    snapshot_authority: ArtifactRefV1
    snapshot_id: str


@dataclass(frozen=True)
class GenesisOutputV2:
    """Genesis outputs without an assembly-receipt alias."""

    final: MediaRefV1
    cover: ArtifactRefV1
    cover_proof: ArtifactRefV1
    proxy_disposition: str


@dataclass(frozen=True)
class GenesisApprovedCardV2:
    """Complete private genesis current card; publication stays external."""

    status: str
    realization_kind: str
    expected_parent: None
    identity: sections.ApprovedParentIdentityV1
    policies: sections.ApprovedParentPoliciesV1
    provenance: sections.ApprovedParentProvenanceV1
    origin: GenesisOriginAuthorityV2
    plan: sections.ApprovedParentPlanV1
    base: sections.ApprovedParentBaseV1
    graphics: sections.ApprovedParentGraphicsV1
    output: GenesisOutputV2
    quality: sections.ApprovedParentQualityV1
    document_json: bytes


def parse_genesis_origin_authority_v2(value: object) -> GenesisOriginAuthorityV2:
    """Parse the closed origin authority section shared by verification V2."""
    row = wire.exact(value, _ORIGIN_KEYS, "genesis origin authority")
    result = GenesisOriginAuthorityV2(
        wire.artifact(row["receipt"]),
        wire.artifact(row["operation"]),
        wire.digest(row["operationDigest"], "genesis operation digest"),
        wire.artifact(row["snapshotAuthority"]),
        wire.digest(row["snapshotId"], "genesis snapshot ID"),
    )
    refs = (result.receipt, result.operation, result.snapshot_authority)
    paths = tuple(ref.relative_path.casefold() for ref in refs)
    if len(set(paths)) != len(paths):
        raise GenesisApprovedCardError("genesis origin artifact paths alias")
    return result


def _output(value: object) -> GenesisOutputV2:
    row = wire.exact(value, _OUTPUT_KEYS, "genesis output")
    if row["proxyDisposition"] != "omitted-by-policy":
        raise GenesisApprovedCardError("genesis proxy disposition is invalid")
    try:
        final = values.parse_media(row["final"])
    except values.ApprovedParentSchemaError as exc:
        raise GenesisApprovedCardError(str(exc)) from exc
    return GenesisOutputV2(
        final,
        wire.artifact(row["cover"]),
        wire.artifact(row["coverProof"]),
        row["proxyDisposition"],
    )


def _sections(document: dict) -> tuple:
    try:
        return (
            sections.parse_identity(document["identity"]),
            sections.parse_policies(document["policies"]),
            sections.parse_provenance(document["provenance"]),
            sections.parse_plan(document["plan"]),
            sections.parse_base(document["base"]),
            sections.parse_graphics(document["graphics"]),
            sections.parse_quality(document["quality"]),
        )
    except values.ApprovedParentSchemaError as exc:
        raise GenesisApprovedCardError(str(exc)) from exc


def _parsed(document: dict, raw: bytes) -> GenesisApprovedCardV2:
    wire.exact(document, _TOP_KEYS, "genesis approved card")
    valid = (
        type(document["schemaVersion"]) is int
        and document["schemaVersion"] == 2
        and document["status"] == "approved-private-genesis-generation"
        and document["realizationKind"] == "deterministic-mp4"
        and document["expectedParent"] is None
    )
    if not valid:
        raise GenesisApprovedCardError("genesis approved-card envelope is invalid")
    identity, policies, provenance, plan, base, graphics, quality = _sections(document)
    return GenesisApprovedCardV2(
        document["status"],
        document["realizationKind"],
        None,
        identity,
        policies,
        provenance,
        parse_genesis_origin_authority_v2(document["origin"]),
        plan,
        base,
        graphics,
        _output(document["output"]),
        quality,
        raw,
    )


def _validate_refs(value: GenesisApprovedCardV2) -> None:
    paths = tuple(ref.relative_path.casefold() for ref in values.artifact_refs(value))
    if len(paths) != len(set(paths)):
        raise GenesisApprovedCardError("genesis approved-card artifact paths alias")
    media = (value.base.media, value.output.final) + tuple(
        asset.media for asset in value.graphics.assets
    )
    if any(type(item.facts.duration_seconds) is not float for item in media):
        raise GenesisApprovedCardError("genesis media timing types are invalid")


def parse_genesis_approved_card_v2(raw: object) -> GenesisApprovedCardV2:
    """Parse exact canonical genesis bytes with an origin and no assembly field."""
    document = wire.canonical_document(raw, "genesis approved card")
    parsed = _parsed(document, raw)
    _validate_refs(parsed)
    return parsed


def validate_genesis_approved_card_v2(value: object) -> None:
    """Reject forged direct construction outside the authoritative card bytes."""
    valid = type(value) is GenesisApprovedCardV2 and type(value.document_json) is bytes
    if not valid:
        raise GenesisApprovedCardError("genesis approved-card instance is invalid")
    parsed = parse_genesis_approved_card_v2(value.document_json)
    if not wire.same_typed_value(value, parsed):
        raise GenesisApprovedCardError("genesis approved-card identity is invalid")
