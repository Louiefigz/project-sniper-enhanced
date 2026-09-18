"""Rejected-candidate archival and stale-finalize lifecycle tests."""
import hashlib
import contextlib
import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.candidate_receipt import load_candidate, save_candidate
from palmier.mcp_client import PalmierError
from palmier.native_qc import finalize_approval
from palmier.native_qc_authority import identity
from palmier.native_qc_contract import export_path, load_qc, save_qc
from palmier.native_qc_repair import reject_for_repair
from palmier.sync_lock import SyncLockState
import palmier.native_qc_cli as native_qc_cli
from test_palmier_native_delta import NativeClient
from test_palmier_native_qc import _candidate


class RepairLifecycleTests(unittest.TestCase):
    def test_failed_candidate_is_archived_rejected_and_parent_restored(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent, candidate = _candidate(tmp, client)
            request = "Repair the rejected card hierarchy"
            request_hash = hashlib.sha256(request.encode()).hexdigest()
            candidate.update({"requestHash": request_hash,
                              "lanes": ["graphics", "motion"]})
            save_candidate(tmp, candidate)
            media, review = (export_path(tmp),
                             os.path.join(tmp, "composition-failure.json"))
            with open(media, "wb") as handle:
                handle.write(b"rejected-candidate-export")
            with open(review, "w", encoding="utf-8") as handle:
                json.dump({"verdict": "revise"}, handle)
            receipt = {"schemaVersion": 1, "status": "deterministic-passed",
                       "outDir": tmp, "parent": identity(parent),
                       "candidate": identity(candidate),
                       "authority": {"request": {"text": request,
                                                   "hash": request_hash},
                                     "lanes": candidate["lanes"],
                                     "inputDigest": "i" * 64},
                       "export": {"path": media, "hash": file_sha256(media),
                                  "audioPresent": True}}
            save_qc(tmp, receipt)
            reason_path = os.path.join(tmp, "repair-reason.json")
            reason = {"schemaVersion": 1, "reason": "Composition critic failed",
                      "sourceCandidate": {"timelineId": "candidate",
                                          "fingerprint": candidate["fingerprint"]},
                      "originalRequest": {"text": request, "hash": request_hash},
                      "controllerLanes": candidate["lanes"],
                      "inputAuthorityDigest": "i" * 64,
                      "issues": [{"message": "Card covers the speaker"}],
                      "reviewArtifacts": [review]}
            with open(reason_path, "w", encoding="utf-8") as handle:
                json.dump(reason, handle)
            client.active = "candidate"
            rejected = reject_for_repair(client, tmp, reason_path)
            archive = rejected["archivePath"]
            self.assertEqual(client.active, "head")
            self.assertEqual(load_candidate(tmp)["status"], "qc-rejected")
            self.assertEqual(load_qc(tmp)["status"], "qc-rejected")
            self.assertTrue(os.path.isfile(os.path.join(archive, "archive.json")))
            evidence = os.listdir(os.path.join(archive, "evidence"))
            self.assertTrue(any("candidate-export" in name for name in evidence))
            self.assertTrue(any("review" in name for name in evidence))

    def test_cross_candidate_rejection_reason_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent, candidate = _candidate(tmp, client)
            candidate.update({"requestHash": "a" * 64, "lanes": ["graphics"]})
            save_candidate(tmp, candidate)
            save_qc(tmp, {"schemaVersion": 1, "status": "prepared", "outDir": tmp,
                          "parent": identity(parent), "candidate": identity(candidate),
                          "authority": {"request": {"text": "wrong", "hash": "a" * 64},
                                        "lanes": ["graphics"],
                                        "inputDigest": "i" * 64}, "export": {}})
            reason_path = os.path.join(tmp, "reason.json")
            with open(reason_path, "w", encoding="utf-8") as handle:
                json.dump({"schemaVersion": 1, "reason": "fail",
                           "sourceCandidate": {"timelineId": "other",
                                               "fingerprint": candidate["fingerprint"]},
                           "originalRequest": {"text": "wrong", "hash": "a" * 64},
                           "controllerLanes": ["graphics"],
                           "inputAuthorityDigest": "i" * 64,
                           "issues": [], "reviewArtifacts": []}, handle)
            with self.assertRaisesRegex(PalmierError, "stale or cross-candidate"):
                reject_for_repair(client, tmp, reason_path)
            self.assertEqual(load_candidate(tmp)["status"], "edited")

    def test_finalize_rejects_changed_export_and_stale_reviews(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent, candidate = _candidate(tmp, client)
            media = export_path(tmp)
            with open(media, "wb") as handle:
                handle.write(b"original-export")
            save_qc(tmp, {"schemaVersion": 1, "status": "deterministic-passed",
                          "outDir": tmp, "parent": identity(parent),
                          "candidate": identity(candidate),
                          "authority": {"inputDigest": "i" * 64},
                          "export": {"path": media, "hash": file_sha256(media),
                                     "audioPresent": True},
                          "deterministic": {"digest": "d" * 64}})
            reviews_path = os.path.join(tmp, "reviews.json")
            with open(reviews_path, "w", encoding="utf-8") as handle:
                json.dump({"schemaVersion": 1, "reviews": []}, handle)
            with open(media, "ab") as handle:
                handle.write(b"drift")
            with patch("palmier.native_qc.validate_current_authority"):
                with self.assertRaisesRegex(PalmierError, "export bytes changed"):
                    finalize_approval(client, tmp, reviews_path)
            with open(media, "wb") as handle:
                handle.write(b"original-export")
            rows = [{"schemaVersion": 1, "stage": "rendered", "lens": lens,
                     "verdict": "pass", "materialIssues": [],
                     "candidateFingerprint": "stale", "exportHash": file_sha256(media),
                     "inputAuthorityDigest": "i" * 64,
                     "deterministicDigest": "d" * 64}
                    for lens in ("composition", "editorial")]
            with open(reviews_path, "w", encoding="utf-8") as handle:
                json.dump({"schemaVersion": 1, "reviews": rows}, handle)
            with patch("palmier.native_qc.validate_current_authority"), \
                    patch("palmier.native_qc.validate_export"), \
                    patch("palmier.native_qc._audit_current"):
                with self.assertRaisesRegex(PalmierError, "stale or did not pass"):
                    finalize_approval(client, tmp, reviews_path)
            self.assertEqual(load_candidate(tmp)["status"], "edited")


class NativeQcCliTests(unittest.TestCase):
    def test_reject_action_emits_one_archive_bound_success_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            reason = os.path.join(tmp, "reason.json")
            with open(reason, "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            lease = SimpleNamespace(release=lambda: None)
            acquired = SimpleNamespace(state=SyncLockState.ACQUIRED, lease=lease)
            client = SimpleNamespace(handshake=lambda: None)
            receipt = {"schemaVersion": 1, "status": "qc-rejected",
                       "candidate": {"timelineId": "candidate",
                                     "fingerprint": "c" * 64},
                       "parent": {"timelineId": "head", "fingerprint": "p" * 64},
                       "archivePath": os.path.join(tmp, "history", "one")}
            output = io.StringIO()
            with patch.object(native_qc_cli.SyncLock, "acquire",
                              return_value=acquired), \
                    patch.object(native_qc_cli, "PalmierClient", return_value=client), \
                    patch.object(native_qc_cli, "_perform", return_value=receipt), \
                    contextlib.redirect_stdout(output):
                code = native_qc_cli.main(
                    [tmp, "--reject-for-repair", reason])
            lines = output.getvalue().splitlines()
            self.assertEqual((code, len(lines)), (0, 1))
            verdict = json.loads(lines[0])
            self.assertEqual(verdict["status"], "candidate-rejected")
            self.assertEqual(verdict["archivePath"], receipt["archivePath"])


if __name__ == "__main__":
    unittest.main()
