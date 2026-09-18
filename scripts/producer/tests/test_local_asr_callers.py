"""Caller clock/ownership faults with fake ASR only; no model or media execution."""
from __future__ import annotations

import asyncio
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "producer"))

import asr_policy
import local_asr_cli as cli
import local_asr_deadline as clock
import transcribe
from study import study_transcribe as study
from study import study_transcribe_local as standalone
from producer import ingest_scan

PAYLOAD = {"status": "done", "model": "TEST-only", "duration": 1,
           "transcript": [{"text": "TEST", "words": [{"word": "TEST", "start": 0, "end": 1}]}]}


class LocalCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.now = [10.0]
        self.output = io.StringIO()
        self.stack.enter_context(mock.patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(mock.patch.object(clock.time, "monotonic", side_effect=lambda: self.now[0]))
        self.stack.enter_context(redirect_stdout(self.output))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.exists = self.stack.enter_context(mock.patch.object(transcribe.os.path, "exists", return_value=True))
        self.probe = self.stack.enter_context(mock.patch.object(transcribe, "probe_transcribe_input",
                                                               side_effect=AssertionError("NO EXTRA PROBE")))
        self.local = self.stack.enter_context(mock.patch.object(transcribe, "transcribe_media", return_value=PAYLOAD))

    def invoke(self, flags: list[str]) -> None:
        with mock.patch.object(sys, "argv", ["transcribe.py", "/TEST/media", *flags]):
            asyncio.run(asr_policy.run_asr_cli(transcribe.main))

    def test_local_has_one_source_probe_and_forwards_original_expiry(self) -> None:
        self.invoke(["--provider", "local-whisper", "--local-asr-expires-at", "15"])
        self.assertEqual(self.local.call_args.kwargs["deadline"].expires_at, 15)
        self.probe.assert_not_called()
        self.assertEqual(json.loads(self.output.getvalue())["status"], "done")

    def test_expired_parent_blocks_before_source_stat_or_core(self) -> None:
        with self.assertRaises(SystemExit):
            self.invoke(["--local-asr-expires-at", "9"])
        self.exists.assert_not_called()
        self.local.assert_not_called()

    def test_malformed_duplicate_extra_and_abbreviated_controls_never_probe(self) -> None:
        cases = [["--local-asr-expires-at", value] for value in ("nan", "inf", "-2", "x", "1" * 65)]
        cases += [["--local-asr-exp", "15"], ["extra"], ["--unknown"],
                  ["--local-asr-expires-at", "15", "--local-asr-expires-at", "16"],
                  ["--local-asr-owned-worker", "--local-asr-owned-worker"]]
        for flags in cases:
            with self.subTest(flags=flags), self.assertRaises(SystemExit):
                self.invoke(flags)
        self.exists.assert_not_called()
        self.local.assert_not_called()

    def test_local_controls_rejected_on_explicit_paid_branch_before_source(self) -> None:
        with self.assertRaises(SystemExit):
            self.invoke(["--provider", "deepgram", "--authorize-paid-asr", "deepgram",
                         "--local-asr-expires-at", "15"])
        self.exists.assert_not_called()
        self.local.assert_not_called()

    def test_shared_group_is_explicit_and_enters_before_core(self) -> None:
        with mock.patch.object(cli, "use_local_asr_worker_group") as group:
            group.return_value.__enter__.side_effect = lambda: self.local.assert_not_called()
            self.invoke(["--local-asr-owned-worker", "--local-asr-expires-at", "15"])
            group.assert_called_once_with()
        self.local.assert_called_once()

    def test_unverified_group_blocks_before_source_read(self) -> None:
        with mock.patch.object(cli, "use_local_asr_worker_group", side_effect=RuntimeError("TEST group unknown")), \
                self.assertRaises(SystemExit):
            self.invoke(["--local-asr-owned-worker"])
        self.exists.assert_not_called()
        self.local.assert_not_called()

    def test_core_or_serialization_overrun_emits_no_done(self) -> None:
        def late(*args: object, **kwargs: object) -> dict:
            self.now[0] = 16
            return PAYLOAD
        self.local.side_effect = late
        with self.assertRaises(SystemExit):
            self.invoke(["--local-asr-expires-at", "15"])
        self.assertNotIn('"status": "done"', self.output.getvalue())
        self.now[0] = 10
        original = json.dumps
        def encode(value: object, **kwargs: object) -> str:
            self.now[0] = 16
            return original(value, **kwargs)
        with mock.patch.object(cli.json, "dumps", side_effect=encode), \
                self.assertRaises(clock.LocalAsrDeadlineError):
            cli.emit_local_result(PAYLOAD, clock.LocalAsrDeadline(15))


class StudyDeadlineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.now = [10.0]
        self.stack.enter_context(mock.patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(mock.patch.object(clock.time, "monotonic", side_effect=lambda: self.now[0]))
        self.proc = subprocess.CompletedProcess([], 0, json.dumps(PAYLOAD), "")
        self.runner = self.stack.enter_context(mock.patch.object(study, "run_text", return_value=self.proc))

    def test_minimum_of_study_configured_and_parent_clocks_is_forwarded(self) -> None:
        cases = [(None, {}, 1810), (clock.LocalAsrDeadline(14), {}, 14),
                 (None, {clock.TIMEOUT_ENV: "7"}, 17)]
        for parent, env, expected in cases:
            with self.subTest(expected=expected), mock.patch.dict(os.environ, env, clear=True):
                result = study.run_transcribe_worker("/TEST/media", parent)
                self.assertNotIn("skipped", result)
                request = self.runner.call_args.args[0]
                self.assertEqual(request.timeout_seconds, expected - 10)
                self.assertEqual(float(request.command[-2]), expected)
                self.assertEqual(request.command[-1], "--local-asr-owned-worker")
                self.assertEqual(request.max_output_bytes, 16 * 1024 * 1024)

    def test_inherited_active_clock_is_not_reset_by_study(self) -> None:
        with clock.use_local_asr_deadline(clock.LocalAsrDeadline(15)):
            study.transcribe_profile("/TEST/media")
        self.assertEqual(self.runner.call_args.args[0].timeout_seconds, 5)

    def test_expired_parent_does_not_spawn(self) -> None:
        self.assertIn("skipped", study.run_transcribe_worker("/TEST/media", clock.LocalAsrDeadline(9)))
        self.runner.assert_not_called()

    def test_cleanup_or_parse_or_summary_overrun_is_not_accepted(self) -> None:
        def late(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
            self.now[0] = 16
            return self.proc
        self.runner.side_effect = late
        self.assertIn("skipped", study.run_transcribe_worker("/TEST/media", clock.LocalAsrDeadline(15)))
        self.runner.side_effect = None
        self.now[0] = 10
        with mock.patch.object(study, "_parse_done_line", side_effect=lambda raw, guard=None: late() and PAYLOAD):
            self.assertIn("skipped", study.run_transcribe_worker("/TEST/media", clock.LocalAsrDeadline(15)))
        self.now[0] = 10
        with mock.patch.object(study, "_summarize", side_effect=lambda value: late() and {"wordCount": 1}):
            self.assertIn("skipped", study.transcribe_profile("/TEST/media", clock.LocalAsrDeadline(15)))

    def test_explicit_paid_branch_retains_authorization_and_no_local_flags(self) -> None:
        with asr_policy.use_asr_invocation(asr_policy.AsrInvocation("deepgram", "deepgram")), \
                mock.patch.object(study.subprocess, "run", return_value=self.proc) as paid:
            result = study.run_transcribe_worker("/TEST/media")
        self.assertEqual(result, PAYLOAD)
        self.runner.assert_not_called()
        self.assertEqual(paid.call_args.args[0][-4:], ["--provider", "deepgram", "--authorize-paid-asr", "deepgram"])

    def test_study_rejects_malformed_error_or_duplicate_done_anywhere(self) -> None:
        done = json.dumps(PAYLOAD)
        for raw in [done + "\nTEST trailing", done + "\n" + done, "null\n" + done,
                    '{"error":"TEST"}\n' + done, done + '\n{"status":"extracting_audio"}']:
            with self.subTest(raw=raw):
                self.proc.stdout = raw
                self.assertIn("skipped", study.run_transcribe_worker("/TEST/media"))

    def test_study_passes_original_guard_into_stream_validation(self) -> None:
        with mock.patch.object(study, "parse_transcription_output", return_value=PAYLOAD) as parser:
            study.run_transcribe_worker("/TEST/media", clock.LocalAsrDeadline(15))
        guard = parser.call_args.args[1]
        self.assertEqual(guard.__self__.expires_at, 15)
        self.now[0] = 16
        with self.assertRaises(clock.LocalAsrDeadlineError):
            guard()


class StandaloneStudyTests(unittest.TestCase):
    def test_real_help_imports_without_pythonpath_or_model_invocation(self) -> None:
        script = SCRIPTS / "producer" / "study" / "study_transcribe_local.py"
        env = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "SNIPER_DEBUG": "0"}
        result = subprocess.run((sys.executable, "-B", str(script), "--help"),
                                env=env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--local-asr-owned-worker", result.stdout)

    def test_guarded_atomic_write_preserves_prior_file_on_serialization_expiry(self) -> None:
        now = [10.0]
        original = json.dump
        def write_then_expire(value: object, handle: object, **kwargs: object) -> None:
            original(value, handle, **kwargs)
            now[0] = 16
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(clock.time, "monotonic", side_effect=lambda: now[0]), \
                mock.patch.object(standalone, "transcribe_media", return_value=PAYLOAD), \
                mock.patch.object(ingest_scan.json, "dump", side_effect=write_then_expire), \
                redirect_stdout(io.StringIO()) as output:
            target = Path(tmp) / "transcript.json"
            target.write_text("TEST prior bytes")
            with self.assertRaises(clock.LocalAsrDeadlineError):
                standalone.write_transcript("/TEST/media", str(target), clock.LocalAsrDeadline(15))
            self.assertEqual(target.read_text(), "TEST prior bytes")
            self.assertEqual(list(Path(tmp).iterdir()), [target])
            self.assertNotIn('"status": "done"', output.getvalue())

    def test_standalone_deadline_covers_core_and_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(clock.time, "monotonic", return_value=10), \
                mock.patch.object(standalone, "transcribe_media", return_value=PAYLOAD) as core, \
                redirect_stdout(io.StringIO()) as output:
            target = Path(tmp) / "transcript.json"
            standalone.write_transcript("/TEST/media", str(target))
            self.assertEqual(core.call_args.kwargs["deadline"].expires_at, 1810)
            self.assertEqual(json.loads(target.read_text()), PAYLOAD)
            self.assertEqual(json.loads(output.getvalue())["status"], "done")


if __name__ == "__main__":
    unittest.main()
