"""Composition-free structural binding for genesis R1 authorities."""

from __future__ import annotations

from .genesis_authority_documents import bind_exact_authority_documents
from .genesis_authority_types import (
    GENESIS_R1_STRUCTURAL_STATUS,
    REMAINING_GENESIS_R1_BLOCKERS,
    GenesisAuthorityBindingV2,
)
from .genesis_authority_validation import (
    GenesisAuthorityBindingError,
    bind_genesis_current_card,
    bind_genesis_manifest_roles,
    bind_operation_snapshot,
    revalidate_genesis_inputs,
    snapshot_manifest_bytes,
)
from .genesis_execution_policy import bind_initialize_operation_policy_v2
from .genesis_generation_profile import (
    GENESIS_R1_PROFILE,
    select_disjoint_generation_profile,
)
from .genesis_policy_bundle import bind_genesis_policy_bundle
from .origin_requirements import R1_PROFILE_REQUIREMENTS


def bind_genesis_r1_authority(inputs: object) -> GenesisAuthorityBindingV2:
    """Bind all R1 structure while holding runtime and execution gates closed."""
    inputs = revalidate_genesis_inputs(inputs)
    try:
        selection = select_disjoint_generation_profile(inputs.commit)
    except RuntimeError as exc:
        raise GenesisAuthorityBindingError("genesis R1 profile is invalid") from exc
    if selection.profile != GENESIS_R1_PROFILE:
        raise GenesisAuthorityBindingError("genesis R1 profile was not selected")
    artifact_bytes = snapshot_manifest_bytes(inputs.commit, inputs.artifact_bytes)
    bind_exact_authority_documents(inputs, selection.groups, artifact_bytes)
    bind_genesis_policy_bundle(inputs, selection.groups, artifact_bytes)
    bind_genesis_current_card(inputs)
    bind_operation_snapshot(inputs)
    bind_genesis_manifest_roles(inputs, selection.groups)
    compatibility = bind_initialize_operation_policy_v2(
        inputs.operation, inputs.initialization_policy
    )
    if not compatibility.policy_compatible or compatibility.execution_authorized:
        raise GenesisAuthorityBindingError("initialization policy gate is invalid")
    return GenesisAuthorityBindingV2(
        GENESIS_R1_STRUCTURAL_STATUS,
        R1_PROFILE_REQUIREMENTS,
        REMAINING_GENESIS_R1_BLOCKERS,
        tuple(selection.groups),
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


def require_genesis_execution_authorized(binding: object) -> None:
    """Never promote structural genesis evidence to an execution capability."""
    if type(binding) is not GenesisAuthorityBindingV2:
        raise GenesisAuthorityBindingError("genesis binding result is invalid")
    raise GenesisAuthorityBindingError(
        "genesis R1 structural binding is not execution-authorized"
    )
