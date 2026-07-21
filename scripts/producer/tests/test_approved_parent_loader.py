"""Disk-real authority and lease regressions for approved-parent loading."""

from __future__ import annotations

import dataclasses
import stat
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from _common import pl  # noqa: F401
from _approved_parent_loader_fixture import ApprovedParentAuthorityFixture
from headless.approved_parent_loader import (
    ApprovedParentLoadError,
    load_current_approved_parent,
)
from headless.approved_parent_media import ApprovedParentVerifierContextV1
from headless.artifact_contract import ArtifactRefV1
from headless.generation_artifact_store import GenerationArtifactStoreError
from headless.generation_profile import (
    R0_GENERATION_ARTIFACT_CLASS_COUNTS,
    R0_MANIFEST_ROWS,
)

_CONTEXT = ApprovedParentVerifierContextV1("/not/invoked/ffprobe", "0" * 64, 1.0)


class ApprovedParentLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ApprovedParentAuthorityFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def _loader(self, fixture: ApprovedParentAuthorityFixture):
        return load_current_approved_parent(
            str(fixture.authority),
            str(fixture.materialization),
            fixture.documents.expected_parent(),
            _CONTEXT,
        )

    def _assert_rejected(self, scenario: str, message: str) -> None:
        fixture = ApprovedParentAuthorityFixture(scenario)
        try:
            with patch(
                "headless.approved_parent_loader.validate_parent_media",
                return_value=fixture.base_probe(),
            ), self.assertRaisesRegex(ApprovedParentLoadError, message), self._loader(
                fixture
            ):
                self.fail("invalid authority unexpectedly yielded a lease")
        finally:
            fixture.close()

    def _assert_exact_profile(self, fixture: ApprovedParentAuthorityFixture) -> None:
        rows = fixture.documents.commit.files
        self.assertEqual(len(rows), R0_MANIFEST_ROWS)
        self.assertEqual(
            tuple(row.path for row in rows), tuple(sorted(row.path for row in rows))
        )
        self.assertEqual(
            Counter(row.artifact_class for row in rows),
            Counter(R0_GENERATION_ARTIFACT_CLASS_COUNTS),
        )

    def _assert_bad_artifacts(self, lease, refs: tuple[ArtifactRefV1, ...]) -> None:
        for value in refs:
            with self.subTest(ref=value), self.assertRaises(
                GenerationArtifactStoreError
            ):
                lease.resolve_artifact(value)

    def _assert_loaded_lease(self, lease, fixture, expected) -> None:
        self.assertEqual(lease.resolve_parent(expected), lease.parent)
        self.assertEqual(lease.parent.ref, expected)
        self.assertEqual(
            lease.parent.plan_json, fixture.documents.files["plan/edit-plan.json"]
        )
        self.assertEqual(
            lease.read_artifact(lease.parent.plan_artifact, 1024),
            lease.parent.plan_json,
        )
        policies = lease.evidence.policies
        self.assertEqual(
            policies.quality.policy_id, fixture.documents.commit.quality_policy_id
        )
        self.assertEqual(
            policies.repair.policy_id, fixture.documents.commit.repair_policy_id
        )
        quality = lease.evidence.quality_records
        self.assertEqual(quality.final_approval.request_digest, "1" * 64)
        self.assertEqual(
            tuple(critic.lens for critic in quality.critics),
            ("composition", "editorial"),
        )
        authority = lease.evidence.quality_evidence
        self.assertFalse(authority.runtime_reobserved)
        self.assertFalse(authority.execution_authorized)
        self.assertEqual(authority.status, "SEALED_CLAIMS_BOUND_NOT_RUNTIME_REOBSERVED")
        self.assertEqual(authority.evidence.full_decode.video.decoded_frames, 120)
        self.assertEqual(authority.evidence.effect_proof.timing.sampled_frames, 75)
        self.assertEqual(authority.evidence.audit.summary.failed, 0)
        self.assertEqual(len(lease.evidence.class_artifacts), 41)

    def test_complete_r0_generation_loads_and_lease_is_revoked(self) -> None:
        fixture = self.fixture
        expected = fixture.documents.expected_parent()
        self._assert_exact_profile(fixture)
        with patch(
            "headless.approved_parent_loader.validate_parent_media",
            return_value=fixture.base_probe(),
        ) as media_check:
            with self._loader(fixture) as lease:
                self._assert_loaded_lease(lease, fixture, expected)
                retained = lease
        media_check.assert_called_once()
        with self.assertRaisesRegex(ApprovedParentLoadError, "stale or closed"):
            retained.resolve_parent(expected)
        with self.assertRaisesRegex(ApprovedParentLoadError, "lease is closed"):
            retained.resolve_artifact(retained.parent.plan_artifact)
        with self.assertRaisesRegex(ApprovedParentLoadError, "lease is closed"):
            retained.read_artifact(retained.parent.plan_artifact, 1024)

    def test_exact_artifact_resolver_rejects_all_forged_refs(self) -> None:
        fixture = self.fixture
        with patch(
            "headless.approved_parent_loader.validate_parent_media",
            return_value=fixture.base_probe(),
        ), self._loader(fixture) as lease:
            ref = lease.parent.plan_artifact
            resolved = Path(lease.resolve_artifact(ref))
            expected = fixture.materialization / ref.relative_path
            self.assertEqual(resolved, expected)
            self.assertEqual(resolved.read_bytes(), lease.parent.plan_json)
            self.assertEqual(stat.S_IMODE(resolved.stat().st_mode), 0o600)
            forged = (
                ArtifactRefV1(ref.relative_path, "0" * 64, ref.size_bytes),
                ArtifactRefV1(ref.relative_path, ref.sha256, ref.size_bytes + 1),
                ArtifactRefV1("plan/missing.json", ref.sha256, ref.size_bytes),
            )
            self._assert_bad_artifacts(lease, forged)
            wrong_parent = dataclasses.replace(lease.parent.ref, plan_digest="0" * 64)
            with self.assertRaisesRegex(ApprovedParentLoadError, "stale or closed"):
                lease.resolve_parent(wrong_parent)

    def test_stale_caller_expected_parent_is_rejected(self) -> None:
        fixture = self.fixture
        stale = dataclasses.replace(
            fixture.documents.expected_parent(), commit_digest="0" * 64
        )
        loader = load_current_approved_parent(
            str(fixture.authority), str(fixture.materialization), stale, _CONTEXT
        )
        with patch(
            "headless.approved_parent_loader.validate_parent_media",
            return_value=fixture.base_probe(),
        ), self.assertRaisesRegex(
            ApprovedParentLoadError, "not expected parent"
        ), loader:
            self.fail("stale parent unexpectedly loaded")

    def test_descriptor_identity_and_policy_must_match_commit(self) -> None:
        self._assert_rejected("descriptor-identity", "identity differs")
        self._assert_rejected("descriptor-policy", "identity differs")
        self._assert_rejected("policy-document", "quality policy is invalid")

    def test_descriptor_refs_require_exact_class_and_digest(self) -> None:
        self._assert_rejected("descriptor-ref-class", "class plan-v1")
        self._assert_rejected("descriptor-ref-digest", "class plan-v1")

    def test_verification_rejects_mismatch_and_self_reference(self) -> None:
        self._assert_rejected("verification-mismatch", "does not bind")
        self._assert_rejected("verification-self-reference", "does not bind")
        self._assert_rejected("verification-self-inclusion", "does not bind")

    def test_genesis_publication_sequence_must_be_one(self) -> None:
        self._assert_rejected("genesis-sequence", "sequence breaks lineage")

    def test_quality_chain_must_bind_every_semantic_layer(self) -> None:
        self._assert_rejected("quality-cover-binding", "cover proof binding")
        self._assert_rejected("quality-qc-binding", "QC semantic binding")
        self._assert_rejected("quality-critic-binding", "critic semantic binding")
        self._assert_rejected("quality-final-binding", "final approval binding")
        self._assert_rejected("quality-final-schema", "final approval keys")

    def test_quality_evidence_must_bind_decode_effect_and_terminal_audit(self) -> None:
        self._assert_rejected("evidence-decode-binding", "media coverage")
        self._assert_rejected("evidence-effect-binding", "requested effect")
        self._assert_rejected("evidence-audit-binding", "Audit-B authority")

    def test_caller_exception_is_not_rewritten_as_loader_failure(self) -> None:
        fixture = self.fixture
        with patch(
            "headless.approved_parent_loader.validate_parent_media",
            return_value=fixture.base_probe(),
        ):
            with self.assertRaisesRegex(RuntimeError, "caller failure"):
                with self._loader(fixture):
                    raise RuntimeError("caller failure")


if __name__ == "__main__":
    unittest.main(verbosity=2)
