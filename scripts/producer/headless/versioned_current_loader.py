"""Disk-backed, non-authorizing loader for versioned selected CURRENT."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Mapping
from types import MappingProxyType

from .approved_parent_binding import class_artifacts
from .artifact_contract import ArtifactRefV1
from .generation_artifact_store import GenerationArtifactStoreV1
from .genesis_approved_card import parse_genesis_approved_card_v2
from .genesis_authority_types import GenesisAuthorityInputsV2
from .genesis_execution_policy import parse_initialization_execution_policy_v2
from .genesis_generation_profile import (
    GENESIS_R1_PROFILE,
    GENESIS_R1_SEMANTIC_DOCUMENT_MAX_BYTES,
    QUALITY_PASS_R0_PROFILE,
)
from .genesis_generation_verification import (
    parse_genesis_generation_verification_v2,
)
from .genesis_payload_reobservation import reobserve_genesis_payload
from .genesis_streaming_authority import bind_streamed_genesis_r1_authority
from .operation_contract import InitializeOperationV1, parse_headless_mp4_operation_v1
from .origin_receipt import parse_initialization_origin_receipt_v1
from .versioned_assembly_receipt import parse_assembly_receipt_v2
from .versioned_current_loader_types import (
    GENESIS_R1_DISK_BLOCKERS,
    GENESIS_R1_DISK_STATUS,
    LEGACY_R0_BLOCKERS,
    LEGACY_R0_SELECTED_STATUS,
    QUALITY_PASS_V2_DISK_BLOCKERS,
    FrozenR0CurrentSelectionV1,
    GenesisR1CurrentDocumentsV2,
    QualityPassV2CurrentDocumentsV2,
    VersionedCurrentAuthorityResultV2,
)
from .versioned_generation_reader import (
    VersionedResolvedGenerationV2,
    read_versioned_current_generation,
    validate_versioned_resolved_generation,
)
from .versioned_quality_pass_card import parse_quality_pass_approved_card_v2
from .versioned_quality_pass_current_binding import (
    bind_quality_pass_current_authority_v2,
)
from .versioned_quality_pass_types import QualityPassAuthorityInputsV2
from .versioned_quality_pass_profile import QUALITY_PASS_R1_PROFILE
from .versioned_quality_pass_verification import (
    parse_quality_pass_generation_verification_v2,
)

_GENESIS_DOCUMENT_LIMIT = GENESIS_R1_SEMANTIC_DOCUMENT_MAX_BYTES
_QUALITY_PASS_DOCUMENT_LIMIT = 16 * 1024 * 1024
_GENESIS_DOCUMENT_CLASSES = (
    "genesis-approved-card-v2",
    "initialization-origin-receipt-v1",
    "headless-operation-v1",
    "initialization-snapshot-authority-v1",
    "initialization-execution-policy-v2",
    "generation-verification-v2",
)
_GENESIS_POLICY_CLASSES = (
    "repair-policy-v1",
    "quality-policy-v1",
    "fallback-policy-v1",
)
_QUALITY_PASS_DOCUMENT_CLASSES = (
    "quality-pass-approved-card-v2",
    "assembly-receipt-v2",
    "quality-pass-generation-verification-v2",
)


def _document_limit(artifact_class: str) -> int:
    if artifact_class in _GENESIS_DOCUMENT_CLASSES + _GENESIS_POLICY_CLASSES:
        return _GENESIS_DOCUMENT_LIMIT
    return _QUALITY_PASS_DOCUMENT_LIMIT


class VersionedCurrentAuthorityLoadError(RuntimeError):
    """Selected versioned authority documents are stale or inconsistent."""


def _artifacts(
    selected: VersionedResolvedGenerationV2,
) -> Mapping[str, tuple[ArtifactRefV1, ...]]:
    selection = validate_versioned_resolved_generation(selected)
    return class_artifacts(selection.groups)


def _sole(
    artifacts: Mapping[str, tuple[ArtifactRefV1, ...]], artifact_class: str
) -> ArtifactRefV1:
    matches = artifacts.get(artifact_class, ())
    if len(matches) != 1:
        raise VersionedCurrentAuthorityLoadError(
            f"authority class is not singular: {artifact_class}"
        )
    return matches[0]


def _read_documents(
    store: GenerationArtifactStoreV1,
    artifacts: Mapping[str, tuple[ArtifactRefV1, ...]],
    classes: tuple[str, ...],
) -> tuple[dict[str, ArtifactRefV1], dict[str, bytes]]:
    refs, raw = {}, {}
    for artifact_class in classes:
        ref = _sole(artifacts, artifact_class)
        refs[artifact_class] = ref
        raw[artifact_class] = store.read(ref, _document_limit(artifact_class))
    return refs, raw


def _assert_store_closure(
    store: GenerationArtifactStoreV1,
    artifacts: Mapping[str, tuple[ArtifactRefV1, ...]],
) -> None:
    for refs in artifacts.values():
        for ref in refs:
            store.resolve(ref)


def _genesis_inputs(
    selected: VersionedResolvedGenerationV2,
    store: GenerationArtifactStoreV1,
    artifacts: Mapping[str, tuple[ArtifactRefV1, ...]],
) -> tuple[GenesisAuthorityInputsV2, Mapping[str, ArtifactRefV1]]:
    classes = _GENESIS_DOCUMENT_CLASSES + _GENESIS_POLICY_CLASSES
    refs, raw = _read_documents(store, artifacts, classes)
    operation = parse_headless_mp4_operation_v1(raw["headless-operation-v1"])
    if type(operation) is not InitializeOperationV1:
        raise VersionedCurrentAuthorityLoadError(
            "genesis operation class/version is invalid"
        )
    by_path = {refs[name].relative_path: value for name, value in raw.items()}
    inputs = GenesisAuthorityInputsV2(
        selected.generation.commit,
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
    return inputs, MappingProxyType(refs)


def _load_genesis(
    selected: VersionedResolvedGenerationV2,
    store: GenerationArtifactStoreV1,
    artifacts: Mapping[str, tuple[ArtifactRefV1, ...]],
) -> GenesisR1CurrentDocumentsV2:
    inputs, refs = _genesis_inputs(selected, store, artifacts)
    _assert_store_closure(store, artifacts)
    observation = reobserve_genesis_payload(selected)
    binding = bind_streamed_genesis_r1_authority(inputs, observation)
    return GenesisR1CurrentDocumentsV2(
        "genesis-r1",
        GENESIS_R1_DISK_STATUS,
        selected.profile,
        selected.approved_card_class,
        selected.generation.current,
        inputs.commit,
        inputs.approved_card,
        inputs.origin_receipt,
        inputs.operation,
        inputs.initialization_policy,
        inputs.verification,
        inputs.snapshot_authority_json,
        refs,
        observation,
        binding,
        GENESIS_R1_DISK_BLOCKERS,
        True,
        True,
        True,
        False,
        False,
        False,
    )


def _load_quality_pass(
    selected: VersionedResolvedGenerationV2,
    store: GenerationArtifactStoreV1,
    artifacts: Mapping[str, tuple[ArtifactRefV1, ...]],
) -> QualityPassV2CurrentDocumentsV2:
    refs, raw = _read_documents(store, artifacts, _QUALITY_PASS_DOCUMENT_CLASSES)
    authority = QualityPassAuthorityInputsV2(
        selected.generation.commit,
        parse_quality_pass_approved_card_v2(raw["quality-pass-approved-card-v2"]),
        parse_assembly_receipt_v2(raw["assembly-receipt-v2"]),
        parse_quality_pass_generation_verification_v2(
            raw["quality-pass-generation-verification-v2"]
        ),
    )
    binding = bind_quality_pass_current_authority_v2(authority)
    _assert_store_closure(store, artifacts)
    return QualityPassV2CurrentDocumentsV2(
        "quality-pass-v2",
        binding.status,
        selected.profile,
        selected.approved_card_class,
        selected.generation.current,
        authority.commit,
        authority,
        binding,
        MappingProxyType(refs),
        QUALITY_PASS_V2_DISK_BLOCKERS,
        True,
        True,
        False,
        False,
        False,
    )


def _load_selected(
    selected: VersionedResolvedGenerationV2,
) -> VersionedCurrentAuthorityResultV2:
    artifacts = _artifacts(selected)
    store = GenerationArtifactStoreV1.from_resolved(selected.generation)
    _assert_store_closure(store, artifacts)
    if selected.profile == QUALITY_PASS_R0_PROFILE:
        generation = selected.generation
        return FrozenR0CurrentSelectionV1(
            "frozen-r0",
            LEGACY_R0_SELECTED_STATUS,
            selected.profile,
            selected.approved_card_class,
            generation.current,
            generation.commit,
            LEGACY_R0_BLOCKERS,
            False,
            False,
            False,
            False,
        )
    if selected.profile == GENESIS_R1_PROFILE:
        return _load_genesis(selected, store, artifacts)
    if selected.profile == QUALITY_PASS_R1_PROFILE:
        return _load_quality_pass(selected, store, artifacts)
    raise VersionedCurrentAuthorityLoadError("selected profile is unsupported")


@contextlib.contextmanager
def load_versioned_current_authority(
    authority_root: str, materialization_root: str
) -> Iterator[VersionedCurrentAuthorityResultV2]:
    """Load tagged versioned authority documents without execution authority."""
    try:
        with read_versioned_current_generation(
            authority_root, materialization_root
        ) as selected:
            result = _load_selected(selected)
    except VersionedCurrentAuthorityLoadError:
        raise
    except RuntimeError as exc:
        raise VersionedCurrentAuthorityLoadError(
            "versioned selected authority is invalid"
        ) from exc
    yield result


def require_versioned_current_execution_authorized(value: object) -> None:
    """Never promote any disk-selection result into execution authority."""
    if type(value) not in {
        FrozenR0CurrentSelectionV1,
        GenesisR1CurrentDocumentsV2,
        QualityPassV2CurrentDocumentsV2,
    }:
        raise VersionedCurrentAuthorityLoadError("versioned loader result is invalid")
    raise VersionedCurrentAuthorityLoadError(
        "versioned disk authority is not execution-authorized"
    )
