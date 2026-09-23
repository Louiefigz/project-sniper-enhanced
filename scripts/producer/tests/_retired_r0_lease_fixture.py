"""Inert TEST historical readers and DTO wiring; never current render authority.

No source validator is patched. Static evidence readers run directly, and
current-policy refusal is exercised separately through the public boundaries.
"""
from __future__ import annotations

import contextlib
import copy
from unittest.mock import patch

from headless import approved_parent_loader as loader
from headless.generation_reader import read_current_generation
from headless.repair_intent import RepairApplication, approved_plan_digest
from _approved_parent_loader_values import canonical


def static_lease(generation: object) -> loader.ApprovedParentLeaseV1:
    """Read immutable historical evidence without claiming current clip admission."""
    store = loader.GenerationArtifactStoreV1.from_resolved(generation)
    artifacts = loader.class_artifacts(loader.verify_r0_generation_profile(generation.commit))
    approved_ref, descriptor = loader._descriptor(store, artifacts)
    loader.validate_descriptor_identity(descriptor, generation.commit)
    loader.validate_descriptor_artifacts(descriptor, artifacts, store)
    loader.validate_remaining_artifacts(artifacts, store)
    policies = loader._policies(store, artifacts)
    raw = store.read(descriptor.plan.artifact, 16 * 1024 * 1024)
    quality = loader._quality_records(store, descriptor)
    evidence = loader.load_approved_parent_quality_evidence(store, descriptor, quality, raw)
    verification_ref, verification = loader._verification(store, artifacts, approved_ref)
    ref = loader._lineage_ref(generation, descriptor.plan.approved_plan_digest)
    parent = loader._parent(ref, verification_ref, descriptor, raw)
    loader.validate_approved_parent(parent)
    sealed = loader.ApprovedGenerationEvidenceV1(approved_ref, descriptor,
        verification_ref, verification, policies, quality, evidence, artifacts)
    return loader.ApprovedParentLeaseV1(parent, sealed, generation, store)


@contextlib.contextmanager
def historical_lease(fixture: object):
    """Exercise real scoped static files with a TEST lease, never execute it."""
    with read_current_generation(str(fixture.authority), str(fixture.materialization)) as generation:
        lease = static_lease(generation)
    try:
        yield lease
    finally:
        lease.close()


def candidate_metadata(operation: object, lease: object) -> RepairApplication:
    """Build a synthetic historical application for orchestration units only."""
    plan = copy.deepcopy(lease.parent.decoded_plan())
    before = approved_plan_digest(plan)
    plan['graphicsTrack'][0]['spec']['accent'] = operation.quality_pass.repair.value
    return RepairApplication(canonical(plan), before, approved_plan_digest(plan),
        ('/graphicsTrack/0/spec/accent',), operation.quality_pass.repair.graphic_id,
        operation.quality_pass.repair_policy_id)


@contextlib.contextmanager
def inert_preflight_inputs(fixture: object):
    """Unit-test preflight lifetime/result wiring, not loader or repair approval."""
    with patch('headless.quality_pass_preflight.load_current_approved_parent',
               side_effect=lambda *args: historical_lease(fixture)), patch(
                   'headless.quality_pass_preflight._candidate', side_effect=candidate_metadata):
        yield
