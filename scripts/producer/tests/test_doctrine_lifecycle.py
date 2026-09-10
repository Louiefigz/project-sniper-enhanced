"""Fail-closed tests for the Palmier-canonical doctrine learning lifecycle."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cross_runtime_canonical_json import canonical_compact_json  # noqa: E402
from learning.doctrine_lifecycle import (  # noqa: E402
    DoctrineLifecycleError,
    PRODUCER_CORE_DOCTRINE_PATHS,
    build_candidate,
    capture_producer_run,
    capture_run,
    draft_proposal,
    promote_for_next_run,
    rollback_for_next_run,
    restore_lock,
    source_drift,
)
from learning.observations import (  # noqa: E402
    critic_observation,
    manual_timeline_observation,
    qc_observation,
)

_ARTIFACT = "a" * 64
_REPO = Path(__file__).resolve().parents[3]


def _hash(value: object) -> str:
    blob = canonical_compact_json(value)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class DoctrineLockTests(unittest.TestCase):
    """A run reads exact pinned doctrine even when repository text moves on."""

    def test_hash_is_order_independent_and_content_sensitive(self) -> None:
        one = capture_run("run-1", {"SKILL.md": "law", "ledger.md": "lesson"})
        reordered = capture_run("run-2", {"ledger.md": "lesson", "SKILL.md": "law"})
        changed = capture_run("run-3", {"SKILL.md": "law!", "ledger.md": "lesson"})
        self.assertEqual(one.doctrine_hash, reordered.doctrine_hash)
        self.assertNotEqual(one.doctrine_hash, changed.doctrine_hash)

    def test_pinned_text_survives_live_source_drift(self) -> None:
        lock = capture_run("run-1", {"ledger.md": "active lesson"})
        drift = source_drift(lock, {"ledger.md": "mid-run mutation"})
        self.assertEqual(drift, ("ledger.md",))
        self.assertEqual(lock.text("ledger.md"), "active lesson")

    def test_lock_receipt_is_hash_only_but_text_stays_available(self) -> None:
        lock = capture_run("run-1", {"ledger.md": "secret exact doctrine"})
        self.assertNotIn("content", lock.receipt()["files"][0])
        self.assertEqual(lock.receipt()["state"], "pinned")

    def test_resumable_snapshot_round_trips_and_rejects_tampering(self) -> None:
        lock = capture_run("run-1", {"ledger.md": "exact doctrine"})
        snapshot = lock.snapshot()
        self.assertEqual(restore_lock(snapshot), lock)
        snapshot["files"][0]["content"] = "changed after capture"
        with self.assertRaises(DoctrineLifecycleError):
            restore_lock(snapshot)

    def test_resumable_snapshot_rejects_activation_tampering(self) -> None:
        snapshot = capture_run("run-1", {"ledger.md": "exact"}).snapshot()
        snapshot["activation"]["kind"] = "promotion"
        with self.assertRaises(DoctrineLifecycleError):
            restore_lock(snapshot)

    def test_producer_capture_requires_the_shared_core(self) -> None:
        with self.assertRaisesRegex(DoctrineLifecycleError, "sources missing"):
            capture_producer_run("run-1", {"ledger.md": "not enough"})

    def test_real_producer_core_can_be_pinned(self) -> None:
        sources = {path: (_REPO / path).read_text(encoding="utf-8")
                   for path in PRODUCER_CORE_DOCTRINE_PATHS}
        lock = capture_producer_run("run-real", sources)
        self.assertEqual(len(lock.files), len(PRODUCER_CORE_DOCTRINE_PATHS))
        self.assertRegex(lock.doctrine_hash, r"^[0-9a-f]{64}$")


class ObservationTests(unittest.TestCase):
    """Learning inputs are evidence records, never active doctrine edits."""

    def setUp(self) -> None:
        self.lock = capture_run("run-1", {"ledger.md": "lesson"})

    def test_scoped_critic_issue_keeps_run_doctrine_authority(self) -> None:
        item = critic_observation(self.lock, "obs-critic", {
            "code": "TRANSITION_UNEARNED", "lane": "transition",
            "severity": "major", "reviewArtifactHash": _ARTIFACT,
            "evidence": ["frame 126 shows an unmotivated wipe"],
        })
        self.assertEqual(item.doctrine_hash, self.lock.doctrine_hash)
        self.assertEqual(item.code, "TRANSITION_UNEARNED")
        self.assertEqual(item.receipt()["status"], "observed")

    def test_qc_only_records_warnings_or_failures(self) -> None:
        item = qc_observation(self.lock, "obs-qc", {
            "code": "AUDIO_TRUE_PEAK", "lane": "audio", "status": "fail",
            "qcArtifactHash": _ARTIFACT, "measurement": {"dbtp": 0.3},
        })
        self.assertEqual(item.evidence["measurement"], {"dbtp": 0.3})
        with self.assertRaises(DoctrineLifecycleError):
            qc_observation(self.lock, "obs-pass", {
                "code": "OK", "lane": "audio", "status": "pass",
                "qcArtifactHash": _ARTIFACT,
            })

    def test_manual_palmier_revision_is_a_hashed_diff_without_interpretation(self) -> None:
        before = {"id": "timeline-1", "canGenerate": False, "currentFrame": 0,
                  "tracks": [{
            "id": "video", "clips": [{"id": "clip-1", "start": 0, "end": 2}],
        }]}
        after = {"id": "timeline-1", "canGenerate": True, "currentFrame": 17,
                 "timelines": [{"timelineId": "copy", "active": True}], "tracks": [{
            "id": "video", "clips": [{"id": "clip-1", "start": 0, "end": 1.5}],
        }]}
        revision = {"before": self._authority(before),
                    "after": self._authority(after), "lane": "cut"}
        item = manual_timeline_observation(self.lock, "obs-manual", revision)
        evidence = item.evidence
        self.assertEqual(item.source_kind, "palmier-manual")
        self.assertEqual(evidence["interpretation"], "none")
        self.assertEqual(evidence["diff"]["changeCount"], 1)
        self.assertEqual(evidence["diff"]["changes"][0]["path"],
                         "/tracks/0/clips/0/end")
        self.assertNotIn("lesson", json.dumps(evidence).lower())

    def test_manual_palmier_diff_rejects_stale_fingerprint(self) -> None:
        before = {"id": "timeline-1", "tracks": []}
        after = {"id": "timeline-1", "tracks": [{"id": "video"}]}
        revision = {"before": self._authority(before),
                    "after": self._authority(after)}
        revision["after"]["fingerprint"] = "0" * 64
        with self.assertRaisesRegex(DoctrineLifecycleError, "fingerprint is stale"):
            manual_timeline_observation(self.lock, "obs-stale", revision)

    @staticmethod
    def _authority(timeline: dict) -> dict:
        runtime = {"canGenerate", "currentFrame", "timelines"}
        content = {key: value for key, value in timeline.items()
                   if key not in runtime}
        return {"timelineId": timeline["id"], "fingerprint": _hash(content),
                "projectId": "project-1",
                "semanticFingerprint": "b" * 64, "timeline": timeline}


class PromotionBoundaryTests(unittest.TestCase):
    """No proposal can activate without operator approval, tests, and evals."""

    def setUp(self) -> None:
        self.base = capture_run("run-1", {"ledger.md": "old lesson"})
        self.observation = critic_observation(self.base, "obs-1", {
            "code": "GRAPHIC_REDUNDANT", "lane": "graphics",
            "severity": "major", "reviewArtifactHash": _ARTIFACT,
            "evidence": ["graphic repeats the narration"],
        })
        self.proposal = draft_proposal(self.base, {
            "proposalId": "proposal-1", "observationIds": ["obs-1"],
            "lessonText": "Remove redundant graphics.",
            "targetPath": "ledger.md", "authorKind": "agent-draft",
        }, [self.observation])
        self.candidate = build_candidate(
            self.base, {"ledger.md": "old lesson\nnew proposed lesson"},
            [self.proposal])

    def _gate(self, next_run: str = "run-2") -> dict:
        return {
            "nextRunId": next_run,
            "operatorApproval": {"actor": "operator", "decision": "approve",
                                 "proposalIds": ["proposal-1"],
                                 "candidateDoctrineHash":
                                     self.candidate.candidate_doctrine_hash},
            "verification": {
                "candidateDoctrineHash": self.candidate.candidate_doctrine_hash,
                "regressionCount": 0,
                "tests": [{"id": "lint-regression", "status": "pass",
                           "artifactHash": _ARTIFACT}],
                "evals": [{"id": "golden-edit", "status": "pass",
                           "artifactHash": "b" * 64}],
            },
        }

    def test_proposal_and_candidate_are_not_active(self) -> None:
        self.assertEqual(self.proposal.status, "proposed")
        self.assertEqual(self.candidate.status, "candidate")
        self.assertEqual(self.base.text("ledger.md"), "old lesson")

    def test_model_draft_cannot_self_approve(self) -> None:
        gate = self._gate()
        gate["operatorApproval"]["actor"] = "model"
        with self.assertRaisesRegex(DoctrineLifecycleError, "operator approval"):
            promote_for_next_run(self.base, self.candidate, [self.proposal], gate)

    def test_operator_approval_binds_the_exact_candidate_bytes(self) -> None:
        gate = self._gate()
        gate["operatorApproval"]["candidateDoctrineHash"] = "c" * 64
        with self.assertRaisesRegex(DoctrineLifecycleError, "operator approval"):
            promote_for_next_run(self.base, self.candidate, [self.proposal], gate)

    def test_tests_and_evals_both_gate_promotion(self) -> None:
        for key in ("tests", "evals"):
            gate = self._gate()
            gate["verification"][key] = []
            with self.subTest(key=key), self.assertRaises(DoctrineLifecycleError):
                promote_for_next_run(self.base, self.candidate,
                                     [self.proposal], gate)

    def test_failed_or_stale_verification_is_rejected(self) -> None:
        gate = self._gate()
        gate["verification"]["evals"][0]["status"] = "fail"
        with self.assertRaises(DoctrineLifecycleError):
            promote_for_next_run(self.base, self.candidate, [self.proposal], gate)
        gate = self._gate()
        gate["verification"]["candidateDoctrineHash"] = "c" * 64
        with self.assertRaises(DoctrineLifecycleError):
            promote_for_next_run(self.base, self.candidate, [self.proposal], gate)

    def test_activation_is_next_run_only_and_records_rollback(self) -> None:
        with self.assertRaisesRegex(DoctrineLifecycleError, "inside a running edit"):
            promote_for_next_run(self.base, self.candidate, [self.proposal],
                                 self._gate("run-1"))
        activated = promote_for_next_run(self.base, self.candidate,
                                         [self.proposal], self._gate())
        self.assertEqual(activated.run_id, "run-2")
        self.assertEqual(activated.activation_kind, "promotion")
        self.assertEqual(activated.rollback_doctrine_hash, self.base.doctrine_hash)
        self.assertRegex(activated.activation_evidence_hash or "", r"^[0-9a-f]{64}$")
        self.assertEqual(self.base.text("ledger.md"), "old lesson")

    def test_rollback_restores_exact_prior_bytes_in_another_run(self) -> None:
        active = promote_for_next_run(self.base, self.candidate,
                                      [self.proposal], self._gate())
        rolled = rollback_for_next_run(active, self.base, {
            "nextRunId": "run-3", "operatorApproval": {
                "actor": "operator", "decision": "approve", "action": "rollback",
                "reason": "golden-edit regression appeared in production",
            },
        })
        self.assertEqual(rolled.doctrine_hash, self.base.doctrine_hash)
        self.assertEqual(rolled.text("ledger.md"), "old lesson")
        self.assertEqual(rolled.activation_kind, "rollback")


if __name__ == "__main__":
    unittest.main()
