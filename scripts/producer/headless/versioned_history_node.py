"""Semantic dispatch and loading for one sealed versioned history node."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from .approved_parent_assembly_binding import (
    bind_approved_parent_assembly_receipt,
)
from .approved_parent_assembly_receipt import parse_assembly_receipt_v1
from .artifact_contract import ArtifactRefV1
from .generation_schema import GenerationCommitV1, parse_generation_commit
from .genesis_approved_card import parse_genesis_approved_card_v2
from .genesis_authority_documents import bind_exact_authority_documents
from .genesis_authority_types import GenesisAuthorityInputsV2
from .genesis_authority_validation import (
    bind_genesis_current_card,
    bind_genesis_manifest_roles,
    bind_operation_snapshot,
    revalidate_genesis_inputs,
)
from .genesis_execution_policy import parse_initialization_execution_policy_v2
from .genesis_generation_profile import GENESIS_R1_PROFILE, QUALITY_PASS_R0_PROFILE
from .genesis_generation_verification import (
    parse_genesis_generation_verification_v2,
)
from .genesis_policy_bundle import bind_genesis_policy_bundle
from .historical_generation_store import HistoricalSourceArtifactStoreV1
from .historical_generation_validation import validate_historical_generation
from .operation_contract import InitializeOperationV1, parse_headless_mp4_operation_v1
from .origin_receipt import parse_initialization_origin_receipt_v1
from .quality_receipt_json import same_typed_value
from .repair_intent import ParentRefV1, validate_parent_ref
from .versioned_assembly_receipt import parse_assembly_receipt_v2
from .versioned_generation_profile_dispatch import (
    VersionedProfileSelectionV2,
    select_versioned_generation_profile,
)
from .versioned_history_types import (
    FrozenR0HistoryAuthorityV1,
    GenesisHistoryAuthorityV1,
    QualityPassV2HistoryAuthorityV1,
    VersionedHistoryNodeV1,
    VersionedSelectedHistoryError,
)
from .versioned_quality_pass_card import parse_quality_pass_approved_card_v2
from .versioned_quality_pass_current_binding import (
    bind_quality_pass_current_authority_v2,
)
from .versioned_quality_pass_profile import QUALITY_PASS_R1_PROFILE
from .versioned_quality_pass_types import QualityPassAuthorityInputsV2
from .versioned_quality_pass_verification import (
    parse_quality_pass_generation_verification_v2,
)

_DOCUMENT_LIMIT = 16 * 1024 * 1024
_GENESIS_POLICY_CLASSES = (
    "repair-policy-v1",
    "quality-policy-v1",
    "fallback-policy-v1",
)
_GENESIS_CLASSES = (
    "genesis-approved-card-v2",
    "initialization-origin-receipt-v1",
    "headless-operation-v1",
    "initialization-snapshot-authority-v1",
    "initialization-execution-policy-v2",
    "generation-verification-v2",
    *_GENESIS_POLICY_CLASSES,
)
_QUALITY_CLASSES = (
    "quality-pass-approved-card-v2",
    "assembly-receipt-v2",
    "quality-pass-generation-verification-v2",
)


def _ref(row: object) -> ArtifactRefV1:
    return ArtifactRefV1(row.path, row.sha256, row.size_bytes)


def _sole(groups: Mapping, artifact_class: str) -> ArtifactRefV1:
    rows = groups.get(artifact_class, ())
    if len(rows) != 1:
        raise VersionedSelectedHistoryError(
            f"history authority class is not singular: {artifact_class}"
        )
    return _ref(rows[0])


def _documents(
    store: HistoricalSourceArtifactStoreV1,
    groups: Mapping,
    classes: tuple[str, ...],
) -> tuple[dict[str, ArtifactRefV1], dict[str, bytes]]:
    refs, raw = {}, {}
    for artifact_class in classes:
        ref = _sole(groups, artifact_class)
        refs[artifact_class] = ref
        raw[artifact_class] = store.read(ref, _DOCUMENT_LIMIT)
    return refs, raw


def _genesis(
    commit: GenerationCommitV1,
    selection: VersionedProfileSelectionV2,
    store: HistoricalSourceArtifactStoreV1,
) -> GenesisHistoryAuthorityV1:
    refs, raw = _documents(store, selection.groups, _GENESIS_CLASSES)
    operation = parse_headless_mp4_operation_v1(raw["headless-operation-v1"])
    if type(operation) is not InitializeOperationV1:
        raise VersionedSelectedHistoryError("genesis history operation is invalid")
    by_path = {refs[name].relative_path: value for name, value in raw.items()}
    inputs = GenesisAuthorityInputsV2(
        commit,
        parse_genesis_approved_card_v2(raw["genesis-approved-card-v2"]),
        parse_initialization_origin_receipt_v1(raw["initialization-origin-receipt-v1"]),
        operation,
        parse_initialization_execution_policy_v2(
            raw["initialization-execution-policy-v2"]
        ),
        parse_genesis_generation_verification_v2(raw["generation-verification-v2"]),
        raw["initialization-snapshot-authority-v1"],
        MappingProxyType(by_path),
    )
    _bind_genesis(inputs, selection.groups)
    return GenesisHistoryAuthorityV1(inputs)


def _bind_genesis(inputs: GenesisAuthorityInputsV2, groups: Mapping) -> None:
    revalidate_genesis_inputs(inputs)
    bind_exact_authority_documents(inputs, groups, inputs.artifact_bytes)
    bind_genesis_policy_bundle(inputs, groups, inputs.artifact_bytes)
    bind_genesis_current_card(inputs)
    bind_operation_snapshot(inputs)
    bind_genesis_manifest_roles(inputs, groups)


def _r0(
    commit: GenerationCommitV1, store: HistoricalSourceArtifactStoreV1
) -> FrozenR0HistoryAuthorityV1:
    card, _plan_digest = validate_historical_generation(commit, store)
    receipt = parse_assembly_receipt_v1(
        store.read(card.output.assembly_receipt, _DOCUMENT_LIMIT)
    )
    bind_approved_parent_assembly_receipt(card, commit, receipt)
    return FrozenR0HistoryAuthorityV1(commit, card, receipt)


def _quality_v2(
    commit: GenerationCommitV1,
    selection: VersionedProfileSelectionV2,
    store: HistoricalSourceArtifactStoreV1,
) -> QualityPassV2HistoryAuthorityV1:
    _refs, raw = _documents(store, selection.groups, _QUALITY_CLASSES)
    inputs = QualityPassAuthorityInputsV2(
        commit,
        parse_quality_pass_approved_card_v2(raw["quality-pass-approved-card-v2"]),
        parse_assembly_receipt_v2(raw["assembly-receipt-v2"]),
        parse_quality_pass_generation_verification_v2(
            raw["quality-pass-generation-verification-v2"]
        ),
    )
    bind_quality_pass_current_authority_v2(inputs)
    return QualityPassV2HistoryAuthorityV1(inputs)


def _authority(
    commit: GenerationCommitV1,
    selection: VersionedProfileSelectionV2,
    store: HistoricalSourceArtifactStoreV1,
) -> object:
    if selection.profile == GENESIS_R1_PROFILE:
        return _genesis(commit, selection, store)
    if selection.profile == QUALITY_PASS_R0_PROFILE:
        return _r0(commit, store)
    if selection.profile == QUALITY_PASS_R1_PROFILE:
        return _quality_v2(commit, selection, store)
    raise VersionedSelectedHistoryError("history profile is unsupported")


def load_versioned_history_node(
    commit: GenerationCommitV1,
    store: HistoricalSourceArtifactStoreV1,
    publication_seq: int,
) -> VersionedHistoryNodeV1:
    """Dispatch before semantic reads, then authenticate one sealed node."""
    if type(commit) is not GenerationCommitV1 or type(publication_seq) is not int:
        raise VersionedSelectedHistoryError("history node identity is invalid")
    selection = select_versioned_generation_profile(commit)
    authority = _authority(commit, selection, store)
    card = history_card(authority)
    ref = ParentRefV1(
        commit.authority_id,
        publication_seq,
        commit.generation_id,
        commit.commit_digest,
        card.plan.approved_plan_digest,
    )
    validate_parent_ref(ref)
    return VersionedHistoryNodeV1(
        ref, selection.profile, selection.approved_card_class, commit, authority
    )


def history_card(authority: object) -> object:
    """Return the exact parsed current card for an internal authority variant."""
    if type(authority) is GenesisHistoryAuthorityV1:
        return authority.inputs.approved_card
    if type(authority) is FrozenR0HistoryAuthorityV1:
        return authority.approved_card
    if type(authority) is QualityPassV2HistoryAuthorityV1:
        return authority.inputs.approved_card
    raise VersionedSelectedHistoryError("history authority variant is invalid")


def _revalidate_authority(
    authority: object,
    commit: GenerationCommitV1,
    selection: VersionedProfileSelectionV2,
) -> None:
    if type(authority) is GenesisHistoryAuthorityV1:
        if not same_typed_value(authority.inputs.commit, commit):
            raise VersionedSelectedHistoryError("genesis history commit is stale")
        _bind_genesis(authority.inputs, selection.groups)
        return
    if type(authority) is FrozenR0HistoryAuthorityV1:
        if not same_typed_value(authority.commit, commit):
            raise VersionedSelectedHistoryError("frozen R0 history commit is stale")
        bind_approved_parent_assembly_receipt(
            authority.approved_card, commit, authority.assembly_receipt
        )
        return
    if type(authority) is QualityPassV2HistoryAuthorityV1:
        if not same_typed_value(authority.inputs.commit, commit):
            raise VersionedSelectedHistoryError("quality-pass history commit is stale")
        bind_quality_pass_current_authority_v2(authority.inputs)
        return
    raise VersionedSelectedHistoryError("history authority type is invalid")


def _validated_node(value: VersionedHistoryNodeV1) -> VersionedHistoryNodeV1:
    try:
        parsed = parse_generation_commit(value.commit.document_json)
        validate_parent_ref(value.ref)
        selection = select_versioned_generation_profile(parsed)
    except RuntimeError as exc:
        raise VersionedSelectedHistoryError(
            "history node wire identity is invalid"
        ) from exc
    _revalidate_authority(value.authority, parsed, selection)
    card = history_card(value.authority)
    identity = (
        value.ref.authority_id,
        value.ref.generation_id,
        value.ref.commit_digest,
        value.ref.plan_digest,
    )
    expected = (
        parsed.authority_id,
        parsed.generation_id,
        parsed.commit_digest,
        card.plan.approved_plan_digest,
    )
    tags = (value.profile, value.approved_card_class)
    if not same_typed_value(value.commit, parsed) or identity != expected:
        raise VersionedSelectedHistoryError("history node construction is stale")
    if not same_typed_value(tags, (selection.profile, selection.approved_card_class)):
        raise VersionedSelectedHistoryError("history node class tag is stale")
    return value


def validate_versioned_history_node(value: object) -> VersionedHistoryNodeV1:
    """Reject stale tags, direct construction, and hostile subclasses."""
    if type(value) is not VersionedHistoryNodeV1:
        raise VersionedSelectedHistoryError("history node type is invalid")
    try:
        return _validated_node(value)
    except VersionedSelectedHistoryError:
        raise
    except Exception as exc:
        raise VersionedSelectedHistoryError(
            "history node construction is invalid"
        ) from exc
