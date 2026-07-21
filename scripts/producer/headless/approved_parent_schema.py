"""Exact acyclic authority card for one approved private MP4 generation."""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import approved_parent_schema_sections as sections
from . import approved_parent_schema_values as values
from .wire_identity import same_wire_value

ApprovedParentSchemaError = values.ApprovedParentSchemaError
ArtifactRefV1 = values.ArtifactRefV1
MediaFactsV1 = values.MediaFactsV1
MediaRefV1 = values.MediaRefV1
GraphicAssetRefV1 = values.GraphicAssetRefV1
CriticArtifactRefV1 = values.CriticArtifactRefV1
ApprovedParentIdentityV1 = sections.ApprovedParentIdentityV1
ApprovedParentPoliciesV1 = sections.ApprovedParentPoliciesV1
ApprovedParentProvenanceV1 = sections.ApprovedParentProvenanceV1
ApprovedParentPlanV1 = sections.ApprovedParentPlanV1
ApprovedParentBaseV1 = sections.ApprovedParentBaseV1
ApprovedParentGraphicsV1 = sections.ApprovedParentGraphicsV1
ApprovedParentOutputV1 = sections.ApprovedParentOutputV1
ApprovedParentQualityV1 = sections.ApprovedParentQualityV1

_TOP_KEYS = frozenset(
    "base graphics identity output plan policies provenance quality "
    "realizationKind schemaVersion status".split()
)


class _DuplicateKey(ValueError):
    pass


@dataclass(frozen=True)
class ApprovedParentDescriptorV1:
    status: str
    realization_kind: str
    identity: ApprovedParentIdentityV1
    policies: ApprovedParentPoliciesV1
    provenance: ApprovedParentProvenanceV1
    plan: ApprovedParentPlanV1
    base: ApprovedParentBaseV1
    graphics: ApprovedParentGraphicsV1
    output: ApprovedParentOutputV1
    quality: ApprovedParentQualityV1
    document_json: bytes


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ApprovedParentSchemaError("descriptor cannot be canonicalized") from exc
    return encoded.encode("ascii")


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _document(value: object) -> tuple[dict, bytes]:
    if type(value) is dict:
        return value, _canonical(value)
    if type(value) is not bytes:
        raise ApprovedParentSchemaError("descriptor must be an object or bytes")
    try:
        document = json.loads(
            value, object_pairs_hook=_pairs, parse_constant=_reject_constant
        )
    except _DuplicateKey as exc:
        raise ApprovedParentSchemaError("descriptor has duplicate JSON keys") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ApprovedParentSchemaError("descriptor is invalid JSON") from exc
    if type(document) is not dict or _canonical(document) != value:
        raise ApprovedParentSchemaError("descriptor is not exact canonical JSON")
    return document, value


def _parsed(document: dict, raw: bytes) -> ApprovedParentDescriptorV1:
    valid = (
        set(document) == _TOP_KEYS
        and type(document.get("schemaVersion")) is int
        and document["schemaVersion"] == 1
        and document.get("status") == "approved-private-generation"
        and document.get("realizationKind") == "deterministic-mp4"
    )
    if not valid:
        raise ApprovedParentSchemaError("approved-parent envelope is invalid")
    return ApprovedParentDescriptorV1(
        document["status"],
        document["realizationKind"],
        sections.parse_identity(document["identity"]),
        sections.parse_policies(document["policies"]),
        sections.parse_provenance(document["provenance"]),
        sections.parse_plan(document["plan"]),
        sections.parse_base(document["base"]),
        sections.parse_graphics(document["graphics"]),
        sections.parse_output(document["output"]),
        sections.parse_quality(document["quality"]),
        raw,
    )


def parse_approved_parent_descriptor(value: object) -> ApprovedParentDescriptorV1:
    """Parse the exact approved private-generation card without publication state."""
    document, raw = _document(value)
    parsed = _parsed(document, raw)
    paths = tuple(ref.relative_path for ref in values.artifact_refs(parsed))
    if len(paths) != len(set(paths)):
        raise ApprovedParentSchemaError("approved-parent artifact paths alias")
    return parsed


def validate_approved_parent_descriptor(value: object) -> None:
    """Revalidate direct construction against authoritative canonical bytes."""
    if type(value) is not ApprovedParentDescriptorV1:
        raise ApprovedParentSchemaError("approved-parent instance is invalid")
    if type(value.document_json) is not bytes:
        raise ApprovedParentSchemaError("approved-parent bytes are invalid")
    parsed = parse_approved_parent_descriptor(value.document_json)
    if not same_wire_value(value, parsed):
        raise ApprovedParentSchemaError(
            "approved-parent descriptor identity is invalid"
        )
