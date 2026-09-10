"""No-network ASR admission tests; all credentials, SDKs and ASR are TEST stubs."""
from __future__ import annotations

import argparse
import asyncio
import builtins
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "clipper"))

import asr_policy as policy
import clipper_transcribe as clipper
import local_whisper
import transcribe


class AsrAdmissionTests(unittest.TestCase):
    def test_ambient_keys_execution_modes_and_fake_authorization_do_not_spend(self) -> None:
        environments = [{}, {"DEEPGRAM_API_KEY": "TEST-only"},
            {"SNIPER_EXECUTION_MODE": "cloud", "SNIPER_AUTHORIZE_PAID_ASR": "deepgram"}]
        for env in environments:
            with self.subTest(env=sorted(env)):
                self.assertEqual(policy.transcription_provider(env), policy.LOCAL_PROVIDER)
        for value in ["deepgram", "automatic", "", " Deepgram", "local", None, 1]:
            with self.subTest(provider=value), self.assertRaises(policy.AsrPolicyError):
                policy.transcription_provider({policy.PROVIDER_ENV: value})

    def test_manual_paid_authority_requires_both_exact_options_and_ends_with_scope(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            for provider, consent in [("deepgram", None), (None, "deepgram"),
                    ("local-whisper", "deepgram"), ("deepgram", "yes"),
                    ("", None), ([], None), (True, None)]:
                with self.subTest(provider=provider, consent=consent), self.assertRaises(policy.AsrPolicyError):
                    policy.invocation_from_options(argparse.Namespace(provider=provider, authorize_paid_asr=consent))
            options = argparse.Namespace(provider="deepgram", authorize_paid_asr="deepgram")
            with policy.use_asr_invocation(policy.invocation_from_options(options)):
                policy.require_paid_asr()
                self.assertEqual(policy.child_asr_arguments(), ["--provider", "deepgram", "--authorize-paid-asr", "deepgram"])
            with self.assertRaises(policy.AsrPolicyError):
                policy.require_paid_asr()
            self.assertEqual(policy.transcription_provider(), "local-whisper")

    def test_denied_client_does_not_import_sdk_or_read_api_key(self) -> None:
        with mock.patch.object(builtins, "__import__", side_effect=AssertionError("no import")), \
                mock.patch.dict(os.environ, {"DEEPGRAM_API_KEY": "TEST-only"}):
            with self.assertRaises(policy.AsrPolicyError):
                policy.paid_deepgram_client()

    def test_explicit_manual_paid_client_is_only_a_fake_sdk_in_this_test(self) -> None:
        sdk = types.ModuleType("deepgram")
        sdk.AsyncDeepgramClient = mock.Mock(return_value="TEST-SDK-STUB")
        with mock.patch.dict(sys.modules, {"deepgram": sdk}), \
                mock.patch.dict(os.environ, {"DEEPGRAM_API_KEY": "TEST-not-a-key"}), \
                policy.use_asr_invocation(policy.AsrInvocation("deepgram", "deepgram")):
            self.assertEqual(policy.paid_deepgram_client(), "TEST-SDK-STUB")
        sdk.AsyncDeepgramClient.assert_called_once_with(api_key="TEST-not-a-key")

    def test_direct_paid_helpers_reject_even_caller_supplied_fake_client(self) -> None:
        calls = [(transcribe.run_transcription, ("/TEST/no-media",)),
                 (clipper.run_transcription, ("/TEST/no-media",)),
                 (clipper._transcribe_channel_deepgram, (mock.Mock(), "/TEST/no-media", 0))]
        with mock.patch.dict(os.environ, {"DEEPGRAM_API_KEY": "TEST-only"}), \
                mock.patch("socket.create_connection", side_effect=AssertionError("NO NETWORK")):
            for function, args in calls:
                with self.subTest(function=function.__qualname__), self.assertRaises(policy.AsrPolicyError):
                    asyncio.run(function(*args))

    def test_local_child_strips_paid_key_and_never_forwards_environment_consent(self) -> None:
        env = {"DEEPGRAM_API_KEY": "TEST-only", policy.PROVIDER_ENV: "deepgram"}
        with policy.use_asr_invocation(policy.AsrInvocation("local-whisper")):
            child = policy.transcription_environment(env)
            self.assertNotIn("DEEPGRAM_API_KEY", child)
            self.assertEqual(child[policy.PROVIDER_ENV], "local-whisper")


class WorkerFailureTests(unittest.TestCase):
    def _run_local_failure(self, error: Exception) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav") as media, \
                mock.patch.dict(os.environ, {"DEEPGRAM_API_KEY": "TEST-only"}, clear=True), \
                mock.patch.object(sys, "argv", ["transcribe.py", media.name]), \
                mock.patch.object(transcribe, "probe_transcribe_input", return_value=types.SimpleNamespace(is_video=False, is_audio=True)), \
                mock.patch.object(transcribe, "transcribe_media", side_effect=error) as local, \
                mock.patch.object(transcribe, "paid_deepgram_client", side_effect=AssertionError("NO PAID SDK")) as paid, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                asyncio.run(policy.run_asr_cli(transcribe.main))
            local.assert_called_once()
            paid.assert_not_called()

    def test_missing_local_runtime_and_local_errors_never_fallback(self) -> None:
        for error in [local_whisper.LocalWhisperError("whisper-cli not found"),
                      local_whisper.LocalWhisperError("timing quality failed"),
                      OSError("local tool failed"), ValueError("invalid local words")]:
            with self.subTest(error=str(error)):
                self._run_local_failure(error)

    def test_environment_paid_request_and_cli_provider_alone_never_enter_workers(self) -> None:
        cases = [([], {policy.PROVIDER_ENV: "deepgram"}), (["--provider", "deepgram"], {}),
                 (["--authorize-paid-asr", "deepgram"], {})]
        for flags, env in cases:
            with self.subTest(flags=flags), mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(sys, "argv", ["transcribe.py", "/TEST/no-media", *flags]), \
                    mock.patch.object(transcribe, "main", new_callable=mock.AsyncMock) as worker:
                with self.assertRaises(policy.AsrPolicyError):
                    asyncio.run(policy.run_asr_cli(worker))
                worker.assert_not_called()

    def test_explicit_paid_cli_propagates_only_for_that_invocation_without_sdk(self) -> None:
        observed = []
        async def worker() -> None:
            observed.append((list(sys.argv), policy.transcription_provider()))
            policy.require_paid_asr()
        argv = ["transcribe.py", "/TEST/no-media", "--provider", "deepgram", "--authorize-paid-asr", "deepgram"]
        with mock.patch.object(sys, "argv", argv), mock.patch.dict(os.environ, {}, clear=True):
            asyncio.run(policy.run_asr_cli(worker))
            self.assertIs(sys.argv, argv)
        self.assertEqual(observed, [(["transcribe.py", "/TEST/no-media"], "deepgram")])
        with self.assertRaises(policy.AsrPolicyError):
            policy.require_paid_asr()

    def test_clipper_local_channel_error_never_uses_supplied_paid_client(self) -> None:
        with mock.patch.dict(os.environ, {"DEEPGRAM_API_KEY": "TEST-only"}, clear=True), \
                mock.patch.object(clipper, "transcribe_media", side_effect=local_whisper.LocalWhisperError("runtime missing")), \
                mock.patch.object(clipper, "_transcribe_channel_deepgram", new_callable=mock.AsyncMock) as paid:
            with self.assertRaises(local_whisper.LocalWhisperError):
                asyncio.run(clipper.transcribe_channel(mock.Mock(), "/TEST/no-media", 0))
            paid.assert_not_called()


_CLI_SMOKE = """
import importlib.abc, runpy, socket, subprocess, sys
class NoPaidSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'deepgram':
            raise AssertionError('NO PAID SDK IMPORT')
def denied(*args, **kwargs):
    raise AssertionError('NO NETWORK OR MEDIA CHILD')
sys.meta_path.insert(0, NoPaidSdk())
socket.socket.connect = denied
socket.create_connection = denied
subprocess.Popen = denied
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""


class ActualWorkerCliSmokeTests(unittest.TestCase):
    def test_actual_entrypoints_fail_before_any_sdk_model_media_or_network(self) -> None:
        cases = [([], {}, "File not found"),
                 (["--provider", "local-whisper"], {policy.PROVIDER_ENV: "deepgram"}, "File not found"),
                 ([], {policy.PROVIDER_ENV: "deepgram"}, "Paid ASR is not authorized"),
                 (["--provider", "deepgram"], {}, "Paid ASR is not authorized"),
                 (["--provider", "invalid"], {}, "invalid choice")]
        workers = [SCRIPTS / "transcribe.py", SCRIPTS / "clipper" / "clipper_transcribe.py"]
        for worker, case in [(worker, case) for worker in workers for case in cases]:
            flags, environment, expected = case
            with self.subTest(worker=worker.name, flags=flags, environment=environment):
                self._assert_cli_denied(worker, (flags, environment, expected))

    def _assert_cli_denied(self, worker: Path, case: tuple) -> None:
        flags, environment, expected = case
        env = {"PATH": os.defpath, "PYTHONPATH": str(SCRIPTS), "PYTHONDONTWRITEBYTECODE": "1",
               "DEEPGRAM_API_KEY": "TEST-not-a-key", "SNIPER_DEBUG": "0", **environment}
        result = subprocess.run(
            [sys.executable, "-B", "-c", _CLI_SMOKE, str(worker), "/TEST/no-media", *flags],
            capture_output=True, text=True, timeout=10, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(expected, result.stdout + result.stderr)
        self.assertNotIn("NO PAID SDK IMPORT", result.stdout + result.stderr)
        self.assertNotIn("NO NETWORK OR MEDIA CHILD", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
