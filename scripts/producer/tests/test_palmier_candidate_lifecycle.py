"""A new Palmier AI request never orphans the prior candidate evidence."""
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
from palmier.candidate_receipt import load_candidate, save_candidate
from palmier.mcp_client import PalmierError
from palmier.native_candidate_lifecycle import discard_candidate
from palmier.native_delta import NativeRequest, execute_native_candidate
import palmier.native_candidate_lifecycle as lifecycle
import palmier.native_delta_cli as native_cli
from palmier.sync_lock import SyncLockState
from palmier.timeline_authority import TimelineConflict
from test_palmier_native_delta import NativeClient, _plan, _record


def _bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


class CandidateLifecycleTests(unittest.TestCase):
    def _first(self, tmp: str) -> tuple[NativeClient, dict]:
        client = NativeClient()
        authority = _record(tmp, client)
        execute_native_candidate(
            client, tmp, NativeRequest({"projectId": "project-1"},
                                       _plan(authority)))
        return client, authority

    def test_second_request_preserves_edited_receipt_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, authority = self._first(tmp)
            candidate_path = os.path.join(tmp, "palmier.timeline-candidate.json")
            evidence_path = os.path.join(tmp, "candidate-review-evidence.json")
            with open(evidence_path, "w", encoding="utf-8") as handle:
                json.dump({"candidate": "first", "finding": "keep me"}, handle)
            before = (_bytes(candidate_path), _bytes(evidence_path))
            forks = sum(name == "create_timeline" for name, _ in client.calls)
            with self.assertRaisesRegex(PalmierError, "already edited"):
                execute_native_candidate(
                    client, tmp, NativeRequest({"projectId": "project-1"},
                                               _plan(authority, 0.25)))
            self.assertEqual(sum(name == "create_timeline" for name, _ in client.calls),
                             forks)
            self.assertEqual((_bytes(candidate_path), _bytes(evidence_path)), before)
            self.assertEqual(client.active, "head")

    def test_second_request_preserves_stale_qc_approved_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, authority = self._first(tmp)
            candidate = load_candidate(tmp)
            candidate.update({"status": "qc-approved", "qc": {
                "status": "approved", "approved": True,
                "approvalDigest": "stale-approval"}})
            save_candidate(tmp, candidate)
            qc_path = os.path.join(tmp, "palmier.native-qc.json")
            export_path = os.path.join(tmp, "palmier.candidate.mp4")
            with open(export_path, "wb") as handle:
                handle.write(b"changed-export")
            with open(qc_path, "w", encoding="utf-8") as handle:
                json.dump({"schemaVersion": 1, "status": "qc-approved",
                           "approvalDigest": "different-stale-proof",
                           "export": {"path": export_path,
                                      "hash": hashlib.sha256(
                                          b"old-export").hexdigest()}}, handle)
            candidate_path = os.path.join(tmp, "palmier.timeline-candidate.json")
            before = (_bytes(candidate_path), _bytes(qc_path))
            forks = sum(name == "create_timeline" for name, _ in client.calls)
            with self.assertRaisesRegex(PalmierError, "use the approved candidate"):
                execute_native_candidate(
                    client, tmp, NativeRequest({"projectId": "project-1"},
                                               _plan(authority, 0.25)))
            self.assertEqual(sum(name == "create_timeline" for name, _ in client.calls),
                             forks)
            self.assertEqual((_bytes(candidate_path), _bytes(qc_path)), before)
            client.active = "candidate"
            discarded = discard_candidate(client, tmp)
            with open(os.path.join(discarded["archivePath"], "archive.json"),
                      encoding="utf-8") as handle:
                evidence = json.load(handle)["evidence"]
            self.assertNotIn("candidate-export",
                             {row["label"] for row in evidence})
            with open(os.path.join(discarded["archivePath"], "qc.json"),
                      encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["status"], "not-started")
            self.assertEqual(_bytes(qc_path), before[1])

    def test_explicit_discard_archives_then_allows_a_new_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, authority = self._first(tmp)
            candidate = load_candidate(tmp)
            native_input = os.path.join(tmp, "native-input.json")
            with open(native_input, "wb") as handle:
                handle.write(b'{"request":"first"}\n')
            candidate["nativeAuthority"] = {"nativeInput": {
                "path": native_input,
                "hash": hashlib.sha256(_bytes(native_input)).hexdigest()}}
            save_candidate(tmp, candidate)
            original = load_candidate(tmp)
            switches = sum(name == "set_active_timeline"
                           for name, _args in client.calls)
            result = discard_candidate(client, tmp)
            archived_candidate = os.path.join(result["archivePath"], "candidate.json")
            archived_manifest = os.path.join(result["archivePath"], "archive.json")
            with open(archived_candidate, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), original)
            with open(archived_manifest, encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["state"], "discarded")
            self.assertEqual(manifest["evidence"][0]["label"], "native-input")
            self.assertEqual(load_candidate(tmp)["status"], "discarded")
            self.assertEqual(client.active, "head")
            self.assertEqual(sum(name == "set_active_timeline"
                                 for name, _args in client.calls), switches)
            replacement = execute_native_candidate(
                client, tmp, NativeRequest({"projectId": "project-1"},
                                           _plan(authority, 0.25)))
            self.assertEqual(replacement["status"], "edited")

    def test_discard_refuses_to_hide_an_unrelated_visible_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, _authority = self._first(tmp)
            before = _bytes(os.path.join(tmp, "palmier.timeline-candidate.json"))
            client.timelines["other"] = {**client.timelines["head"], "id": "other"}
            client.active = "other"
            with self.assertRaisesRegex(PalmierError, "another timeline"):
                discard_candidate(client, tmp)
            self.assertEqual(client.active, "other")
            self.assertEqual(_bytes(os.path.join(
                tmp, "palmier.timeline-candidate.json")), before)

    def test_discard_preserves_a_manually_changed_visible_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, _authority = self._first(tmp)
            candidate_path = os.path.join(tmp, "palmier.timeline-candidate.json")
            before = _bytes(candidate_path)
            client.active = "candidate"
            client.timelines["candidate"]["tracks"][0]["clips"][0]["opacity"] = 0.2
            with self.assertRaisesRegex(PalmierError, "changed manually"):
                discard_candidate(client, tmp)
            self.assertEqual(client.active, "candidate")
            self.assertEqual(_bytes(candidate_path), before)
            self.assertFalse(os.path.exists(os.path.join(
                tmp, ".sniper-learning", "native-qc-history")))

    def test_discard_rechecks_candidate_after_slow_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, _authority = self._first(tmp)
            client.active = "candidate"
            candidate_path = os.path.join(tmp, "palmier.timeline-candidate.json")
            before = _bytes(candidate_path)
            real_archive = lifecycle.archive_discarded_candidate

            def archive_then_mutate(*args):
                archive = real_archive(*args)
                client.timelines["candidate"]["tracks"][0]["clips"][0][
                    "opacity"] = 0.25
                return archive

            with patch.object(lifecycle, "archive_discarded_candidate",
                              side_effect=archive_then_mutate), \
                    self.assertRaisesRegex(TimelineConflict,
                                            "changed while the candidate was being"):
                discard_candidate(client, tmp)
            self.assertEqual(client.active, "candidate")
            self.assertEqual(_bytes(candidate_path), before)

    def test_discard_rechecks_unchanged_visible_parent_without_switching(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, _authority = self._first(tmp)
            candidate_path = os.path.join(tmp, "palmier.timeline-candidate.json")
            before = _bytes(candidate_path)
            switches = sum(name == "set_active_timeline"
                           for name, _args in client.calls)
            real_archive = lifecycle.archive_discarded_candidate

            def archive_then_mutate(*args):
                archive = real_archive(*args)
                client.timelines["head"]["tracks"][0]["clips"][0]["opacity"] = 0.3
                return archive

            with patch.object(lifecycle, "archive_discarded_candidate",
                              side_effect=archive_then_mutate), \
                    self.assertRaisesRegex(TimelineConflict,
                                            "Palmier parent changed while"):
                discard_candidate(client, tmp)
            self.assertEqual(client.active, "head")
            self.assertEqual(_bytes(candidate_path), before)
            self.assertEqual(sum(name == "set_active_timeline"
                                 for name, _args in client.calls), switches)

    def test_candidate_two_discard_ignores_candidate_one_qc(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, _authority = self._first(tmp)
            candidate = load_candidate(tmp)
            current_input = os.path.join(tmp, "candidate-two-input.json")
            stale_input = os.path.join(tmp, "candidate-one-input.json")
            for path, request in ((current_input, "second"),
                                  (stale_input, "first")):
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump({"request": request}, handle)
            candidate["nativeAuthority"] = {"nativeInput": {
                "path": current_input,
                "hash": hashlib.sha256(_bytes(current_input)).hexdigest()}}
            save_candidate(tmp, candidate)
            stale_qc = {
                "schemaVersion": 1, "status": "prepared",
                "candidate": {"projectId": candidate["projectId"],
                              "timelineId": "candidate-one",
                              "fingerprint": "1" * 64},
                "authority": {"nativeInput": {
                    "path": stale_input,
                    "hash": hashlib.sha256(_bytes(stale_input)).hexdigest()}},
            }
            qc_path = os.path.join(tmp, "palmier.native-qc.json")
            with open(qc_path, "w", encoding="utf-8") as handle:
                json.dump(stale_qc, handle)
            stale_bytes = _bytes(qc_path)
            client.active = "candidate"
            discarded = discard_candidate(client, tmp)
            self.assertEqual(_bytes(qc_path), stale_bytes)
            with open(os.path.join(discarded["archivePath"], "qc.json"),
                      encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["status"], "not-started")
            with open(os.path.join(discarded["archivePath"], "archive.json"),
                      encoding="utf-8") as handle:
                evidence = json.load(handle)["evidence"]
            native = next(row for row in evidence if row["label"] == "native-input")
            self.assertEqual(native["sourcePath"], os.path.realpath(current_input))

    def test_locked_cli_exposes_the_explicit_discard_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, _authority = self._first(tmp)
            client.active = "candidate"
            lease = SimpleNamespace(active=True)
            lease.release = lambda: setattr(lease, "active", False)
            client.lock_probe = lambda: self.assertTrue(lease.active)
            acquired = SimpleNamespace(
                state=SyncLockState.ACQUIRED, lease=lease)
            output = io.StringIO()
            with patch.object(native_cli, "PalmierClient", return_value=client), \
                    patch.object(native_cli.SyncLock, "acquire",
                                 return_value=acquired), \
                    contextlib.redirect_stdout(output):
                code = native_cli.main([tmp, "--discard-candidate"])
            verdict = json.loads(output.getvalue())
            self.assertEqual((code, verdict["status"]),
                             (0, "candidate-discarded"))
            self.assertTrue(os.path.isfile(os.path.join(
                verdict["archivePath"], "archive.json")))
            self.assertEqual(client.active, "head")
            self.assertFalse(lease.active)


if __name__ == "__main__":
    unittest.main()
