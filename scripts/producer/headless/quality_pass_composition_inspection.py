"""Lifetime-safe, non-authorizing composition inspection for quality-pass."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from .approved_parent_assembly_binding import bind_approved_parent_assembly_receipt
from .approved_parent_assembly_receipt import (
    AssemblyReceiptV1,
    parse_assembly_receipt_v1,
)
from .approved_parent_assembly_types import (
    IMMEDIATE_PARENT_AND_BASE_CONTINUITY,
    AssemblyBindingReportV1,
)
from .approved_parent_media import ApprovedParentVerifierContextV1
from .approved_parent_schema import ApprovedParentDescriptorV1
from .assembly_lineage_binding import bind_assembly_lineage_continuity
from .generation_schema import GenerationCommitV1
from .historical_generation_resolver import resolve_historical_generation
from .quality_pass_preflight import (
    QualityPassPreflightV1,
    inspect_quality_pass_preflight,
)
from .quality_pass_composition_types import (
    R0_GENESIS_BLOCKED,
    STRUCTURAL_CHILD_STATUS,
    CompositionAuthorityRequirementV1,
    NonAuthorizingQualityPassCompositionV1,
    QualityPassCompositionInspectionError,
    QualityPassCompositionInspectionRequestV1,
)
from .runtime_capability_binding import (
    RuntimeCapabilityBindingV1,
    RuntimeCapabilityBindingReportV1,
    bind_runtime_capability_manifest,
)
from .runtime_capability_manifest import parse_runtime_capability_manifest_v1

_JSON_LIMIT = 16 * 1024 * 1024

__all__ = (
    "R0_GENESIS_BLOCKED",
    "STRUCTURAL_CHILD_STATUS",
    "CompositionAuthorityRequirementV1",
    "NonAuthorizingQualityPassCompositionV1",
    "QualityPassCompositionInspectionError",
    "QualityPassCompositionInspectionRequestV1",
    "inspect_quality_pass_composition",
    "require_render_start_authorized",
)


@dataclass(frozen=True)
class _ChildDiagnosticsV1:
    lineage_status: str
    edges_required: int
    edges_verified: int
    runtime_status: str
    requirements: tuple[CompositionAuthorityRequirementV1, ...]


@dataclass(frozen=True)
class _ParentReportsV1:
    descriptor: ApprovedParentDescriptorV1
    commit: GenerationCommitV1
    assembly: AssemblyReceiptV1
    assembly_report: AssemblyBindingReportV1
    runtime_report: RuntimeCapabilityBindingReportV1


def _canonical_root(value: object, label: str) -> str:
    valid = type(value) is str and value and os.path.isabs(value)
    try:
        canonical = os.path.realpath(value) if valid else None
    except OSError:
        canonical = None
    if not valid or canonical != value:
        raise QualityPassCompositionInspectionError(f"{label} is not canonical")
    return value


def _checked_request(value: object) -> QualityPassCompositionInspectionRequestV1:
    if type(value) is not QualityPassCompositionInspectionRequestV1:
        raise QualityPassCompositionInspectionError("inspection request is invalid")
    roots = (
        _canonical_root(value.authority_root, "authority root"),
        _canonical_root(value.current_materialization_root, "current materialization"),
        _canonical_root(
            value.historical_materialization_root, "historical materialization"
        ),
    )
    valid = len(set(roots)) == 3 and type(value.operation_json) is bytes
    valid = valid and type(value.verifier) is ApprovedParentVerifierContextV1
    if not valid:
        raise QualityPassCompositionInspectionError("inspection inputs alias or differ")
    return value


def _requirement(code: str, proof: str) -> CompositionAuthorityRequirementV1:
    return CompositionAuthorityRequirementV1(code, proof)


def _requirements(
    preflight: QualityPassPreflightV1,
    extra: tuple[CompositionAuthorityRequirementV1, ...],
    closed: tuple[str, ...] = (),
) -> tuple[CompositionAuthorityRequirementV1, ...]:
    rows = (
        tuple(
            _requirement(item.code, item.required_proof)
            for item in preflight.unresolved_authority
        )
        + extra
    )
    unique: dict[str, CompositionAuthorityRequirementV1] = {}
    for row in rows:
        if row.code not in closed:
            unique.setdefault(row.code, row)
    return tuple(unique.values())


def _parent_reports(preflight: QualityPassPreflightV1) -> _ParentReportsV1:
    lease, descriptor = preflight.parent, preflight.parent.evidence.descriptor
    commit = lease.generation.commit
    assembly = parse_assembly_receipt_v1(
        lease.read_artifact(descriptor.output.assembly_receipt, _JSON_LIMIT)
    )
    runtime = parse_runtime_capability_manifest_v1(
        lease.read_artifact(
            descriptor.provenance.runtime_capability_manifest, _JSON_LIMIT
        )
    )
    assembly_report = bind_approved_parent_assembly_receipt(
        descriptor, commit, assembly
    )
    runtime_report = bind_runtime_capability_manifest(
        RuntimeCapabilityBindingV1(
            descriptor,
            commit,
            runtime,
            assembly,
            lease.evidence.quality_evidence.evidence,
        )
    )
    return _ParentReportsV1(
        descriptor, commit, assembly, assembly_report, runtime_report
    )


def _child_diagnostics(
    request: QualityPassCompositionInspectionRequestV1,
    preflight: QualityPassPreflightV1,
) -> _ChildDiagnosticsV1:
    reports = _parent_reports(preflight)
    parent = reports.commit.expected_parent
    if parent is None:
        raise QualityPassCompositionInspectionError(
            "child diagnostics require a parent"
        )
    with resolve_historical_generation(
        request.authority_root, request.historical_materialization_root, parent
    ) as historical:
        lineage = bind_assembly_lineage_continuity(
            historical, reports.descriptor, reports.commit, reports.assembly
        )
    extras = tuple(
        _requirement(item.code, item.required_proof)
        for item in (
            *lineage.unresolved_authority,
            *reports.assembly_report.unresolved_authority,
            *reports.runtime_report.unresolved_authority,
        )
    )
    return _ChildDiagnosticsV1(
        lineage.status,
        lineage.assembly_edges_required,
        lineage.assembly_edges_verified,
        reports.runtime_report.status,
        extras,
    )


def _closed_checks(child: _ChildDiagnosticsV1 | None) -> tuple[str, ...]:
    checks = (
        "OPERATION_POLICY_BOUND",
        "CURRENT_PARENT_BYTES_BOUND",
        "REPAIR_CAS_APPLIED",
        "PARENT_SEALED_QUALITY_CLAIMS_BOUND",
    )
    if child is None:
        return checks
    return checks + (
        "IMMEDIATE_PARENT_BASE_EDGE_BOUND",
        "PARENT_STATIC_RUNTIME_CLAIMS_BOUND",
    )


def _result(
    preflight: QualityPassPreflightV1,
    child: _ChildDiagnosticsV1 | None,
) -> NonAuthorizingQualityPassCompositionV1:
    operation, lease = preflight.operation, preflight.parent
    application = preflight.candidate
    genesis = lease.generation.commit.expected_parent is None
    extra = (
        (
            _requirement(
                "DISJOINT_R1_PARENT_LOADER_AND_HISTORY",
                "load a genesis R1 card and dispatch R1 at every selected-chain tail",
            ),
        )
        if child is None
        else child.requirements
    )
    closed_requirements = (
        ()
        if child is None
        else (
            "SELECTED_PARENT_LINEAGE_CONTINUITY",
            IMMEDIATE_PARENT_AND_BASE_CONTINUITY,
        )
    )
    return NonAuthorizingQualityPassCompositionV1(
        R0_GENESIS_BLOCKED if genesis else STRUCTURAL_CHILD_STATUS,
        operation.operation_digest,
        operation.unit_id,
        operation.expected_parent,
        lease.generation.commit.commit_digest,
        application.after_digest,
        hashlib.sha256(application.plan_json).hexdigest(),
        _closed_checks(child),
        _requirements(preflight, extra, closed_requirements),
        "legacy-r0-genesis-specimen" if genesis else "quality-pass-r0",
        None if child is None else child.lineage_status,
        0 if child is None else child.edges_required,
        0 if child is None else child.edges_verified,
        None if child is None else child.runtime_status,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    )


def inspect_quality_pass_composition(
    request: object,
) -> NonAuthorizingQualityPassCompositionV1:
    """Inspect exact parent/candidate structure and close every lease before return."""
    checked = _checked_request(request)
    try:
        with inspect_quality_pass_preflight(
            checked.authority_root,
            checked.current_materialization_root,
            checked.operation_json,
            checked.verifier,
        ) as preflight:
            child = (
                None
                if preflight.parent.generation.commit.expected_parent is None
                else _child_diagnostics(checked, preflight)
            )
            return _result(preflight, child)
    except QualityPassCompositionInspectionError:
        raise
    except RuntimeError as exc:
        raise QualityPassCompositionInspectionError(str(exc)) from exc


def require_render_start_authorized(value: object) -> None:
    """Reject all current diagnostics, including forged authorization booleans."""
    raise QualityPassCompositionInspectionError(
        "quality-pass composition is not render-start authority"
    )
