"""Reparsed immutable inputs for runtime capability structural binding."""

from __future__ import annotations

from dataclasses import dataclass

from .approved_parent_assembly_receipt import (
    AssemblyReceiptV1,
    parse_assembly_receipt_v1,
)
from .approved_parent_quality_evidence import (
    ApprovedParentQualityEvidenceV1,
    parse_approved_parent_quality_evidence_v1,
)
from .approved_parent_schema import (
    ApprovedParentDescriptorV1,
    parse_approved_parent_descriptor,
)
from .generation_schema import GenerationCommitV1, parse_generation_commit
from .quality_receipt_json import same_typed_value
from .runtime_capability_manifest import (
    RuntimeCapabilityManifestV1,
    parse_runtime_capability_manifest_v1,
)


class RuntimeCapabilityInputError(RuntimeError):
    """A runtime binding input was not reconstructed from canonical bytes."""


@dataclass(frozen=True)
class RuntimeCapabilityBindingV1:
    """Loader-ready already-read records for one immutable R0 generation."""

    descriptor: ApprovedParentDescriptorV1
    commit: GenerationCommitV1
    runtime_manifest: RuntimeCapabilityManifestV1
    assembly_receipt: AssemblyReceiptV1
    quality_evidence: ApprovedParentQualityEvidenceV1


@dataclass(frozen=True)
class CheckedRuntimeCapabilityV1:
    descriptor: ApprovedParentDescriptorV1
    commit: GenerationCommitV1
    runtime: RuntimeCapabilityManifestV1
    assembly: AssemblyReceiptV1
    evidence: ApprovedParentQualityEvidenceV1


def _parse_descriptor(value: object) -> ApprovedParentDescriptorV1:
    if type(value) is not ApprovedParentDescriptorV1:
        raise RuntimeCapabilityInputError("runtime descriptor is invalid")
    try:
        parsed = parse_approved_parent_descriptor(value.document_json)
    except RuntimeError as exc:
        raise RuntimeCapabilityInputError(
            "runtime descriptor bytes are invalid"
        ) from exc
    if not same_typed_value(value, parsed):
        raise RuntimeCapabilityInputError("runtime descriptor is forged")
    return parsed


def _parse_commit(value: object) -> GenerationCommitV1:
    if type(value) is not GenerationCommitV1:
        raise RuntimeCapabilityInputError("runtime commit is invalid")
    try:
        parsed = parse_generation_commit(value.document_json)
    except RuntimeError as exc:
        raise RuntimeCapabilityInputError("runtime commit bytes are invalid") from exc
    if not same_typed_value(value, parsed):
        raise RuntimeCapabilityInputError("runtime commit is forged")
    return parsed


def _parse_runtime(value: object) -> RuntimeCapabilityManifestV1:
    if type(value) is not RuntimeCapabilityManifestV1:
        raise RuntimeCapabilityInputError("runtime manifest is invalid")
    try:
        parsed = parse_runtime_capability_manifest_v1(value.document_json)
    except RuntimeError as exc:
        raise RuntimeCapabilityInputError("runtime manifest bytes are invalid") from exc
    if not same_typed_value(value, parsed):
        raise RuntimeCapabilityInputError("runtime manifest is forged")
    return parsed


def _parse_assembly(value: object) -> AssemblyReceiptV1:
    if type(value) is not AssemblyReceiptV1:
        raise RuntimeCapabilityInputError("runtime assembly receipt is invalid")
    try:
        parsed = parse_assembly_receipt_v1(value.document_json)
    except RuntimeError as exc:
        raise RuntimeCapabilityInputError("runtime assembly bytes are invalid") from exc
    if not same_typed_value(value, parsed):
        raise RuntimeCapabilityInputError("runtime assembly receipt is forged")
    return parsed


def _parse_evidence(value: object) -> ApprovedParentQualityEvidenceV1:
    if type(value) is not ApprovedParentQualityEvidenceV1:
        raise RuntimeCapabilityInputError("runtime quality evidence is invalid")
    try:
        parsed = parse_approved_parent_quality_evidence_v1(
            value.full_decode.document_json,
            value.effect_proof.document_json,
            value.audit.document_json,
        )
    except (AttributeError, RuntimeError) as exc:
        raise RuntimeCapabilityInputError("runtime evidence bytes are invalid") from exc
    if not same_typed_value(value, parsed):
        raise RuntimeCapabilityInputError("runtime quality evidence is forged")
    return parsed


def checked_runtime_capability(value: object) -> CheckedRuntimeCapabilityV1:
    """Reparse every binding input and reject direct-construction forgeries."""
    if type(value) is not RuntimeCapabilityBindingV1:
        raise RuntimeCapabilityInputError("runtime binding input is invalid")
    return CheckedRuntimeCapabilityV1(
        _parse_descriptor(value.descriptor),
        _parse_commit(value.commit),
        _parse_runtime(value.runtime_manifest),
        _parse_assembly(value.assembly_receipt),
        _parse_evidence(value.quality_evidence),
    )
