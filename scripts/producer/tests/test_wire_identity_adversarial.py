"""Hostile-equality regressions for reparsed headless wire contracts."""

from __future__ import annotations

import dataclasses
import unittest

from _common import pl  # noqa: F401
from _approved_parent_schema_fixture import _descriptor
from headless.approved_parent_schema import (
    ApprovedParentSchemaError,
    parse_approved_parent_descriptor,
    validate_approved_parent_descriptor,
)
from headless.artifact_contract import (
    ArtifactContractError,
    validate_artifact_ref,
)
from headless.generation_artifact_store import (
    GenerationArtifactStoreError,
    GenerationArtifactStoreV1,
)
from headless.generation_reader import ResolvedGenerationV1
from headless.generation_verification import (
    GenerationVerificationError,
    parse_generation_verification,
    validate_generation_verification,
)
from headless.quality_pass_contract import (
    QualityPassContractError,
    parse_quality_pass_input,
    validate_graphic_asset,
    validate_quality_pass_input,
)
from headless.quality_policy import (
    DeterministicQualityPolicyError,
    current_deterministic_quality_policy,
    validate_deterministic_quality_policy,
)
from headless.repair_intent import (
    RepairIntentError,
    apply_repair,
    current_accent_policy,
    parse_repair_intent,
)
from test_generation_artifact_store import _Fixture as StoreFixture
from test_generation_verification import (
    _approved as verification_parent,
    _commit as verification_commit,
    _document as verification_document,
)
from test_quality_pass_contract import _approved, _document, _plan
from test_repair_intent import _intent as repair_document
from test_repair_intent import _plan as repair_plan


class _AlwaysEqualString(str):
    def __eq__(self, value: object) -> bool:
        return True

    def __ne__(self, value: object) -> bool:
        return False

    __hash__ = str.__hash__


def _hostile() -> _AlwaysEqualString:
    return _AlwaysEqualString("0" * 64)


class WireIdentityAdversarialTests(unittest.TestCase):
    def test_quality_input_policy_and_graphic_reject_hostile_leaves(self) -> None:
        request = parse_quality_pass_input(_document(_plan()))
        forged_request = dataclasses.replace(request, request_digest=_hostile())
        with self.assertRaises(QualityPassContractError):
            validate_quality_pass_input(forged_request)
        policy = current_deterministic_quality_policy()
        forged_policy = dataclasses.replace(policy, policy_id=_hostile())
        with self.assertRaises(DeterministicQualityPolicyError):
            validate_deterministic_quality_policy(forged_policy)
        graphic = _approved().graphics_assets[0]
        forged_graphic = dataclasses.replace(graphic, render_build_digest=_hostile())
        with self.assertRaises(QualityPassContractError):
            validate_graphic_asset(forged_graphic)

    def test_repair_parent_and_policy_reject_hostile_leaves(self) -> None:
        plan = repair_plan()
        intent = parse_repair_intent(repair_document(plan))
        parent = dataclasses.replace(intent.expected_parent, commit_digest=_hostile())
        policy = dataclasses.replace(current_accent_policy(), policy_id=_hostile())
        for actual_parent, actual_policy in (
            (parent, current_accent_policy()),
            (intent.expected_parent, policy),
        ):
            with self.subTest(policy=actual_policy), self.assertRaises(
                RepairIntentError
            ):
                apply_repair(intent, actual_parent, plan, actual_policy)

    def test_descriptor_reparse_rejects_hostile_nested_leaf(self) -> None:
        descriptor = parse_approved_parent_descriptor(_descriptor())
        identity = dataclasses.replace(descriptor.identity, request_digest=_hostile())
        forged = dataclasses.replace(descriptor, identity=identity)
        with self.assertRaises(ApprovedParentSchemaError):
            validate_approved_parent_descriptor(forged)

    def test_verification_rejects_hostile_record_and_commit_leaves(self) -> None:
        commit = verification_commit()
        record = parse_generation_verification(verification_document(commit))
        cases = (
            (dataclasses.replace(record, request_digest=_hostile()), commit),
            (record, dataclasses.replace(commit, request_digest=_hostile())),
        )
        for actual_record, actual_commit in cases:
            with self.subTest(commit=actual_commit), self.assertRaises(
                GenerationVerificationError
            ):
                validate_generation_verification(
                    actual_record, actual_commit, verification_parent(commit)
                )

    def test_artifact_store_rejects_hostile_resolved_pointer(self) -> None:
        fixture = StoreFixture()
        try:
            current = dataclasses.replace(fixture.current, commit_digest=_hostile())
            forged = ResolvedGenerationV1(
                current,
                fixture.commit,
                fixture.resolved.materialized,
                fixture.resolved.materialized_snapshots,
            )
            with self.assertRaises(GenerationArtifactStoreError):
                GenerationArtifactStoreV1.from_resolved(forged)
            ref = dataclasses.replace(fixture.ref("proof/qc.json"), sha256=_hostile())
            with self.assertRaises(ArtifactContractError):
                validate_artifact_ref(ref)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
