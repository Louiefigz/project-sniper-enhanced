from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from headless.admission_registry import (  # noqa: E402
    AdmissionError,
    AdmissionRequest,
    AttemptStateConflict,
    admit,
)
from headless.attempt_trace import (  # noqa: E402
    AttemptTrace,
    TraceContext,
    TraceCorruption,
)
from headless.durability_controller import (  # noqa: E402
    admit_attempt,
    recover_durable_boundaries,
    resolve_attempt,
)
from headless.terminal_manifest import (  # noqa: E402
    TerminalManifestError,
    TerminalSealRequest,
    seal_terminal_manifest,
    terminal_result_digest,
)

KEY = "11111111-1111-4111-8111-111111111111"
ATTEMPT = "22222222-2222-4222-8222-222222222222"
UNIT = "33333333-3333-4333-8333-333333333333"
DIGEST = hashlib.sha256(b"controller-request").hexdigest()


def _failure(code: str) -> dict:
    return {"schemaVersion": 1, "errorCode": code,
            "evidenceDigest": "0" * 64}


class DurabilityControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.authority = Path(self.temp.name).resolve() / "authority"
        self.authority.mkdir(mode=0o700)
        os.chmod(self.authority, 0o700)

    def _request(self, attempt_id: str = ATTEMPT) -> AdmissionRequest:
        return AdmissionRequest(
            authority_root=str(self.authority), authority_id="authority-mp4-v1",
            idempotency_key=KEY, request_identity_digest=DIGEST,
            attempt_id=attempt_id, unit_id=UNIT,
            first_submitted_at="2026-07-18T12:00:00+00:00",
            release_id="release-test", build_id="build-test",
            policy_id="policy-test", expected_parent=None)

    def _attempt_dir(self) -> Path:
        return self.authority / "attempts" / ATTEMPT

    def _second_request(self) -> AdmissionRequest:
        return replace(
            self._request("44444444-4444-4444-8444-444444444444"),
            idempotency_key="55555555-5555-4555-8555-555555555555",
            unit_id="66666666-6666-4666-8666-666666666666")

    def _trace(self, authority_id: str = "authority-mp4-v1",
               build_id: str = "build-test") -> AttemptTrace:
        context = TraceContext(
            unit_id=UNIT, attempt_id=ATTEMPT, release_id="release-test",
            build_id=build_id, boot_id="boot-a", policy_id="policy-test",
            expected_parent=None, request_digest=DIGEST,
            authority_id=authority_id)
        return AttemptTrace(str(self._attempt_dir()), context)

    def test_admit_and_replay_have_one_authority_bound_trace(self) -> None:
        first = admit_attempt(self._request(), "boot-a")
        replay = admit_attempt(
            replace(self._request(),
                    attempt_id="44444444-4444-4444-8444-444444444444"),
            "boot-a")
        self.assertTrue(first.created)
        self.assertFalse(replay.created)
        self.assertEqual(first.record["schemaVersion"], 2)
        self.assertEqual(first.trace_state.phase, "ADMITTED")
        self.assertEqual(replay.trace_state.record_count, 1)
        frame = json.loads((self._attempt_dir() / "trace.jsonl").read_text())
        self.assertEqual(frame["frameVersion"], 3)
        self.assertEqual(frame["payload"]["authorityId"], "authority-mp4-v1")

    def test_record_before_trace_is_recovered_by_startup_scan(self) -> None:
        with mock.patch(
                "headless.durability_controller.AttemptTrace.ensure_admitted",
                side_effect=RuntimeError("injected death")):
            with self.assertRaisesRegex(RuntimeError, "injected death"):
                admit_attempt(self._request(), "boot-a")
        rows = recover_durable_boundaries(str(self.authority), "boot-a")
        self.assertEqual(rows[0].action, "ADMISSION_TRACE_RECOVERED")
        self.assertEqual(rows[0].reason_code, "ADMISSION_GAP")
        self.assertEqual(self._trace().validate().record_count, 1)

    def test_torn_first_admission_frame_is_replaced_from_denominator(self) -> None:
        admit(self._request())
        trace_path = self._attempt_dir() / "trace.jsonl"
        trace_path.write_bytes(b'{"partialAdmission":')
        trace_path.chmod(0o600)
        rows = recover_durable_boundaries(str(self.authority), "boot-a")
        self.assertEqual(rows[0].action, "ADMISSION_TRACE_RECOVERED")
        self.assertEqual(rows[0].reason_code, "TORN_ADMISSION")
        frame = json.loads(trace_path.read_text())
        self.assertGreater(frame["payload"]["traceRecovery"]["truncatedTailBytes"], 0)

    def test_terminal_result_recovers_without_caller_memory(self) -> None:
        admit_attempt(self._request(), "boot-a")
        trace = self._trace()
        request = TerminalSealRequest(trace, "FAILED", _failure("CRASHED"))
        with mock.patch.object(trace, "append", side_effect=RuntimeError("death")):
            with self.assertRaisesRegex(RuntimeError, "death"):
                seal_terminal_manifest(request)
        rows = recover_durable_boundaries(str(self.authority), "boot-a")
        self.assertEqual(rows[0].action, "TERMINAL_MANIFEST_RECOVERED")
        self.assertTrue(rows[0].terminal)

    def test_startup_repairs_torn_terminal_after_durable_intent(self) -> None:
        admit_attempt(self._request(), "boot-a")
        trace = self._trace()
        request = TerminalSealRequest(trace, "FAILED", _failure("TORN"))
        with mock.patch.object(trace, "append", side_effect=RuntimeError("death")):
            with self.assertRaisesRegex(RuntimeError, "death"):
                seal_terminal_manifest(request)
        path = self._attempt_dir() / "trace.jsonl"
        with path.open("ab") as handle:
            handle.write(b'{"incompleteTerminal":')
            handle.flush()
            os.fsync(handle.fileno())
        rows = recover_durable_boundaries(str(self.authority), "boot-a")
        self.assertEqual(rows[0].action, "TERMINAL_MANIFEST_RECOVERED")
        self.assertTrue(rows[0].terminal)
        self.assertEqual(trace.validate().record_count, 2)

    def test_terminal_trace_without_result_bytes_is_broken(self) -> None:
        admit_attempt(self._request(), "boot-a")
        self._trace().append("TERMINAL_SEALED", {
            "disposition": "FAILED",
            "resultDigest": terminal_result_digest({"lost": True}),
        })
        rows = recover_durable_boundaries(str(self.authority), "boot-a")
        self.assertEqual(rows[0].action, "BROKEN")
        self.assertEqual(rows[0].reason_code, "TERMINAL_RESULT_UNAVAILABLE")
        self.assertFalse(rows[0].terminal)

    def test_terminal_results_are_closed_by_disposition(self) -> None:
        admit_attempt(self._request(), "boot-a")
        trace = self._trace()
        invalid_failures = ({}, {**_failure("FAILED"), "extra": True})
        for result in invalid_failures:
            with self.subTest(failure=result), \
                    self.assertRaisesRegex(TerminalManifestError,
                                           "invalid for disposition"):
                seal_terminal_manifest(TerminalSealRequest(
                    trace, "FAILED", result))
        for event in ("WORKER_START", "VERIFIED", "PUBLISH_INTENT",
                      "POINTER_COMMITTED"):
            trace.append(event)
        invalid_successes = ({}, _failure("FAILED"), {"commitDigest": "a" * 64})
        for result in invalid_successes:
            with self.subTest(success=result), \
                    self.assertRaisesRegex(TerminalManifestError,
                                           "invalid for disposition"):
                seal_terminal_manifest(TerminalSealRequest(
                    trace, "SUCCEEDED", result))
        self.assertFalse((self._attempt_dir() / "terminal-intent.json").exists())

    def test_reboot_is_classified_without_guessing_or_trace_mutation(self) -> None:
        admit_attempt(self._request(), "boot-a")
        trace_path = self._attempt_dir() / "trace.jsonl"
        before = trace_path.read_bytes()
        rows = recover_durable_boundaries(str(self.authority), "boot-b")
        self.assertEqual(rows[0].action, "RECONCILIATION_REQUIRED")
        self.assertEqual(rows[0].reason_code, "HOST_REBOOT")
        self.assertEqual(trace_path.read_bytes(), before)

    def test_trace_cannot_be_rebound_to_another_authority(self) -> None:
        admit_attempt(self._request(), "boot-a")
        with self.assertRaisesRegex(TraceCorruption, "identity changed"):
            self._trace("authority-other").append("WORKER_START")

    def test_terminal_replay_requires_every_admitted_identity_field(self) -> None:
        admit(self._request())
        wrong = self._trace(build_id="build-other")
        wrong.append("ADMITTED")
        seal_terminal_manifest(
            TerminalSealRequest(wrong, "FAILED", _failure("WRONG_BUILD")))
        with self.assertRaisesRegex(AdmissionError, "does not match admission"):
            admit(self._request())

    def test_concurrent_controller_replay_appends_admitted_once(self) -> None:
        requests = [self._request(
            f"{index + 10:08d}-aaaa-4aaa-8aaa-{index + 10:012d}")
                    for index in range(8)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(
                lambda request: admit_attempt(request, "boot-a"), requests))
        self.assertEqual(sum(outcome.created for outcome in outcomes), 1)
        self.assertEqual({outcome.record["attemptId"] for outcome in outcomes},
                         {outcomes[0].record["attemptId"]})
        attempt = self.authority / "attempts" / outcomes[0].record["attemptId"]
        self.assertEqual(len((attempt / "trace.jsonl").read_text().splitlines()), 1)

    def test_restrictive_umask_cannot_strand_new_trace_files(self) -> None:
        previous = os.umask(0o777)
        try:
            outcome = admit_attempt(self._request(), "boot-a")
        finally:
            os.umask(previous)
        self.assertEqual(outcome.trace_state.record_count, 1)
        for name in (".trace.lock", "trace.jsonl"):
            mode = (self._attempt_dir() / name).stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)
        self.assertEqual(self._trace().validate().record_count, 1)

    def test_corrupt_old_attempt_does_not_hide_healthy_scan_rows(self) -> None:
        first = admit_attempt(self._request(), "boot-a")
        second = admit_attempt(self._second_request(), "boot-a")
        path = self.authority / "attempts" / first.record["attemptId"] / "trace.jsonl"
        path.write_bytes(path.read_bytes().replace(
            b'"event":"ADMITTED"', b'"event":"ADMIXTED"'))
        rows = recover_durable_boundaries(str(self.authority), "boot-a")
        by_attempt = {row.attempt_id: row for row in rows}
        self.assertEqual(by_attempt[first.record["attemptId"]].action, "BROKEN")
        self.assertEqual(by_attempt[first.record["attemptId"]].reason_code,
                         "TRACE_CORRUPT")
        self.assertEqual(by_attempt[second.record["attemptId"]].action,
                         "RECONCILIATION_REQUIRED")

    def test_unsafe_old_attempt_path_does_not_abort_healthy_scan(self) -> None:
        first = admit_attempt(self._request(), "boot-a")
        second = admit_attempt(self._second_request(), "boot-a")
        old_dir = self.authority / "attempts" / first.record["attemptId"]
        os.chmod(old_dir, 0o755)
        rows = recover_durable_boundaries(str(self.authority), "boot-a")
        by_attempt = {row.attempt_id: row for row in rows}
        self.assertEqual(by_attempt[first.record["attemptId"]].reason_code,
                         "ATTEMPT_PATH_UNSAFE")
        self.assertEqual(by_attempt[second.record["attemptId"]].action,
                         "RECONCILIATION_REQUIRED")

    def test_initialized_running_attempt_is_never_recreated_if_lost(self) -> None:
        admit_attempt(self._request(), "boot-a")
        self._trace().append("WORKER_START")
        lost = self.authority / "lost-running-attempt"
        os.rename(self._attempt_dir(), lost)
        with self.assertRaisesRegex(AttemptStateConflict, "missing"):
            resolve_attempt(str(self.authority), ATTEMPT, "boot-a")
        self.assertFalse(self._attempt_dir().exists())
        row = recover_durable_boundaries(
            str(self.authority), "boot-a")[0]
        self.assertEqual((row.action, row.reason_code),
                         ("BROKEN", "ATTEMPT_PATH_UNSAFE"))

    def test_initialized_attempt_rejects_fresh_directory_at_same_path(self) -> None:
        admit_attempt(self._request(), "boot-a")
        self._trace().append("WORKER_START")
        old = self.authority / "replaced-running-attempt"
        os.rename(self._attempt_dir(), old)
        self._attempt_dir().mkdir(mode=0o700)
        os.chmod(self._attempt_dir(), 0o700)
        with self.assertRaisesRegex(AttemptStateConflict, "identity changed"):
            resolve_attempt(str(self.authority), ATTEMPT, "boot-a")
        row = recover_durable_boundaries(
            str(self.authority), "boot-a")[0]
        self.assertEqual((row.action, row.reason_code),
                         ("BROKEN", "ATTEMPT_PATH_UNSAFE"))

    def test_one_authority_root_cannot_mix_authority_ids(self) -> None:
        admit_attempt(self._request(), "boot-a")
        conflicting = replace(
            self._second_request(), authority_id="authority-mp4-other")
        with self.assertRaisesRegex(AdmissionError, "bound to another ID"):
            admit_attempt(conflicting, "boot-a")
        path = self.authority / "authority.json"
        self.assertEqual(json.loads(path.read_text())["authorityId"],
                         "authority-mp4-v1")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main(verbosity=2)
