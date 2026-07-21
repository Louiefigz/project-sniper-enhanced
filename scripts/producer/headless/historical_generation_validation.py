"""Semantic validation shared by source and materialized historical nodes."""

from __future__ import annotations

import json
from typing import Protocol

from fingerprints import base_plan_digest, plan_content_hash

from .approved_parent_binding import (
    class_artifacts,
    validate_descriptor_artifacts,
    validate_descriptor_identity,
    validate_remaining_artifacts,
)
from .approved_parent_schema import (
    ApprovedParentDescriptorV1,
    parse_approved_parent_descriptor,
    validate_approved_parent_descriptor,
)
from .artifact_contract import ArtifactRefV1
from .generation_policy_documents import (
    GENERATION_POLICY_CLASSES,
    validate_generation_policy_documents,
)
from .generation_profile import verify_r0_generation_profile
from .generation_schema import GenerationCommitV1
from .generation_verification import (
    parse_generation_verification,
    validate_generation_verification,
)
from .repair_intent import approved_plan_digest

_JSON_LIMIT = 16 * 1024 * 1024


class HistoricalArtifactStore(Protocol):
    """Small exact-ref surface needed for lineage semantic validation."""

    commit: GenerationCommitV1

    def resolve(self, ref: ArtifactRefV1) -> str:
        """Revalidate and resolve an exact manifest ref."""

    def read(self, ref: ArtifactRefV1, limit_bytes: int) -> bytes:
        """Read stable manifest-bound bytes."""


def _canonical(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError("historical plan cannot be canonicalized") from exc
    return text.encode("ascii")


def _validate_plan(
    descriptor: ApprovedParentDescriptorV1, store: HistoricalArtifactStore
) -> str:
    raw = store.read(descriptor.plan.artifact, _JSON_LIMIT)
    try:
        plan = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("historical approved plan is invalid JSON") from exc
    if type(plan) is not dict or _canonical(plan) != raw:
        raise RuntimeError("historical approved plan is not canonical")
    expected = (
        approved_plan_digest(plan),
        plan_content_hash(plan),
        base_plan_digest(plan),
    )
    actual = (
        descriptor.plan.approved_plan_digest,
        descriptor.plan.content_hash,
        descriptor.plan.base_projection_digest,
    )
    if actual != expected:
        raise RuntimeError("historical approved-plan identities differ")
    return expected[0]


def validate_historical_generation(
    commit: GenerationCommitV1, store: HistoricalArtifactStore
) -> tuple[ApprovedParentDescriptorV1, str]:
    """Apply existing R0/card/policy/verification rules and bind plan bytes."""
    groups = verify_r0_generation_profile(commit)
    artifacts = class_artifacts(groups)
    approved_ref = artifacts["approved-parent-v1"][0]
    if approved_ref.relative_path != commit.approved_parent_path:
        raise RuntimeError("historical approved-parent path differs from commit")
    descriptor = parse_approved_parent_descriptor(store.read(approved_ref, _JSON_LIMIT))
    validate_approved_parent_descriptor(descriptor)
    validate_descriptor_identity(descriptor, commit)
    validate_descriptor_artifacts(descriptor, artifacts, store)  # type: ignore[arg-type]
    validate_remaining_artifacts(artifacts, store)  # type: ignore[arg-type]
    policy_raw = {
        name: store.read(artifacts[name][0], _JSON_LIMIT)
        for name in GENERATION_POLICY_CLASSES
    }
    validate_generation_policy_documents(commit, policy_raw)
    verification_ref = artifacts["generation-verification-v1"][0]
    verification = parse_generation_verification(
        store.read(verification_ref, _JSON_LIMIT)
    )
    validate_generation_verification(verification, commit, approved_ref)
    return descriptor, _validate_plan(descriptor, store)
