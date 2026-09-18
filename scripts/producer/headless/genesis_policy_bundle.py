"""Exact policy-document closure for the genesis R1 structural binder."""

from __future__ import annotations

from collections.abc import Mapping

from .artifact_contract import ArtifactRefV1
from .generation_policy_documents import current_fallback_policy
from .genesis_authority_types import GenesisAuthorityInputsV2
from .genesis_authority_validation import GenesisAuthorityBindingError
from .operation_wire import canonical
from .quality_policy import current_deterministic_quality_policy
from .repair_intent import current_accent_policy


def _sole_ref(groups: Mapping, artifact_class: str) -> ArtifactRefV1:
    rows = groups.get(artifact_class, ())
    if len(rows) != 1:
        raise GenesisAuthorityBindingError(
            f"genesis policy class is not singular: {artifact_class}"
        )
    row = rows[0]
    return ArtifactRefV1(row.path, row.sha256, row.size_bytes)


def _repair_policy_bytes() -> bytes:
    repair = current_accent_policy()
    return canonical(
        {
            "schemaVersion": 1,
            "effectClass": "SECTION_MARKER_ACCENT_V1",
            "allowedValues": list(repair.allowed_values),
        }
    )


def _expected_documents(inputs: GenesisAuthorityInputsV2) -> tuple:
    return (
        (
            "initialization-execution-policy-v2",
            inputs.initialization_policy.document_json,
        ),
        ("repair-policy-v1", _repair_policy_bytes()),
        (
            "quality-policy-v1",
            current_deterministic_quality_policy().document_json,
        ),
        ("fallback-policy-v1", current_fallback_policy().document_json),
    )


def bind_genesis_policy_bundle(
    inputs: GenesisAuthorityInputsV2,
    groups: Mapping,
    artifact_bytes: Mapping[str, bytes],
) -> None:
    """Bind all four policy IDs to exact current committed policy documents."""
    for artifact_class, expected_raw in _expected_documents(inputs):
        ref = _sole_ref(groups, artifact_class)
        if artifact_bytes[ref.relative_path] != expected_raw:
            raise GenesisAuthorityBindingError(
                f"genesis policy bytes are stale: {artifact_class}"
            )
    repair = current_accent_policy()
    quality = current_deterministic_quality_policy()
    fallback = current_fallback_policy()
    expected_ids = (
        inputs.initialization_policy.policy_id,
        repair.policy_id,
        quality.policy_id,
        fallback.policy_id,
    )
    commit = inputs.commit
    actual_ids = (
        commit.execution_policy_id,
        commit.repair_policy_id,
        commit.quality_policy_id,
        commit.fallback_policy_id,
    )
    if actual_ids != expected_ids:
        raise GenesisAuthorityBindingError("genesis policy IDs are stale")
