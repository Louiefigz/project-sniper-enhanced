"""Byte-backed lease for the current approved deterministic-MP4 parent."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from .approved_parent_binding import (
    class_artifacts,
    validate_descriptor_artifacts,
    validate_descriptor_identity,
    validate_remaining_artifacts,
)
from .approved_parent_media import (
    ApprovedParentVerifierContextV1,
    validate_parent_clips,
    validate_parent_media,
)
from .approved_parent_loader_evidence import (
    ApprovedParentQualityEvidenceAuthorityV1,
    load_approved_parent_quality_evidence,
)
from .approved_parent_quality_binding import validate_approved_parent_quality_chain
from .approved_parent_quality_receipts import (
    ApprovedParentQualityRecordsV1,
    parse_cover_proof_v1,
    parse_critic_receipt_v1,
    parse_final_approval_v3,
    parse_qc_receipt_v1,
)
from .approved_parent_schema import (
    ApprovedParentDescriptorV1,
    parse_approved_parent_descriptor,
    validate_approved_parent_descriptor,
)
from .artifact_contract import ArtifactRefV1
from .generation_artifact_store import GenerationArtifactStoreV1
from .generation_policy_documents import (
    GENERATION_POLICY_CLASSES,
    GenerationPolicyDocumentsV1,
    validate_generation_policy_documents,
)
from .generation_profile import verify_r0_generation_profile
from .generation_reader import ResolvedGenerationV1, read_current_generation
from .generation_verification import (
    GenerationVerificationV1,
    parse_generation_verification,
    validate_generation_verification,
)
from .quality_pass_contract import ApprovedParentV1, validate_approved_parent
from .repair_intent import ParentRefV1, validate_parent_ref

_JSON_LIMIT = 16 * 1024 * 1024


class ApprovedParentLoadError(RuntimeError):
    """The current generation cannot authorize a quality-pass parent."""


@dataclass(frozen=True)
class ApprovedGenerationEvidenceV1:
    """Verified authority-card and manifest evidence retained beside the parent."""

    descriptor_artifact: ArtifactRefV1
    descriptor: ApprovedParentDescriptorV1
    verification_artifact: ArtifactRefV1
    verification: GenerationVerificationV1
    policies: GenerationPolicyDocumentsV1
    quality_records: ApprovedParentQualityRecordsV1
    quality_evidence: ApprovedParentQualityEvidenceAuthorityV1
    class_artifacts: Mapping[str, tuple[ArtifactRefV1, ...]]


@dataclass
class ApprovedParentLeaseV1:
    """Scoped parent and exact-ref resolver over one materialized generation."""

    parent: ApprovedParentV1
    evidence: ApprovedGenerationEvidenceV1
    generation: ResolvedGenerationV1
    _store: GenerationArtifactStoreV1
    _active: bool = True

    def resolve_parent(self, ref: ParentRefV1) -> ApprovedParentV1:
        """Resolve only the expected current parent while this lease is active."""
        if not self._active or ref != self.parent.ref:
            raise ApprovedParentLoadError("approved-parent lease is stale or closed")
        return self.parent

    def resolve_artifact(self, ref: ArtifactRefV1) -> str:
        """Resolve one exact manifest ref while this lease is active."""
        if not self._active:
            raise ApprovedParentLoadError("approved-parent lease is closed")
        return self._store.resolve(ref)

    def read_artifact(self, ref: ArtifactRefV1, limit: int) -> bytes:
        """Read one exact manifest artifact through the scoped stable store."""
        if not self._active:
            raise ApprovedParentLoadError("approved-parent lease is closed")
        return self._store.read(ref, limit)

    def close(self) -> None:
        """Revoke parent and artifact resolution after the execution scope."""
        self._active = False


def _lineage_ref(generation: ResolvedGenerationV1, plan_digest: str) -> ParentRefV1:
    current, commit = generation.current, generation.commit
    prior = commit.expected_parent
    valid_sequence = (
        current.publication_seq == 1
        if prior is None
        else (
            current.publication_seq == prior.publication_seq + 1
            and prior.generation_id != commit.generation_id
        )
    )
    if not valid_sequence:
        raise ApprovedParentLoadError("published generation sequence breaks lineage")
    ref = ParentRefV1(
        current.authority_id,
        current.publication_seq,
        current.generation_id,
        current.commit_digest,
        plan_digest,
    )
    try:
        validate_parent_ref(ref)
    except RuntimeError as exc:
        raise ApprovedParentLoadError(str(exc)) from exc
    return ref


def _parent(
    ref: ParentRefV1,
    verification: ArtifactRefV1,
    descriptor: ApprovedParentDescriptorV1,
    plan_json: bytes,
) -> ApprovedParentV1:
    artifacts = descriptor.graphics
    return ApprovedParentV1(
        ref=ref,
        generation_verification=verification,
        repair_policy_id=descriptor.policies.repair_policy_id,
        quality_policy_id=descriptor.policies.quality_policy_id,
        plan_json=plan_json,
        plan_artifact=descriptor.plan.artifact,
        plan_content_hash=descriptor.plan.content_hash,
        base=descriptor.base.media,
        base_plan=descriptor.base.plan_artifact,
        base_receipt=descriptor.base.receipt,
        base_projection_digest=descriptor.plan.base_projection_digest,
        timeline_map=descriptor.base.timeline_map,
        prebound_clips=artifacts.prebound_clips,
        graphics_assets=artifacts.assets,
        final=descriptor.output.final,
        assembly_receipt=descriptor.output.assembly_receipt,
        cover=descriptor.output.cover,
        cover_proof=descriptor.output.cover_proof,
        qc_receipt=descriptor.quality.qc_receipt,
        final_approval=descriptor.quality.final_approval,
    )


def _descriptor(
    store: GenerationArtifactStoreV1,
    artifacts: Mapping[str, tuple[ArtifactRefV1, ...]],
) -> tuple[ArtifactRefV1, ApprovedParentDescriptorV1]:
    ref = artifacts["approved-parent-v1"][0]
    parsed = parse_approved_parent_descriptor(store.read(ref, _JSON_LIMIT))
    validate_approved_parent_descriptor(parsed)
    return ref, parsed


def _verification(
    store: GenerationArtifactStoreV1,
    artifacts: Mapping[str, tuple[ArtifactRefV1, ...]],
    approved: ArtifactRefV1,
) -> tuple[ArtifactRefV1, GenerationVerificationV1]:
    ref = artifacts["generation-verification-v1"][0]
    parsed = parse_generation_verification(store.read(ref, _JSON_LIMIT))
    validate_generation_verification(parsed, store.generation.commit, approved)
    return ref, parsed


def _policies(
    store: GenerationArtifactStoreV1,
    artifacts: Mapping[str, tuple[ArtifactRefV1, ...]],
) -> GenerationPolicyDocumentsV1:
    raw = {
        artifact_class: store.read(artifacts[artifact_class][0], _JSON_LIMIT)
        for artifact_class in GENERATION_POLICY_CLASSES
    }
    return validate_generation_policy_documents(store.generation.commit, raw)


def _quality_records(
    store: GenerationArtifactStoreV1,
    descriptor: ApprovedParentDescriptorV1,
) -> ApprovedParentQualityRecordsV1:
    records = ApprovedParentQualityRecordsV1(
        parse_cover_proof_v1(store.read(descriptor.output.cover_proof, _JSON_LIMIT)),
        parse_qc_receipt_v1(store.read(descriptor.quality.qc_receipt, _JSON_LIMIT)),
        tuple(
            parse_critic_receipt_v1(store.read(item.artifact, _JSON_LIMIT))
            for item in descriptor.quality.critics
        ),
        parse_final_approval_v3(
            store.read(descriptor.quality.final_approval, _JSON_LIMIT)
        ),
    )
    validate_approved_parent_quality_chain(descriptor, store.generation.commit, records)
    return records


def _load(
    generation: ResolvedGenerationV1,
    expected_parent: ParentRefV1,
    context: ApprovedParentVerifierContextV1,
) -> ApprovedParentLeaseV1:
    try:
        validate_parent_ref(expected_parent)
        store = GenerationArtifactStoreV1.from_resolved(generation)
        groups = verify_r0_generation_profile(generation.commit)
        artifacts = class_artifacts(groups)
        approved_ref, descriptor = _descriptor(store, artifacts)
        if approved_ref.relative_path != generation.commit.approved_parent_path:
            raise ApprovedParentLoadError("approved-parent path differs from commit")
        validate_descriptor_identity(descriptor, generation.commit)
        validate_descriptor_artifacts(descriptor, artifacts, store)
        validate_remaining_artifacts(artifacts, store)
        policies = _policies(store, artifacts)
        plan_json = store.read(descriptor.plan.artifact, _JSON_LIMIT)
        quality_records = _quality_records(store, descriptor)
        quality_evidence = load_approved_parent_quality_evidence(
            store, descriptor, quality_records, plan_json
        )
        verification_ref, verification = _verification(store, artifacts, approved_ref)
        ref = _lineage_ref(generation, descriptor.plan.approved_plan_digest)
        if ref != expected_parent:
            raise ApprovedParentLoadError("current generation is not expected parent")
        parent = _parent(ref, verification_ref, descriptor, plan_json)
        validate_approved_parent(parent)
        base = validate_parent_media(descriptor, store, context)
        validate_parent_clips(descriptor, store, parent.decoded_plan(), base)
        evidence = ApprovedGenerationEvidenceV1(
            approved_ref,
            descriptor,
            verification_ref,
            verification,
            policies,
            quality_records,
            quality_evidence,
            artifacts,
        )
        return ApprovedParentLeaseV1(parent, evidence, generation, store)
    except ApprovedParentLoadError:
        raise
    except RuntimeError as exc:
        raise ApprovedParentLoadError(str(exc)) from exc


@contextlib.contextmanager
def load_current_approved_parent(
    authority_root: str,
    materialization_root: str,
    expected_parent: ParentRefV1,
    context: ApprovedParentVerifierContextV1,
) -> Iterator[ApprovedParentLeaseV1]:
    """Read, semantically verify, and scope one current approved-parent lease."""
    try:
        with read_current_generation(
            authority_root, materialization_root
        ) as generation:
            lease = _load(generation, expected_parent, context)
    except ApprovedParentLoadError:
        raise
    except RuntimeError as exc:
        raise ApprovedParentLoadError(str(exc)) from exc
    try:
        yield lease
    finally:
        lease.close()
