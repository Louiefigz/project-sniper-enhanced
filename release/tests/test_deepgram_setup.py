"""Connection validation, privacy, atomic writes, and the actual launcher's read path."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import stat
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from release.tests import _fixture as fx

SPEC = importlib.util.spec_from_file_location("deepgram_setup", fx.INSTALL_SRC / "lib/deepgram_setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)
KEY = "test_key_never_use_for_real_0123456789"


def response(body: bytes = b'{"api_key_id":"fixture"}') -> Mock:
    """An in-memory HTTPS reply, no real account or network."""
    result = Mock(status=200)
    result.read.return_value = body
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


class DeepgramValidation(unittest.TestCase):
    """Only the fixed endpoint sees the key; errors never echo remote text."""

    def test_auth_only_request(self) -> None:
        with patch.object(setup.urllib.request, "build_opener") as factory:
            factory.return_value.open.return_value = response()
            setup.verify_key(KEY)
        request = factory.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, setup.AUTH_URL)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), f"Token {KEY}")
        self.assertIsNone(request.data, "connection checks must not send audio")
        self.assertEqual(factory.return_value.open.call_args.kwargs["timeout"], 10)
        self.assertIsInstance(factory.call_args.args[0], setup.NoRedirect)

    def test_rejected_key_never_echoes_server_body_or_retries(self) -> None:
        for code in (401, 403, 400):
            error = urllib.error.HTTPError(setup.AUTH_URL, code, KEY, {}, io.BytesIO(KEY.encode()))
            with patch.object(setup.urllib.request, "build_opener") as factory:
                factory.return_value.open.side_effect = error
                with self.assertRaises(setup.ConnectionProblem) as caught:
                    setup.verify_key(KEY)
            self.assertNotIn(KEY, str(caught.exception))
            self.assertEqual(factory.return_value.open.call_count, 1)

    def test_offline_retries_are_bounded_and_sanitized(self) -> None:
        with patch.object(setup.urllib.request, "build_opener") as factory, patch.object(setup.time, "sleep") as sleep:
            factory.return_value.open.side_effect = urllib.error.URLError(KEY)
            with self.assertRaises(setup.ConnectionProblem) as caught:
                setup.verify_key(KEY)
        self.assertNotIn(KEY, str(caught.exception))
        self.assertEqual(factory.return_value.open.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_transient_failure_can_recover(self) -> None:
        error = urllib.error.HTTPError(setup.AUTH_URL, 429, "rate limited", {}, io.BytesIO())
        with patch.object(setup.urllib.request, "build_opener") as factory, patch.object(setup.time, "sleep"):
            factory.return_value.open.side_effect = [error, response()]
            setup.verify_key(KEY)
        self.assertEqual(factory.return_value.open.call_count, 2)

    def test_malformed_success_is_not_saved_as_valid(self) -> None:
        for body in (b"not JSON", b"[]", b"{}"):
            with patch.object(setup.urllib.request, "build_opener") as factory:
                factory.return_value.open.return_value = response(body)
                with self.assertRaises(setup.ConnectionProblem):
                    setup.verify_key(KEY)

    def test_redirect_is_refused(self) -> None:
        with self.assertRaises(setup.ConnectionProblem):
            setup.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid")

    def test_malformed_keys_never_reach_network(self) -> None:
        for key in ("", "short", KEY + "\r\nInjected: yes", "$(touch PWNED)", "Token " + KEY):
            with patch.object(setup.urllib.request, "build_opener") as factory:
                with self.assertRaises(setup.ConnectionProblem):
                    setup.verify_key(key)
            factory.assert_not_called()


class DeepgramStorage(unittest.TestCase):
    """The key is private, survives repair, and reaches real launcher environments."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-connection-")
        self.addCleanup(self.temp.cleanup)
        self.pkg = fx.make_package(Path(self.temp.name), "Sniper Budget$97 ü")
        self.path = self.pkg / "runtime/deepgram.env"

    def test_private_atomic_save_replace_and_disconnect(self) -> None:
        setup.save_connection(self.path, KEY)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertTrue(setup.connected(self.path))
        setup.save_connection(self.path, KEY + "new")
        self.assertIn(KEY + "new", self.path.read_text())
        setup.save_connection(self.path, "")
        self.assertFalse(setup.connected(self.path))
        self.assertEqual(list(self.path.parent.glob(".deepgram-*")), [])

    def test_failed_atomic_replace_preserves_previous_key(self) -> None:
        setup.save_connection(self.path, KEY)
        with patch.object(setup.os, "replace", side_effect=OSError("unwritable")):
            with self.assertRaises(OSError):
                setup.save_connection(self.path, KEY + "new")
        self.assertEqual(self.path.read_text(), f"{setup.HEADER}\nDEEPGRAM_API_KEY={KEY}\n")
        self.assertEqual(list(self.path.parent.glob(".deepgram-*")), [])

    def test_connect_validates_before_save_and_does_not_echo(self) -> None:
        output = io.StringIO()
        with patch.object(setup.getpass, "getpass", return_value=KEY), patch.object(setup, "verify_key") as verify:
            with contextlib.redirect_stdout(output):
                setup.connect(self.path)
        verify.assert_called_once_with(KEY)
        self.assertNotIn(KEY, output.getvalue())
        self.assertTrue(setup.connected(self.path))

    def test_invalid_key_and_cancel_preserve_old_key(self) -> None:
        setup.save_connection(self.path, KEY)
        before = self.path.read_bytes()
        with patch.object(setup.getpass, "getpass", return_value=KEY + "bad"):
            with patch.object(setup, "verify_key", side_effect=setup.ConnectionProblem("invalid")):
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(setup.ConnectionProblem):
                    setup.connect(self.path)
        with patch.object(setup.getpass, "getpass", return_value=""):
            with contextlib.redirect_stdout(io.StringIO()):
                setup.connect(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_skip_never_calls_network_or_stores_key(self) -> None:
        with patch("builtins.input", return_value=""), patch.object(setup, "verify_key") as verify:
            with contextlib.redirect_stdout(io.StringIO()):
                setup.configure(self.path)
        verify.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_launcher_reads_key_after_install_repair_and_keeps_local_asr(self) -> None:
        setup.save_connection(self.path, KEY)
        for _ in range(2):
            done = fx.write_settings(self.pkg, "codex", str(self.pkg.parent / "videos"))
            self.assertEqual(done.returncode, 0, done.stderr)
            done = fx.bash(self.pkg, 'load_env; printf "%s|%s" "$DEEPGRAM_API_KEY" "$SNIPER_TRANSCRIBE_PROVIDER"')
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout, KEY + "|local-whisper")

    def test_disconnect_overrides_legacy_manual_key(self) -> None:
        self.assertEqual(fx.write_settings(self.pkg, "codex", str(self.pkg.parent / "videos")).returncode, 0)
        (self.pkg / "runtime/sniper.local.env").write_text(f"DEEPGRAM_API_KEY={KEY}\n")
        setup.save_connection(self.path, "")
        done = fx.bash(self.pkg, 'load_env; printf "key:%s" "$DEEPGRAM_API_KEY"')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "key:")

    def test_support_bundle_omits_saved_credentials(self) -> None:
        setup.save_connection(self.path, KEY)
        spec = importlib.util.spec_from_file_location("sniper_diagnostics", self.pkg / "install/sniper_diagnostics.py")
        diagnostics = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(diagnostics)
        target = self.pkg.parent / "support"
        with patch.object(diagnostics, "_run", return_value="{}"):
            diagnostics.build(target, False)
        self.assertNotIn(KEY, "".join(p.read_text() for p in target.iterdir()))
        self.assertFalse((target / "deepgram.env").exists())


if __name__ == "__main__":
    unittest.main()
