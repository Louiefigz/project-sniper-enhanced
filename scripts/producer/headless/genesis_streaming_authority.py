"""Structural genesis binding over complete streamed payload evidence."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from .genesis_authority_documents import bind_exact_authority_documents
from .genesis_authority_types import (
    GENESIS_R1_STRUCTURAL_STATUS,
    REMAINING_GENESIS_R1_BLOCKERS,
    GenesisAuthorityBindingV2,
    GenesisAuthorityInputsV2,
)
from .genesis_authority_validation import (
    GenesisAuthorityBindingError,
    bind_genesis_current_card,
    bind_genesis_manifest_roles,
    bind_operation_snapshot,
    revalidate_genesis_inputs,
)
from .genesis_execution_policy import bind_initialize_operation_policy_v2
from .genesis_generation_profile import GENESIS_R1_PROFILE
from .genesis_payload_reobservation import (
    validate_genesis_payload_reobservation,
)
from .genesis_policy_bundle import bind_genesis_policy_bundle
from .origin_requirements import R1_PROFILE_REQUIREMENTS
from .versioned_generation_profile_dispatch import (
    select_versioned_generation_profile,
)

_SEMANTIC_CLASSES = (
    "genesis-approved-card-v2",
    "initialization-origin-receipt-v1",
    "headless-operation-v1",
    "initialization-snapshot-authority-v1",
    "initialization-execution-policy-v2",
    "generation-verification-v2",
    "repair-policy-v1",
    "quality-policy-v1",
    "fallback-policy-v1",
)


def _semantic_paths(groups: Mapping) -> frozenset[str]:
    paths = []
    for artifact_class in _SEMANTIC_CLASSES:
        rows = groups.get(artifact_class, ())
        if len(rows) != 1:
            raise GenesisAuthorityBindingError(
                f"genesis semantic class is not singular: {artifact_class}"
            )
        paths.append(rows[0].path)
    return frozenset(paths)


def _semantic_snapshot(
    inputs: GenesisAuthorityInputsV2, groups: Mapping
) -> Mapping[str, bytes]:
    artifacts = inputs.artifact_bytes
    allowed_types = {dict, type(MappingProxyType({}))}
    if type(artifacts) not in allowed_types or len(artifacts) != len(_SEMANTIC_CLASSES):
        raise GenesisAuthorityBindingError("genesis semantic bytes are invalid")
    try:
        snapshot = dict(artifacts)
        paths = frozenset(snapshot)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise GenesisAuthorityBindingError(
            "genesis semantic mapping is invalid"
        ) from exc
    if paths != _semantic_paths(groups):
        raise GenesisAuthorityBindingError(
            "genesis semantic document mapping is not exact closure"
        )
    if any(
        type(path) is not str or type(raw) is not bytes
        for path, raw in snapshot.items()
    ):
        raise GenesisAuthorityBindingError("genesis semantic documents are invalid")
    return MappingProxyType(snapshot)


def _binding_result(groups: Mapping) -> GenesisAuthorityBindingV2:
    return GenesisAuthorityBindingV2(
        GENESIS_R1_STRUCTURAL_STATUS,
        R1_PROFILE_REQUIREMENTS,
        REMAINING_GENESIS_R1_BLOCKERS,
        tuple(groups),
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
    )


def bind_streamed_genesis_r1_authority(
    inputs: object, observation: object
) -> GenesisAuthorityBindingV2:
    """Bind R1 structure after exact complete payload streaming evidence."""
    inputs = revalidate_genesis_inputs(inputs)
    try:
        selection = select_versioned_generation_profile(inputs.commit)
        validate_genesis_payload_reobservation(observation, inputs.commit)
    except RuntimeError as exc:
        raise GenesisAuthorityBindingError(
            "streamed genesis payload evidence is invalid"
        ) from exc
    if selection.profile != GENESIS_R1_PROFILE:
        raise GenesisAuthorityBindingError("streamed genesis profile is invalid")
    groups = selection.groups
    artifacts = _semantic_snapshot(inputs, groups)
    bind_exact_authority_documents(inputs, groups, artifacts)
    bind_genesis_policy_bundle(inputs, groups, artifacts)
    bind_genesis_current_card(inputs)
    bind_operation_snapshot(inputs)
    bind_genesis_manifest_roles(inputs, groups)
    compatibility = bind_initialize_operation_policy_v2(
        inputs.operation, inputs.initialization_policy
    )
    if not compatibility.policy_compatible or compatibility.execution_authorized:
        raise GenesisAuthorityBindingError("initialization policy gate is invalid")
    return _binding_result(groups)
