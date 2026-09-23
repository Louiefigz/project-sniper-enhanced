"""Inert historical R0 diagnostic DTOs for ledger/promotion unit tests only.

These values are never persisted as render evidence or passed to an executor.
The actual retired-parent rejection is tested separately without this seam.
No source, quality, or runtime policy validator is replaced by this helper.
"""
from __future__ import annotations

import dataclasses

from headless.operation_contract import parse_headless_mp4_operation_v1
from headless.quality_pass_composition_types import (
    CompositionAuthorityRequirementV1,
    NonAuthorizingQualityPassCompositionV1,
    QualityPassCompositionInspectionRequestV1,
    R0_GENESIS_BLOCKED,
)


_REQUIREMENTS = (
    "DURABLE_OPERATION_ADMISSION_BINDING",
    "UNIT_ENROLLMENT_AUTHORITY",
    "R1_INITIALIZATION_ORIGIN_AUTHORITY",
    "RECURSIVE_LINEAGE_AND_GENESIS_ORIGIN",
    "OPERATION_RUNTIME_EXECUTION_AND_CHILD_SEAL",
    "ACTIVE_FENCE_RECHECK",
    "FENCED_PUBLICATION_AND_TERMINAL_SEAL",
)


def historical_diagnostics(
    request: QualityPassCompositionInspectionRequestV1,
) -> NonAuthorizingQualityPassCompositionV1:
    """Supply a labeled metadata seam; authenticate neither media nor execution."""
    from headless.admitted_quality_pass_composition_types import ADMISSION_BINDING_REQUIREMENT
    operation = parse_headless_mp4_operation_v1(request.operation_json)
    codes = (ADMISSION_BINDING_REQUIREMENT, *_REQUIREMENTS[1:])
    return NonAuthorizingQualityPassCompositionV1(
        status=R0_GENESIS_BLOCKED,
        operation_digest=operation.operation_digest,
        unit_id=operation.unit_id,
        expected_parent=operation.expected_parent,
        current_commit_digest=operation.expected_parent.commit_digest,
        candidate_plan_digest="a" * 64,
        candidate_plan_sha256="b" * 64,
        closed_checks=("TEST_INERT_HISTORICAL_METADATA",),
        unresolved_authority=tuple(CompositionAuthorityRequirementV1(
            code, "TEST synthetic unresolved requirement; never executable") for code in codes),
        parent_profile="legacy-r0-genesis-specimen",
        lineage_status=None,
        lineage_edges_required=0,
        lineage_edges_verified=0,
        parent_runtime_status=None,
        parent_quality_runtime_reobserved=False,
        recursive_assembly_verified=False,
        genesis_origin_verified=False,
        durable_admission_bound=False,
        operation_runtime_verified=False,
        fence_rechecked=False,
        execution_authorized=False,
        publication_authorized=False,
    )


def assert_retired_inspection(case: object, ledgers: tuple[str, ...]) -> None:
    """Check the real source boundary without substituting historical diagnostics."""
    from unittest.mock import patch
    from headless.admitted_quality_pass_composition_types import AdmittedQualityPassCompositionError
    from headless.enrolled_admitted_quality_pass_types import EnrolledAdmittedQualityPassCompositionError
    from headless.quality_pass_composition_inspection import inspect_quality_pass_composition
    fixture = case.fixture
    before = {path: path.read_bytes() for path in fixture.generation.rglob('*') if path.is_file()}
    current = (fixture.authority / 'CURRENT').read_bytes()
    authority_before = {path: path.read_bytes() for path in fixture.authority.rglob('*') if path.is_file()}
    with patch('headless.admitted_quality_pass_composition.inspect_quality_pass_composition',
               side_effect=inspect_quality_pass_composition), patch('subprocess.Popen') as process:
        with case.assertRaisesRegex((AdmittedQualityPassCompositionError,
                                     EnrolledAdmittedQualityPassCompositionError), 'section-marker.*retired'):
            case._inspect(case._request())
    process.assert_not_called()
    case.assertEqual({path: path.read_bytes() for path in fixture.generation.rglob('*')
                      if path.is_file()}, before)
    case.assertEqual((fixture.authority / 'CURRENT').read_bytes(), current)
    for name in ledgers:
        case.assertFalse((fixture.authority / name).exists())
    case.assertEqual({path: path.read_bytes() for path in fixture.authority.rglob('*')
                      if path.is_file()}, authority_before)
    case.assertEqual(len(list((fixture.authority / 'generations').iterdir())), 1)

def _leaves(value: object) -> tuple[object, ...]:
    if dataclasses.is_dataclass(value):
        rows = tuple(getattr(value, field.name) for field in dataclasses.fields(value))
        return tuple(item for row in rows for item in _leaves(row))
    if type(value) in {tuple, list}:
        return tuple(item for row in value for item in _leaves(row))
    return (value,)
