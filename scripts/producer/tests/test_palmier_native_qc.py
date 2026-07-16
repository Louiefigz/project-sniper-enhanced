"""Fresh-read QC lifecycle and compare-and-swap promotion tests."""
import copy
import os
import tempfile
import unittest
import json
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.candidate_receipt import load_candidate, save_candidate
from palmier.native_delta import NativeRequest, execute_native_candidate
from palmier.native_qc import (prepare_qc, promote_approved,
                               run_deterministic_qc)
from palmier.native_qc_audit import run_native_audit, structural_proof
from palmier.native_qc_authority import (identity,
                                         read_candidate_restoring_parent)
from palmier.native_qc_contract import export_path, load_qc, save_qc
from palmier.timeline_authority import (TimelineConflict, authority_path,
                                        load_authority, snapshot)
from palmier.timeline_guard import reconcile_working_authority
from test_palmier_native_delta import NativeClient, _plan, _record


def _candidate(tmp: str, client: NativeClient) -> tuple[dict, dict]:
    parent = _record(tmp, client)
    result = execute_native_candidate(
        client, tmp, NativeRequest({"projectId": "project-1"}, _plan(parent)))
    return parent, result


def _approve(tmp: str, parent: dict, candidate: dict) -> dict:
    digest = "q" * 64
    candidate.update({"status": "qc-approved", "qc": {
        "status": "approved", "approved": True, "approvalDigest": digest}})
    save_candidate(tmp, candidate)
    receipt = {"schemaVersion": 1, "status": "qc-approved", "outDir": tmp,
               "parent": identity(parent), "candidate": identity(candidate),
               "approvalDigest": digest, "approvedAt": "2026-07-12T12:00:00Z",
               "export": {"hash": "e" * 64}}
    return save_qc(tmp, receipt)


class FreshReadTests(unittest.TestCase):
    def test_prepare_preserves_unchanged_visible_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            _parent, _found = _candidate(tmp, client)
            client.active = "candidate"
            media = export_path(tmp)
            with open(media, "wb") as handle:
                handle.write(b"candidate-media")
            exported = {"path": media, "hash": file_sha256(media),
                        "audioPresent": True, "timelineId": "candidate"}
            authority = {"inputDigest": "i" * 64}
            with patch("palmier.native_qc.export_candidate",
                       return_value=exported), \
                    patch("palmier.native_qc.authority_from_input",
                          return_value=authority):
                receipt = prepare_qc(client, tmp, "/unused/context.json")
            self.assertEqual(client.active, "candidate")
            self.assertEqual(receipt["status"], "prepared")
            self.assertEqual(receipt["candidate"]["timelineId"], "candidate")

    def test_candidate_drift_during_export_blocks_before_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            _parent, _found = _candidate(tmp, client)

            def drift(*_args):
                client.timelines["candidate"]["tracks"][0]["clips"][0]["opacity"] = 0.2
                return {"path": export_path(tmp), "hash": "e" * 64,
                        "audioPresent": True, "timelineId": "candidate"}

            with patch("palmier.native_qc.export_candidate", side_effect=drift):
                with self.assertRaisesRegex(TimelineConflict,
                                            "changed after it was staged"):
                    prepare_qc(client, tmp, "/unused/context.json")
            self.assertEqual(client.active, "head")
            self.assertFalse(os.path.exists(os.path.join(
                tmp, "palmier.native-qc.json")))

    def test_visible_manual_candidate_drift_blocks_without_switching(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent, candidate = _candidate(tmp, client)
            client.active = "candidate"
            client.timelines["candidate"]["tracks"][0]["clips"][0]["opacity"] = 0.2
            with self.assertRaisesRegex(TimelineConflict, "changed manually"):
                read_candidate_restoring_parent(client, parent, candidate)
            self.assertEqual(client.active, "candidate")

    def test_unrelated_visible_timeline_is_never_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent, candidate = _candidate(tmp, client)
            other = copy.deepcopy(client.timelines["head"])
            other["id"] = "manual-other"
            client.timelines["manual-other"] = other
            client.active = "manual-other"
            with self.assertRaisesRegex(TimelineConflict, "another managed timeline"):
                read_candidate_restoring_parent(client, parent, candidate)
            self.assertEqual(client.active, "manual-other")


class PromotionTests(unittest.TestCase):
    def test_success_moves_working_and_approved_heads_after_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent, candidate = _candidate(tmp, client)
            _approve(tmp, parent, candidate)
            with patch("palmier.native_qc._validate_approval"):
                receipt = promote_approved(client, tmp)
            authority = load_authority(tmp)
            self.assertEqual(client.active, "candidate")
            self.assertEqual(authority["timelineId"], "candidate")
            self.assertEqual(authority["workingHead"]["timelineId"], "candidate")
            self.assertEqual(authority["approvedHead"]["timelineId"], "candidate")
            self.assertEqual(receipt["status"], "promoted")

    def test_promoted_manual_edit_becomes_unapproved_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent, candidate = _candidate(tmp, client)
            _approve(tmp, parent, candidate)
            with patch("palmier.native_qc._validate_approval"):
                promote_approved(client, tmp)
            approved = copy.deepcopy(load_authority(tmp)["approvedHead"])
            client.timelines["candidate"]["tracks"][0]["clips"][0]["opacity"] = 0.2
            saved, change = reconcile_working_authority(
                client, tmp, {"projectId": "project-1"})
            self.assertEqual(change, "candidate-manual")
            self.assertEqual(saved["approvedHead"], approved)
            self.assertFalse(saved["approvalCurrent"])
            self.assertEqual(load_candidate(tmp)["status"], "superseded-manual")
            self.assertEqual(load_qc(tmp)["status"], "superseded-manual")

    def test_qc_approved_candidate_stays_pending_until_manual_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent, candidate = _candidate(tmp, client)
            _approve(tmp, parent, candidate)
            client.active = "candidate"
            with self.assertRaisesRegex(TimelineConflict, "awaits deliberate promotion"):
                reconcile_working_authority(client, tmp, {"projectId": "project-1"})
            client.timelines["candidate"]["tracks"][0]["clips"][0]["opacity"] = 0.2
            saved, change = reconcile_working_authority(
                client, tmp, {"projectId": "project-1"})
            self.assertEqual(change, "candidate-manual")
            self.assertEqual(saved["timelineId"], "candidate")
            self.assertEqual(load_candidate(tmp)["status"], "superseded-manual")
            self.assertEqual(load_qc(tmp)["status"], "superseded-manual")

    def test_authority_write_failure_occurs_only_after_verified_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent, candidate = _candidate(tmp, client)
            _approve(tmp, parent, candidate)
            with open(authority_path(tmp), encoding="utf-8") as handle:
                original = handle.read()

            def fail(_path, _record):
                self.assertEqual(client.active, "candidate")
                raise OSError("disk full")

            with patch("palmier.native_qc._validate_approval"), \
                    patch("palmier.native_qc_authority.atomic_write_record",
                          side_effect=fail):
                with self.assertRaisesRegex(OSError, "disk full"):
                    promote_approved(client, tmp)
            with open(authority_path(tmp), encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original)
            self.assertEqual(load_candidate(tmp)["status"], "qc-approved")
            self.assertEqual(client.active, "head")

    def test_final_activation_failure_restores_visible_parent(self):
        class FailFinalActivation(NativeClient):
            def __init__(self):
                super().__init__()
                self.candidate_activations = 0

            def call_json(self, tool, arguments=None):
                if tool == "set_active_timeline" \
                        and (arguments or {}).get("timelineId") == "candidate":
                    self.candidate_activations += 1
                    if self.candidate_activations == 3:
                        raise OSError("activation unavailable")
                return super().call_json(tool, arguments)

        with tempfile.TemporaryDirectory() as tmp:
            client = FailFinalActivation()
            parent, candidate = _candidate(tmp, client)
            _approve(tmp, parent, candidate)
            with patch("palmier.native_qc._validate_approval"):
                with self.assertRaisesRegex(OSError, "activation unavailable"):
                    promote_approved(client, tmp)
            self.assertEqual(client.active, "head")
            self.assertEqual(load_authority(tmp)["timelineId"], "head")
            self.assertEqual(load_candidate(tmp)["status"], "qc-approved")

    def test_parent_drift_blocks_before_any_timeline_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent, candidate = _candidate(tmp, client)
            _approve(tmp, parent, candidate)
            client.timelines["head"]["tracks"][0]["clips"][0]["opacity"] = 0.3
            with patch("palmier.native_qc._validate_approval"):
                with self.assertRaisesRegex(TimelineConflict, "parent changed manually"):
                    promote_approved(client, tmp)
            self.assertEqual(client.active, "head")
            self.assertEqual(load_authority(tmp)["timelineId"], "head")

    def test_candidate_drift_during_expensive_validation_fails_final_cas(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent, candidate = _candidate(tmp, client)
            _approve(tmp, parent, candidate)

            def drift(_receipt, _found):
                client.timelines["candidate"]["tracks"][0]["clips"][0]["opacity"] = 0.1

            with patch("palmier.native_qc._validate_approval", side_effect=drift):
                with self.assertRaisesRegex(TimelineConflict, "changed after it was staged"):
                    promote_approved(client, tmp)
            self.assertEqual(client.active, "head")
            self.assertEqual(load_authority(tmp)["timelineId"], "head")

    def test_successful_promotion_retry_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent, candidate = _candidate(tmp, client)
            _approve(tmp, parent, candidate)
            with patch("palmier.native_qc._validate_approval"):
                first = promote_approved(client, tmp)
                first_authority = copy.deepcopy(load_authority(tmp))
                second = promote_approved(client, tmp)
            self.assertEqual(first["approvalDigest"], second["approvalDigest"])
            self.assertEqual(load_authority(tmp), first_authority)
            self.assertEqual(client.active, "candidate")


class AuditLifecycleTests(unittest.TestCase):
    def test_native_audit_artifact_and_hash_match_returned_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = snapshot("project-1", NativeClient().timelines["head"])
            receipt = {"outDir": tmp, "export": {"hash": "e" * 64},
                       "authority": {"inputDigest": "i" * 64}}
            checks = [{"name": "render", "status": "pass",
                       "measured": "ok", "detail": ""}]
            with patch("palmier.native_qc_audit._export_checks",
                       return_value=(checks, [])):
                audit = run_native_audit(tmp, receipt, found)
            self.assertEqual(audit["status"], "pass")
            self.assertEqual(file_sha256(audit["auditPath"]), audit["auditHash"])
            with open(audit["auditPath"], encoding="utf-8") as handle:
                persisted = json.load(handle)
            self.assertEqual(persisted["digest"], audit["digest"])

    def test_deterministic_pass_never_implicitly_approves_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent, candidate = _candidate(tmp, client)
            found = snapshot("project-1", client.timelines["candidate"])
            structure = structural_proof(found)
            save_qc(tmp, {"schemaVersion": 1, "status": "prepared",
                          "outDir": tmp, "parent": identity(parent),
                          "candidate": {**identity(candidate),
                                        "structuralDigest": structure["digest"]},
                          "authority": {}, "export": {}})
            audit = {"schemaVersion": 1, "stage": "palmier-native-audit",
                     "status": "pass", "candidateFingerprint": found.fingerprint,
                     "exportHash": "e" * 64, "inputAuthorityDigest": "i" * 64,
                     "checks": [], "frames": [], "digest": "d" * 64,
                     "auditPath": os.path.join(tmp, "palmier.native-audit.json"),
                     "auditHash": "a" * 64}
            with patch("palmier.native_qc.validate_current_authority"), \
                    patch("palmier.native_qc.validate_export"), \
                    patch("palmier.native_qc.run_native_audit", return_value=audit):
                result = run_deterministic_qc(client, tmp)
            self.assertEqual(result["deterministic"], audit)
            self.assertEqual(result["status"], "deterministic-passed")
            self.assertEqual(load_candidate(tmp)["status"], "edited")
            self.assertEqual(client.active, "head")


if __name__ == "__main__":
    unittest.main()
