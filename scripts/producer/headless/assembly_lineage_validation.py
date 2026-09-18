"""Revalidate a historical materialization before assembly lineage use."""

from __future__ import annotations

from types import MappingProxyType

from .approved_parent_binding import validate_descriptor_identity
from .approved_parent_schema import (
    ApprovedParentDescriptorV1,
    parse_approved_parent_descriptor,
)
from .generation_schema import (
    CurrentPointerV1,
    GenerationCommitV1,
    parse_current_pointer,
    parse_generation_commit,
)
from .historical_generation_store import HistoricalMaterializedArtifactStoreV1
from .historical_generation_types import (
    SELECTED_CURRENT_ANCESTRY_SCOPE,
    HistoricalGenerationMaterializationV1,
    HistoricalGenerationRecordV1,
)
from .historical_generation_validation import validate_historical_generation
from .quality_receipt_json import same_typed_value
from .repair_intent import ParentRefV1, validate_parent_ref

_MAPPING_PROXY = type(MappingProxyType({}))


class AssemblyLineageValidationError(RuntimeError):
    """Historical materialization is forged, incomplete, or substituted."""


def _parsed_record(
    value: object,
) -> tuple[HistoricalGenerationRecordV1, GenerationCommitV1]:
    valid_types = (
        type(value) is HistoricalGenerationRecordV1
        and type(value.ref) is ParentRefV1
        and type(value.commit) is GenerationCommitV1
        and type(value.descriptor) is ApprovedParentDescriptorV1
    )
    if not valid_types:
        raise AssemblyLineageValidationError("historical record type is invalid")
    try:
        validate_parent_ref(value.ref)
        commit = parse_generation_commit(value.commit.document_json)
        descriptor = parse_approved_parent_descriptor(value.descriptor.document_json)
        validate_descriptor_identity(descriptor, commit)
    except RuntimeError as exc:
        raise AssemblyLineageValidationError("historical record is invalid") from exc
    valid = (
        same_typed_value(value.commit, commit)
        and same_typed_value(value.descriptor, descriptor)
        and value.ref.authority_id == commit.authority_id
        and value.ref.generation_id == commit.generation_id
        and value.ref.commit_digest == commit.commit_digest
        and value.ref.plan_digest == descriptor.plan.approved_plan_digest
    )
    if not valid:
        raise AssemblyLineageValidationError("historical record identity differs")
    return value, commit


def _validate_anchor(value: HistoricalGenerationMaterializationV1) -> None:
    if type(value.anchor_current) is not CurrentPointerV1:
        raise AssemblyLineageValidationError("historical CURRENT type is invalid")
    try:
        parsed = parse_current_pointer(value.anchor_current.document_json)
    except RuntimeError as exc:
        raise AssemblyLineageValidationError("historical CURRENT is invalid") from exc
    if not same_typed_value(value.anchor_current, parsed):
        raise AssemblyLineageValidationError("historical CURRENT identity differs")


def _validate_lineage(value: HistoricalGenerationMaterializationV1) -> None:
    if type(value.lineage) is not tuple or not value.lineage:
        raise AssemblyLineageValidationError("historical lineage is empty")
    records = tuple(_parsed_record(item)[0] for item in value.lineage)
    first = records[0].ref
    anchor = value.anchor_current
    if (
        first.authority_id,
        first.publication_seq,
        first.generation_id,
        first.commit_digest,
    ) != (
        anchor.authority_id,
        anchor.publication_seq,
        anchor.generation_id,
        anchor.commit_digest,
    ):
        raise AssemblyLineageValidationError("historical lineage is not CURRENT")


def _lineage_edges(value: HistoricalGenerationMaterializationV1) -> None:
    records = value.lineage
    for child, parent in zip(records, records[1:]):
        valid = (
            child.commit.expected_parent == parent.ref
            and child.ref.publication_seq == parent.ref.publication_seq + 1
        )
        if not valid:
            raise AssemblyLineageValidationError("historical lineage edge differs")
    tail = records[-1]
    if tail.ref.publication_seq != 1 or tail.commit.expected_parent is not None:
        raise AssemblyLineageValidationError("historical lineage lacks genesis")
    matches = tuple(item for item in records if same_typed_value(item, value.target))
    if len(matches) != 1:
        raise AssemblyLineageValidationError("historical target is ambiguous")


def _validate_maps(value: HistoricalGenerationMaterializationV1) -> None:
    if (
        type(value.materialized) is not _MAPPING_PROXY
        or type(value.materialized_snapshots) is not _MAPPING_PROXY
    ):
        raise AssemblyLineageValidationError("historical mappings are mutable")
    valid_paths = all(
        type(name) is str and type(path) is str
        for name, path in value.materialized.items()
    )
    valid_snapshots = all(
        type(name) is str
        and type(snapshot) is tuple
        and len(snapshot) == 8
        and all(type(item) is int for item in snapshot)
        for name, snapshot in value.materialized_snapshots.items()
    )
    if not valid_paths or not valid_snapshots:
        raise AssemblyLineageValidationError("historical mappings are invalid")


def validate_historical_materialization(
    value: object,
) -> tuple[
    HistoricalGenerationMaterializationV1,
    HistoricalMaterializedArtifactStoreV1,
    ApprovedParentDescriptorV1,
]:
    """Return an exact target store after revalidating the selected-chain proof."""
    valid = (
        type(value) is HistoricalGenerationMaterializationV1
        and type(value.proof_scope) is str
        and value.proof_scope == SELECTED_CURRENT_ANCESTRY_SCOPE
        and type(value.target) is HistoricalGenerationRecordV1
    )
    if not valid:
        raise AssemblyLineageValidationError("historical proof scope is invalid")
    _validate_anchor(value)
    _validate_lineage(value)
    _lineage_edges(value)
    _validate_maps(value)
    target, _commit = _parsed_record(value.target)
    try:
        store = HistoricalMaterializedArtifactStoreV1.from_copy(
            target.commit, value.materialized, value.materialized_snapshots
        )
        descriptor, plan_digest = validate_historical_generation(target.commit, store)
    except RuntimeError as exc:
        raise AssemblyLineageValidationError(
            "historical target bytes are invalid"
        ) from exc
    if (
        not same_typed_value(descriptor, target.descriptor)
        or plan_digest != target.ref.plan_digest
    ):
        raise AssemblyLineageValidationError("historical target bytes differ")
    return value, store, descriptor
