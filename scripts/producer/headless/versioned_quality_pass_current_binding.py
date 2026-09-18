"""Non-authorizing current-generation binder for quality-pass authority V2."""

from __future__ import annotations

from .approved_parent_assembly_types import UNRESOLVED_ASSEMBLY_AUTHORITY
from .versioned_quality_pass_current_validation import (
    QualityPassCurrentBindingV2Error,
    revalidate_quality_pass_inputs,
    validate_quality_pass_card_values,
    validate_quality_pass_identity,
    validate_quality_pass_observed_shape,
)
from .versioned_quality_pass_manifest import bind_quality_pass_manifest
from .versioned_quality_pass_profile import verify_quality_pass_r1_profile
from .versioned_quality_pass_types import (
    QUALITY_PASS_V2_CURRENT_STATUS,
    QualityPassCurrentBindingV2,
)


def bind_quality_pass_current_authority_v2(
    value: object,
) -> QualityPassCurrentBindingV2:
    """Bind exact current V2 structure without parent/runtime authorization."""
    inputs = revalidate_quality_pass_inputs(value)
    try:
        groups = verify_quality_pass_r1_profile(inputs.commit)
    except RuntimeError as exc:
        raise QualityPassCurrentBindingV2Error(
            "quality-pass profile is invalid"
        ) from exc
    validate_quality_pass_identity(inputs)
    validate_quality_pass_card_values(inputs)
    validate_quality_pass_observed_shape(inputs)
    if len(inputs.approved_card.graphics.assets) != 1:
        raise QualityPassCurrentBindingV2Error(
            "quality-pass V2 graphic count is invalid"
        )
    if len(inputs.assembly_receipt.compositor.alpha_occupancy) != 1:
        raise QualityPassCurrentBindingV2Error(
            "quality-pass V2 alpha proof count is invalid"
        )
    assembly = bind_quality_pass_manifest(inputs, groups)
    return QualityPassCurrentBindingV2(
        QUALITY_PASS_V2_CURRENT_STATUS,
        assembly,
        inputs.assembly_receipt.parent_authority,
        UNRESOLVED_ASSEMBLY_AUTHORITY,
        False,
        False,
        False,
    )


def require_quality_pass_v2_execution_authorized(value: object) -> None:
    """Never convert current-card or parent evidence into runtime authority."""
    if type(value) is not QualityPassCurrentBindingV2:
        raise QualityPassCurrentBindingV2Error("quality-pass binding is invalid")
    raise QualityPassCurrentBindingV2Error(
        "quality-pass V2 structural binding is not execution-authorized"
    )
