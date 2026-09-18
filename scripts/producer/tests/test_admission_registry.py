from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from headless.admission_registry import (  # noqa: E402
    AdmissionRequest,
    AttemptConflict,
    IdempotencyConflict,
    admit,
    list_admissions,
)
from headless.attempt_trace import (  # noqa: E402
    AttemptTrace,
    TraceContext,
    TraceCorruption,
)
from headless.terminal_manifest import (  # noqa: E402
    TerminalManifestError,
    TerminalSealRequest,
    recover_terminal_manifest,
    seal_terminal_manifest,
    terminal_result_digest,
)

KEY = "11111111-1111-4111-8111-111111111111"
ATTEMPT = "22222222-2222-4222-8222-222222222222"
UNIT = "33333333-3333-4333-8333-333333333333"
REQUEST_DIGEST = hashlib.sha256(b"admission-request").hexdigest()
EVIDENCE_DIGEST = "0" * 64


def _failure(code: str) -> dict:
    return {"schemaVersion": 1, "errorCode": code,
            "evidenceDigest": EVIDENCE_DIGEST}


def _success() -> dict:
    generation = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    return {
        "schemaVersion": 1, "authorityId": "authority-mp4-v1",
        "publicationSeq": 1, "generationId": generation,
        "commitDigest": "a" * 64, "generationVerificationDigest": "b" * 64,
        "mp4RelativePath": f"generations/{generation}/final.mp4",
        "sha256": "c" * 64,
        "mediaFacts": {
            "width": 1080, "height": 1920, "durationSeconds": 60.0,
            "fps": 30.0, "frameCount": 1800, "sizeBytes": 1_000_000,
            "videoCodec": "h264", "audioCodec": "aac",
        },
    }


class AdmissionRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.authority = Path(self.temp.name).resolve() / "authority"
        self.authority.mkdir(mode=0o700)
        os.chmod(self.authority, 0o700)

    def _request(self) -> AdmissionRequest:
        return AdmissionRequest(
            authority_root=str(self.authority), authority_id="authority-mp4-v1",
            idempotency_key=KEY, request_identity_digest=REQUEST_DIGEST,
            attempt_id=ATTEMPT, unit_id=UNIT,
            first_submitted_at="2026-07-18T12:00:00+00:00",
            release_id="release-test", build_id="build-test",
            policy_id="policy-test", expected_parent=None)

    def _attempt_dir(self, attempt_id: str = ATTEMPT) -> Path:
        return self.authority / "attempts" / attempt_id

    def _trace(self) -> AttemptTrace:
        context = TraceContext(
            unit_id=UNIT, attempt_id=ATTEMPT, release_id="release-test",
            build_id="build-test", boot_id="boot-test", policy_id="policy-test",
            expected_parent=None, request_digest=REQUEST_DIGEST,
            authority_id="authority-mp4-v1")
        return AttemptTrace(str(self._attempt_dir()), context)

    def test_new_admission_and_same_identity_replay(self) -> None:
        created = admit(self._request())
        self.assertTrue(created.created)
        self.assertTrue(self._attempt_dir().is_dir())
        replay_request = replace(
            self._request(), attempt_id="44444444-4444-4444-8444-444444444444",
            first_submitted_at="2026-07-18T12:01:00+00:00")
        replay = admit(replay_request)
        self.assertFalse(replay.created)
        self.assertEqual(replay.record, created.record)
        self.assertEqual(list_admissions(str(self.authority)), [created.record])

    def test_changed_request_or_unit_conflicts(self) -> None:
        admit(self._request())
        changed = (
            replace(self._request(), request_identity_digest="0" * 64),
            replace(self._request(), unit_id="55555555-5555-4555-8555-555555555555"),
            replace(self._request(), build_id="build-other"),
        )
        for request in changed:
            with self.subTest(request=request), self.assertRaises(IdempotencyConflict):
                admit(request)

    def test_attempt_id_cannot_be_claimed_by_another_key(self) -> None:
        admit(self._request())
        other = replace(
            self._request(), idempotency_key="66666666-6666-4666-8666-666666666666",
            unit_id="77777777-7777-4777-8777-777777777777")
        with self.assertRaises(AttemptConflict):
            admit(other)

    def test_record_before_attempt_crash_is_healed_by_replay(self) -> None:
        with mock.patch("headless.admission_registry._initialize",
                        side_effect=RuntimeError("injected crash")):
            with self.assertRaisesRegex(RuntimeError, "injected crash"):
                admit(self._request())
        self.assertEqual(len(list_admissions(str(self.authority))), 1)
        self.assertFalse(self._attempt_dir().exists())
        replay = admit(self._request())
        self.assertFalse(replay.created)
        self.assertTrue(self._attempt_dir().is_dir())

    def test_terminal_manifest_is_returned_without_losing_denominator(self) -> None:
        admit(self._request())
        trace = self._trace()
        trace.append("ADMITTED")
        terminal = seal_terminal_manifest(
            TerminalSealRequest(trace, "FAILED", _failure("RENDER_FAILED")))
        replay = admit(self._request())
        self.assertEqual(replay.terminal_manifest, terminal)
        self.assertEqual(len(list_admissions(str(self.authority))), 1)

    def test_success_manifest_requires_full_publication_sequence(self) -> None:
        admit(self._request())
        trace = self._trace()
        trace.append("ADMITTED")
        with self.assertRaisesRegex(TraceCorruption, "committed pointer"):
            seal_terminal_manifest(TerminalSealRequest(trace, "SUCCEEDED", {}))
        for event in ("WORKER_START", "VERIFIED", "PUBLISH_INTENT",
                      "POINTER_COMMITTED"):
            trace.append(event)
        manifest = seal_terminal_manifest(
            TerminalSealRequest(trace, "SUCCEEDED", _success()))
        self.assertEqual(manifest["disposition"], "SUCCEEDED")

    def test_manifest_recovers_after_terminal_trace_and_torn_pending(self) -> None:
        admit(self._request())
        trace = self._trace()
        trace.append("ADMITTED")
        result = _failure("RECOVERED_FAILURE")
        trace.append("TERMINAL_SEALED", {
            "disposition": "FAILED",
            "resultDigest": terminal_result_digest(result),
        })
        pending = self._attempt_dir() / ".terminal-manifest.pending"
        pending.write_bytes(b'{"torn":')
        pending.chmod(0o600)
        manifest = seal_terminal_manifest(
            TerminalSealRequest(trace, "FAILED", result))
        self.assertEqual(manifest["result"], result)
        self.assertFalse(pending.exists())

    def test_terminal_trace_rejects_different_recovery_result(self) -> None:
        admit(self._request())
        trace = self._trace()
        trace.append("ADMITTED")
        trace.append("TERMINAL_SEALED", {
            "disposition": "FAILED",
            "resultDigest": terminal_result_digest(_failure("CODE_A")),
        })
        with self.assertRaisesRegex(TerminalManifestError, "result"):
            seal_terminal_manifest(
                TerminalSealRequest(trace, "FAILED", _failure("CODE_B")))

    def test_terminal_result_is_immutable(self) -> None:
        admit(self._request())
        trace = self._trace()
        trace.append("ADMITTED")
        seal_terminal_manifest(
            TerminalSealRequest(trace, "FAILED", _failure("CODE_A")))
        with self.assertRaisesRegex(TerminalManifestError, "result"):
            seal_terminal_manifest(
                TerminalSealRequest(trace, "FAILED", _failure("CODE_B")))

    def test_recovery_has_result_bytes_after_death_before_terminal_trace(self) -> None:
        admit(self._request())
        trace = self._trace()
        trace.append("ADMITTED")
        request = TerminalSealRequest(trace, "FAILED", _failure("CRASHED"))
        with mock.patch.object(trace, "append", side_effect=RuntimeError("death")):
            with self.assertRaisesRegex(RuntimeError, "death"):
                seal_terminal_manifest(request)
        self.assertTrue((self._attempt_dir() / "terminal-intent.json").is_file())
        self.assertFalse((self._attempt_dir() / "terminal-manifest.json").exists())
        recovered = recover_terminal_manifest(trace)
        self.assertEqual(recovered["result"], _failure("CRASHED"))
        self.assertEqual(trace.validate().terminal_disposition, "FAILED")

    def test_recovery_finishes_after_death_between_trace_and_manifest(self) -> None:
        admit(self._request())
        trace = self._trace()
        trace.append("ADMITTED")
        request = TerminalSealRequest(trace, "FAILED", _failure("CRASHED"))
        with mock.patch("headless.terminal_manifest.write_pending_replace",
                        side_effect=RuntimeError("death")):
            with self.assertRaisesRegex(RuntimeError, "death"):
                seal_terminal_manifest(request)
        self.assertEqual(trace.validate().terminal_disposition, "FAILED")
        self.assertFalse((self._attempt_dir() / "terminal-manifest.json").exists())
        recovered = recover_terminal_manifest(trace)
        self.assertEqual(recovered["result"], _failure("CRASHED"))

    def test_recovery_repairs_torn_tail_from_durable_terminal_intent(self) -> None:
        admit(self._request())
        trace = self._trace()
        trace.append("ADMITTED")
        request = TerminalSealRequest(trace, "FAILED", _failure("TORN_FAILURE"))
        with mock.patch.object(trace, "append", side_effect=RuntimeError("death")):
            with self.assertRaises(RuntimeError):
                seal_terminal_manifest(request)
        path = self._attempt_dir() / "trace.jsonl"
        with path.open("ab") as handle:
            handle.write(b'{"incompleteTerminal":')
            handle.flush()
            os.fsync(handle.fileno())
        recovered = recover_terminal_manifest(trace)
        self.assertEqual(recovered["result"], _failure("TORN_FAILURE"))
        self.assertEqual(trace.validate().record_count, 2)

    def test_replay_revalidates_manifest_against_trace(self) -> None:
        admit(self._request())
        trace = self._trace()
        trace.append("ADMITTED")
        seal_terminal_manifest(
            TerminalSealRequest(trace, "FAILED", _failure("CODE_A")))
        path = self._attempt_dir() / "trace.jsonl"
        raw = path.read_bytes().replace(b'"disposition":"FAILED"',
                                        b'"disposition":"STALE"')
        path.write_bytes(raw)
        with self.assertRaisesRegex(TerminalManifestError, "trace is invalid"):
            admit(self._request())

    def test_restrictive_umask_does_not_weaken_authority_files(self) -> None:
        previous = os.umask(0o777)
        try:
            outcome = admit(self._request())
        finally:
            os.umask(previous)
        self.assertTrue(outcome.created)
        lock = self.authority / ".admission.lock"
        record = next((self.authority / "admissions").glob("*.json"))
        self.assertEqual(lock.stat().st_mode & 0o777, 0o600)
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self._attempt_dir().stat().st_mode & 0o777, 0o700)

    def test_concurrent_processes_share_one_durable_admission(self) -> None:
        script = _CHILD_ADMIT.format(producer=str(PRODUCER_DIR))
        processes = []
        for index in range(8):
            attempt = f"{index + 10:08d}-aaaa-4aaa-8aaa-{index + 10:012d}"
            processes.append(subprocess.Popen(
                [sys.executable, "-c", script, str(self.authority), attempt],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        outputs = [process.communicate(timeout=10) for process in processes]
        self.assertTrue(all(process.returncode == 0 for process in processes), outputs)
        rows = [json.loads(stdout) for stdout, _ in outputs]
        self.assertEqual(sum(row["created"] for row in rows), 1)
        self.assertEqual(len({row["attemptId"] for row in rows}), 1)
        self.assertEqual(len(list_admissions(str(self.authority))), 1)


_CHILD_ADMIT = r'''import json, sys
sys.path.insert(0, {producer!r})
from headless.admission_registry import AdmissionRequest, admit
request = AdmissionRequest(sys.argv[1], "authority-mp4-v1",
    "11111111-1111-4111-8111-111111111111",
    "''' + REQUEST_DIGEST + r'''", sys.argv[2],
    "33333333-3333-4333-8333-333333333333",
    "2026-07-18T12:00:00+00:00", "release-test", "build-test",
    "policy-test", None)
outcome = admit(request)
print(json.dumps({{"created": outcome.created,
                   "attemptId": outcome.record["attemptId"]}}))
'''


if __name__ == "__main__":
    unittest.main(verbosity=2)
