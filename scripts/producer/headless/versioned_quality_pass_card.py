"""Exact approved quality-pass card for assembly receipt V2 generations."""

from __future__ import annotations

from dataclasses import dataclass

from . import approved_parent_schema_sections as sections
from . import approved_parent_schema_values as values
from . import quality_receipt_json as wire
from .operation_wire import parse_parent
from .repair_intent import ParentRefV1

QualityPassApprovedCardV2Error = wire.QualityReceiptSchemaError
_TOP_KEYS = frozenset(
    "base expectedParent graphics identity output plan policies provenance quality "
    "realizationKind schemaVersion status".split()
)


@dataclass(frozen=True)
class QualityPassApprovedCardV2:
    """Non-genesis card whose current receipt is assembly-receipt-v2."""

    status: str
    realization_kind: str
    expected_parent: ParentRefV1
    identity: sections.ApprovedParentIdentityV1
    policies: sections.ApprovedParentPoliciesV1
    provenance: sections.ApprovedParentProvenanceV1
    plan: sections.ApprovedParentPlanV1
    base: sections.ApprovedParentBaseV1
    graphics: sections.ApprovedParentGraphicsV1
    output: sections.ApprovedParentOutputV1
    quality: sections.ApprovedParentQualityV1
    document_json: bytes


def _sections(document: dict) -> tuple:
    try:
        return (
            sections.parse_identity(document["identity"]),
            sections.parse_policies(document["policies"]),
            sections.parse_provenance(document["provenance"]),
            sections.parse_plan(document["plan"]),
            sections.parse_base(document["base"]),
            sections.parse_graphics(document["graphics"]),
            sections.parse_output(document["output"]),
            sections.parse_quality(document["quality"]),
        )
    except values.ApprovedParentSchemaError as exc:
        raise QualityPassApprovedCardV2Error(str(exc)) from exc


def _parsed(document: dict, raw: bytes) -> QualityPassApprovedCardV2:
    wire.exact(document, _TOP_KEYS, "quality-pass approved card V2")
    valid = (
        type(document["schemaVersion"]) is int
        and document["schemaVersion"] == 2
        and document["status"] == "approved-private-quality-pass-generation"
        and document["realizationKind"] == "deterministic-mp4"
    )
    if not valid:
        raise QualityPassApprovedCardV2Error(
            "quality-pass approved-card envelope is invalid"
        )
    identity, policies, provenance, plan, base, graphics, output, quality = _sections(
        document
    )
    return QualityPassApprovedCardV2(
        document["status"],
        document["realizationKind"],
        parse_parent(document["expectedParent"]),
        identity,
        policies,
        provenance,
        plan,
        base,
        graphics,
        output,
        quality,
        raw,
    )


def _validate_refs(value: QualityPassApprovedCardV2) -> None:
    paths = tuple(ref.relative_path.casefold() for ref in values.artifact_refs(value))
    if len(paths) != len(set(paths)):
        raise QualityPassApprovedCardV2Error(
            "quality-pass approved-card artifact paths alias"
        )
    media = (value.base.media, value.output.final) + tuple(
        asset.media for asset in value.graphics.assets
    )
    if any(type(item.facts.duration_seconds) is not float for item in media):
        raise QualityPassApprovedCardV2Error(
            "quality-pass card media timing types are invalid"
        )


def parse_quality_pass_approved_card_v2(raw: object) -> QualityPassApprovedCardV2:
    """Parse exact canonical non-genesis card bytes with assembly output."""
    document = wire.canonical_document(raw, "quality-pass approved card V2")
    parsed = _parsed(document, raw)
    _validate_refs(parsed)
    return parsed


def validate_quality_pass_approved_card_v2(value: object) -> None:
    """Reject direct construction outside the authoritative V2 card bytes."""
    valid = (
        type(value) is QualityPassApprovedCardV2 and type(value.document_json) is bytes
    )
    if not valid:
        raise QualityPassApprovedCardV2Error(
            "quality-pass approved-card instance is invalid"
        )
    parsed = parse_quality_pass_approved_card_v2(value.document_json)
    if not wire.same_typed_value(value, parsed):
        raise QualityPassApprovedCardV2Error(
            "quality-pass approved-card construction is invalid"
        )
