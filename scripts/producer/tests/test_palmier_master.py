"""Approved Sniper visual-master policy and evidence authority tests."""
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.master import approved_master
from palmier.mcp_client import PalmierError
from palmier.quality_hash import request_key, stable_hash


def _write(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(value, bytes) else "w"
    with open(path, mode) as handle:
        handle.write(value if isinstance(value, bytes) else json.dumps(value))


def _ref(path: str) -> dict:
    return {"path": path, "hash": file_sha256(path)}


class ManagedFixture:
    def __init__(self, tmp: str):
        self.tmp = tmp
        self.plan = os.path.join(tmp, "edit_plan.json")
        self.manifest = os.path.join(tmp, "asset_manifest.json")
        self.final = os.path.join(tmp, "final.mp4")
        _write(self.plan, b"{}")
        _write(self.manifest, b'{"sources":[]}')
        _write(self.final, b"approved-final")
        self.final_hash = file_sha256(self.final)
        self.authority = {
            "digest": "a" * 64, "planHash": file_sha256(self.plan),
            "manifestHash": file_sha256(self.manifest),
        }
        self.ctx = {"dir": tmp, "scope": "light", "planPath": self.plan,
                    "manifestPath": self.manifest, "transcriptsDir": tmp}
        self._proof()
        self.approval = self._approval()
        _write(os.path.join(tmp, ".sniper-qc-approved.json"), self.approval)
        self._policy()
        self._job()

    def _proof(self) -> None:
        _write(self.final + ".assembled.json", {
            "planHash": "canonical-plan", "authorityHash": self.final_hash,
            "inputAuthorityDigest": self.authority["digest"],
            "qualityPolicyVersion": 1,
        })

    def _artifact(self, name: str, value) -> dict:
        path = os.path.join(self.tmp, ".sniper-qc", name)
        _write(path, value)
        return _ref(path)

    def _approval(self) -> dict:
        digest = self.authority["digest"]
        gate_verdict = {"ok": True, "gates": {
            "operatorIntent": {"ok": True},
            "templateUsage": {
                "ok": True, "metrics": {"snapshotDigest": "b" * 64}}}}
        packet_core = {
            "schemaVersion": 1, "kind": "producer-plan-review-packet",
            "stage": "plan", "round": 1,
            "inputAuthority": {"digest": digest},
            "plan": {"byteHash": self.authority["planHash"], "content": {}},
            "manifest": {"byteHash": self.authority["manifestHash"], "content": {}},
            "gateDigest": stable_hash(gate_verdict), "gateVerdict": gate_verdict,
        }
        packet_value = {**packet_core, "contentDigest": stable_hash(packet_core)}
        packet = self._artifact("plan-review-packet.json", packet_value)
        packet_binding = {**packet, "contentDigest": packet_value["contentDigest"],
                          "authorityDigest": digest,
                          "gateDigest": packet_value["gateDigest"], "round": 1}
        gates = self._artifact("planning-gates.json", {
            "schemaVersion": 1, "stage": "plan-gates", "round": 1,
            "inputAuthority": {"digest": digest}, "inputPacket": packet_binding,
            "gates": gate_verdict})
        review = self._artifact("plan-review.json", {
            "schemaVersion": 1, "stage": "plan", "round": 1,
            "inputAuthority": {"digest": digest}, "inputPacket": packet_binding,
            "review": {"verdict": "pass"}})
        machine = self._artifact("audit_report.json", {
            "overall": "pass", "checks": [], "frames": []})
        report = self._artifact("audit_report.md", b"# pass")
        frame = self._artifact("audit_frames/frame.jpg", b"frame")
        audit_content = {"candidateHash": self.final_hash,
                         "assembledProofHash": file_sha256(self.final + ".assembled.json"),
                         "machine": machine, "report": report, "frames": [frame]}
        audit = {**audit_content, "digest": stable_hash(audit_content)}
        rendered = []
        for lens in ("composition", "editorial"):
            item = self._artifact(f"{lens}-review.json", {
                "schemaVersion": 1, "stage": "rendered", "lens": lens,
                "inputAuthority": {"digest": digest},
                "evidence": {"digest": audit["digest"]},
                "review": {"verdict": "pass"}})
            rendered.append({"lens": lens, **item})
        summary = self._artifact("quality-summary.json", {
            "schemaVersion": 1, "stage": "quality-summary", "qcRound": 1,
            "inputAuthority": {"digest": digest},
            "evidence": {"digest": audit["digest"]}, "audit": {"failure": None},
            "aggregate": {"verdict": "pass", "materialIssues": []}})
        return {"schemaVersion": 2, "qualityPolicyVersion": 1,
                "authorityDigest": digest, "planHash": self.authority["planHash"],
                "manifestHash": self.authority["manifestHash"],
                "finalHash": self.final_hash, "candidateHash": self.final_hash,
                "assembledProofHash": audit_content["assembledProofHash"],
                "qcRound": 1, "approvedAt": "2026-07-12T12:00:00Z",
                "planningRoundsRequired": 1,
                "planningReviews": [{"round": 1, "authorityDigest": digest,
                                     "planHash": self.authority["planHash"],
                                     "packet": packet, "gates": gates, "review": review}],
                "renderedReviews": rendered, "audit": audit,
                "qualitySummary": summary}

    def _policy(self) -> None:
        _write(os.path.join(self.tmp, ".sniper-quality-policy.json"), {
            "schemaVersion": 1, "mode": "managed", "qualityPolicyVersion": 1,
            "activatedAt": "2026-07-12T10:00:00Z",
            "requestKey": request_key(self.ctx), "ctx": self.ctx})

    def _job(self) -> None:
        digest, plan_hash = self.authority["digest"], self.authority["planHash"]
        job = {"version": 1, "qualityPolicyVersion": 1, "status": "complete",
               "checkpoint": "complete", "requestKey": request_key(self.ctx),
               "ctx": self.ctx, "planHash": plan_hash,
               "planningCleanPlanHash": plan_hash, "reviewedPlanHash": plan_hash,
               "renderedPlanHash": plan_hash,
               "manifestHash": self.authority["manifestHash"],
               "renderedManifestHash": self.authority["manifestHash"],
               "authorityDigest": digest, "planningCleanAuthorityDigest": digest,
               "reviewedAuthorityDigest": digest, "renderedAuthorityDigest": digest,
               "planningRoundsRequired": 1, "planningCleanRounds": 1,
               "planningRound": 1, "qcRound": 1,
               "candidateHash": self.final_hash, "finalHash": self.final_hash,
               "unresolvedFindingIds": []}
        _write(os.path.join(self.tmp, ".sniper-auto-edit-job.json"), job)


class ApprovedMasterTests(unittest.TestCase):
    PROBE = SimpleNamespace(duration=2.0, fps=29.97, width=3840,
                            height=2160, vfr=False,
                            frame_rate="30000/1001")

    def _approved(self, fixture: ManagedFixture):
        with patch("palmier.master.authority_snapshot",
                   return_value=fixture.authority), \
                patch("palmier.master.probe_media", return_value=self.PROBE):
            return approved_master(fixture.tmp, fixture.plan, fixture.manifest,
                                   "canonical-plan")

    def test_managed_master_requires_all_schema_v2_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ManagedFixture(tmp)
            facts = self._approved(fixture)
        self.assertEqual(facts.path, fixture.final)
        self.assertEqual(facts.end_frame, 60)

    def test_changed_audit_frame_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ManagedFixture(tmp)
            _write(fixture.approval["audit"]["frames"][0]["path"], b"changed")
            with self.assertRaisesRegex(PalmierError, "audit frame 1 hash changed"):
                self._approved(fixture)

    def test_changed_planning_packet_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ManagedFixture(tmp)
            packet = fixture.approval["planningReviews"][0]["packet"]["path"]
            _write(packet, {"tampered": True})
            with self.assertRaisesRegex(PalmierError, "planning packet hash changed"):
                self._approved(fixture)

    def test_symlinked_evidence_parent_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ManagedFixture(tmp)
            evidence = os.path.join(tmp, ".sniper-qc")
            moved = evidence + "-real"
            os.rename(evidence, moved)
            os.symlink(moved, evidence)
            with self.assertRaisesRegex(PalmierError, "path escapes"):
                self._approved(fixture)

    def test_current_files_still_fail_when_authority_digest_drifted(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ManagedFixture(tmp)
            drifted = {**fixture.authority, "digest": "b" * 64}
            with patch("palmier.master.authority_snapshot", return_value=drifted):
                with self.assertRaisesRegex(PalmierError, "authority is stale"):
                    approved_master(tmp, fixture.plan, fixture.manifest,
                                    "canonical-plan")

    def test_mutable_job_cannot_claim_completion_without_coherence(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ManagedFixture(tmp)
            job_path = os.path.join(tmp, ".sniper-auto-edit-job.json")
            with open(job_path) as handle:
                job = json.load(handle)
            job["renderedAuthorityDigest"] = "c" * 64
            _write(job_path, job)
            with self.assertRaisesRegex(PalmierError, "renderedAuthorityDigest"):
                self._approved(fixture)

    def test_missing_policy_marker_is_not_assumed_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ManagedFixture(tmp)
            os.remove(os.path.join(tmp, ".sniper-quality-policy.json"))
            with self.assertRaisesRegex(PalmierError, "quality-policy marker"):
                self._approved(fixture)

    def test_explicit_legacy_marker_uses_only_final_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = os.path.join(tmp, "edit_plan.json")
            manifest = os.path.join(tmp, "asset_manifest.json")
            final = os.path.join(tmp, "final.mp4")
            _write(plan, b'{"target":{"mode":"longform","scope":"light"}}')
            _write(manifest, b'{"sources":[]}')
            _write(final, b"legacy-final")
            _write(final + ".assembled.json", {
                "planHash": "canonical-plan", "authorityHash": file_sha256(final)})
            _write(os.path.join(tmp, ".sniper-quality-policy.json"), {
                "schemaVersion": 1, "mode": "legacy",
                "migratedAt": "2026-07-12T12:00:00Z", "reason": "predates v1"})
            _write(os.path.join(tmp, "project.json"), {
                "origin": "raw", "history": [],
                "resolvedIntent": {"mode": "longform", "scope": "light", "lanes": {}}})
            expected_hash = file_sha256(final)
            with patch("palmier.master.probe_media", return_value=self.PROBE):
                facts = approved_master(tmp, plan, manifest, "canonical-plan")
        self.assertEqual(facts.content_hash, expected_hash)

    def test_explicit_legacy_marker_cannot_exempt_produced_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ManagedFixture(tmp)
            _write(fixture.plan, {"target": {"mode": "longform", "scope": "produced"}})
            _write(os.path.join(tmp, ".sniper-quality-policy.json"), {
                "schemaVersion": 1, "mode": "legacy",
                "migratedAt": "2026-07-12T12:00:00Z", "reason": "predates v1"})
            _write(os.path.join(tmp, "project.json"), {
                "origin": "raw", "history": [],
                "resolvedIntent": {"mode": "longform", "scope": "produced", "lanes": {}}})
            with self.assertRaisesRegex(PalmierError, "governed saved-plan review"):
                approved_master(tmp, fixture.plan, fixture.manifest, "canonical-plan")

    def test_preview_stale_marker_blocks_even_an_explicit_legacy_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = os.path.join(tmp, "edit_plan.json")
            manifest = os.path.join(tmp, "asset_manifest.json")
            final = os.path.join(tmp, "final.mp4")
            _write(plan, b"{}")
            _write(manifest, b'{"sources":[]}')
            _write(final, b"legacy-final")
            _write(os.path.join(tmp, ".sniper-preview-stale.json"), {})
            with self.assertRaisesRegex(PalmierError, "newer edit request"):
                approved_master(tmp, plan, manifest, "canonical-plan")


class CrossLanguageHashTests(unittest.TestCase):
    def test_request_key_matches_typescript_stable_json_hash(self):
        ctx = {"scope": "light", "dir": "/tmp/p", "manifestPath": "/tmp/m",
               "planPath": "/tmp/e", "transcriptsDir": "/tmp/t"}
        self.assertEqual(request_key(ctx),
                         "8bdc7d0052f1ef4c41856ea5424cf90c35972fb2f8d4d6fdbb56a867652f8ef7")
        runtime = {**ctx, "doctrine": {"runId": "runtime-only"},
                   "pipeline": {"runId": "runtime-only"}}
        self.assertEqual(request_key(runtime), request_key(ctx))


if __name__ == "__main__":
    unittest.main()
