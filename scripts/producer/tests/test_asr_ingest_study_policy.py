"""Spending guards on ingest/resume/study paths; workers are no-network stubs."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "producer"))

import asr_policy as policy
import ingest
import resume_ingest_transcription as resume
from study import deep_wordlock, study_transcribe

PAYLOAD = {"status": "done", "duration": 1, "transcript": [{"words": [
    {"word": "TEST", "start": 0.1, "end": 0.5}]}]}


class IngestPolicyTests(unittest.TestCase):
    def test_default_ingest_enables_local_without_discovering_keys(self) -> None:
        admission = types.SimpleNamespace(binding={}, media_by_original={})
        with mock.patch.dict(os.environ, {"DEEPGRAM_API_KEY": "TEST-only"}, clear=True), \
                mock.patch.object(ingest, "load_deepgram_key", side_effect=AssertionError("NO KEY DISCOVERY")) as keys, \
                mock.patch.object(ingest, "classify_inputs", return_value=ingest.Inputs([], None, None)), \
                mock.patch.object(ingest, "collect_ingest_candidates", return_value=[]), \
                mock.patch.object(ingest, "admit_ingest_candidates", return_value=admission), \
                mock.patch.object(ingest, "verify_source_set_binding"), \
                mock.patch.object(ingest, "build_admitted_sources", return_value=([], [])) as sources, \
                mock.patch.object(ingest, "catalog_admitted_broll", return_value=[]), \
                mock.patch.object(ingest, "scan_admitted_music", return_value=[]), \
                mock.patch.object(ingest, "scan_builtin_music", return_value=[]), \
                contextlib.redirect_stdout(io.StringIO()):
            ingest.build_manifest(Path("/TEST/source"), Path("/TEST/manifest"), False)
            context = sources.call_args.args[1].transcribe_context
            self.assertTrue(context.enabled)
            self.assertIsNone(context.key)
            keys.assert_not_called()

    def test_ambient_deepgram_blocks_before_admission_or_key_lookup(self) -> None:
        with mock.patch.dict(os.environ, {policy.PROVIDER_ENV: "deepgram", "DEEPGRAM_API_KEY": "TEST-only"}, clear=True), \
                mock.patch.object(ingest, "load_deepgram_key") as keys, \
                mock.patch.object(ingest, "classify_inputs") as scan:
            with self.assertRaises(RuntimeError):
                ingest.build_manifest(Path("/TEST/source"), Path("/TEST/manifest"), False)
            with self.assertRaises(RuntimeError):
                resume._context(Path("/TEST/manifest"), {"sources": []})
            keys.assert_not_called()
            scan.assert_not_called()

    def test_key_helper_itself_is_guarded_before_any_credential_read(self) -> None:
        with mock.patch.object(os.environ, "get", side_effect=AssertionError("NO CREDENTIAL READ")):
            with self.assertRaises(policy.AsrPolicyError):
                ingest.load_deepgram_key(Path("/TEST/root"))

    def test_resume_default_is_local_and_worker_arguments_are_explicit(self) -> None:
        proc = types.SimpleNamespace(returncode=0, stdout=json.dumps(PAYLOAD), stderr="")
        with mock.patch.dict(os.environ, {"DEEPGRAM_API_KEY": "TEST-only"}, clear=True), \
                mock.patch.object(resume, "load_deepgram_key", side_effect=AssertionError("NO KEY DISCOVERY")), \
                mock.patch.object(ingest, "run_text", return_value=proc) as spawn:
            context = resume._context(Path("/TEST/root"), {"sources": []})
            self.assertTrue(context.enabled)
            self.assertIsNone(context.key)
            ingest._run_transcribe(Path("/TEST/source"), {}, "/TEST/python")
            command = spawn.call_args.args[0].command
            index = command.index("--provider")
            self.assertEqual(command[index:index + 2], ("--provider", "local-whisper"))
            self.assertIn("--local-asr-owned-worker", command)

    def test_explicit_paid_capability_propagates_as_cli_args_not_environment_consent(self) -> None:
        proc = types.SimpleNamespace(returncode=0, stdout=json.dumps(PAYLOAD), stderr="")
        with mock.patch.object(ingest.subprocess, "run", return_value=proc) as spawn, \
                policy.use_asr_invocation(policy.AsrInvocation("deepgram", "deepgram")):
            ingest._run_transcribe(Path("/TEST/source"), {}, "/TEST/python")
            self.assertEqual(spawn.call_args.args[0][-4:], ["--provider", "deepgram", "--authorize-paid-asr", "deepgram"])

    def test_failed_worker_cannot_publish_even_a_prior_done_payload(self) -> None:
        proc = types.SimpleNamespace(returncode=1, stdout=json.dumps(PAYLOAD), stderr="TEST local failure")
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(ingest, "run_text", return_value=proc):
            with self.assertRaisesRegex(RuntimeError, "exit 1"):
                ingest._run_transcribe(Path("/TEST/source"), {}, "/TEST/python")


class StudyPolicyTests(unittest.TestCase):
    def test_study_transcribes_locally_without_a_key(self) -> None:
        proc = types.SimpleNamespace(returncode=0, stdout=json.dumps(PAYLOAD), stderr="")
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(study_transcribe, "run_text", return_value=proc) as spawn:
            result = study_transcribe.transcribe_profile("/TEST/media")
            self.assertEqual(result["wordCount"], 1)
            request = spawn.call_args.args[0]
            self.assertEqual(request.command[3:5], ("--provider", "local-whisper"))
            self.assertNotIn("DEEPGRAM_API_KEY", request.environment)

    def test_study_paid_env_and_bad_provider_never_spawn(self) -> None:
        for provider in ["deepgram", "automatic", ""]:
            with self.subTest(provider=provider), mock.patch.dict(os.environ, {policy.PROVIDER_ENV: provider}, clear=True), \
                    mock.patch.object(study_transcribe, "run_text") as spawn, \
                    mock.patch.object(study_transcribe.subprocess, "run") as paid:
                self.assertIn("skipped", study_transcribe.transcribe_profile("/TEST/media"))
                spawn.assert_not_called()
                paid.assert_not_called()

    def test_wordlock_local_failure_keeps_explicit_unavailable_and_no_cache(self) -> None:
        proc = types.SimpleNamespace(returncode=1, stdout=json.dumps(PAYLOAD), stderr="TEST missing whisper runtime")
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(study_transcribe, "run_text", return_value=proc) as spawn:
            root = Path(temporary)
            words, metadata = deep_wordlock.load_words(str(root / "reference.mp4"), str(root), None)
            self.assertEqual(words, [])
            self.assertIn("failed", metadata["skipped"])
            self.assertFalse((root / "transcript.json").exists())
            spawn.assert_called_once()
            self.assertEqual(spawn.call_args.args[0].command[3:5], ("--provider", "local-whisper"))

    def test_study_never_accepts_an_error_after_done_or_tries_paid_on_timeout(self) -> None:
        self.assertIsNone(study_transcribe._parse_done_line(json.dumps(PAYLOAD) + '\n{"error":"TEST failure"}'))
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(study_transcribe, "run_text", side_effect=TimeoutError("TEST unavailable")) as spawn:
            result = study_transcribe.transcribe_profile("/TEST/media")
            self.assertIn("skipped", result)
            spawn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
