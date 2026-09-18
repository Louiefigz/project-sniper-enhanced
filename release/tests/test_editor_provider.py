"""F1: the editor window, the app settings and every edit agree on provider, brain and model.

Runs the shipped install/editor.command against stub CLIs that record their argv and
the environment they were given (never a real provider).

Run: .venv/bin/python -m unittest release.tests.test_editor_provider
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from release.tests import _fixture as fx


class EditorProvider(unittest.TestCase):
    """Each test installs settings with the installer's own writer, then opens the editor."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-editor-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.pkg = fx.make_package(self.base)
        self.logs = Path(fx.base_env(self.pkg)["STUB_LOG_DIR"])

    def _install(self, provider: str) -> None:
        done = fx.write_settings(self.pkg, provider, str(self.base / "videos"))
        self.assertEqual(done.returncode, 0, done.stderr)

    def _editor(self, *args: str) -> subprocess.CompletedProcess:
        for calls in self.logs.glob("*.calls"):
            calls.unlink()
        return subprocess.run(["/bin/bash", str(self.pkg / "install/editor.command"), *args],
                              capture_output=True, text=True, timeout=60, env=fx.base_env(self.pkg), check=False)

    def _calls(self, cli: str) -> str:
        path = self.logs / f"{cli}.calls"
        return path.read_text() if path.exists() else ""

    def test_default_codex_install_opens_codex_with_the_app_settings(self) -> None:
        self._install("codex")
        done = self._editor()
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self._calls("codex")
        self.assertIn("[--model=gpt-5.6-sol]", calls)
        self.assertIn('[model_reasoning_effort="xhigh"]', calls)
        self.assertIn('[forced_login_method="chatgpt"]', calls)
        self.assertIn("SNIPER_PROVIDER=codex SNIPER_BRAIN_PROVIDER=codex", calls)
        self.assertIn("LOCK=shared", calls)
        self.assertEqual(self._calls("claude"), "")

    def test_explicit_claude_on_a_codex_install_is_refused_not_half_obeyed(self) -> None:
        self._install("codex")
        done = self._editor("claude")
        self.assertEqual(done.returncode, 1)
        self.assertIn("install/use-provider.command claude", done.stderr)
        self.assertEqual(self._calls("claude") + self._calls("codex"), "", "a CLI ran despite the mismatch")

    def test_explicit_codex_on_a_claude_install_is_refused(self) -> None:
        self._install("claude")
        done = self._editor("codex")
        self.assertEqual(done.returncode, 1)
        self.assertIn("install/use-provider.command codex", done.stderr)
        self.assertEqual(self._calls("claude") + self._calls("codex"), "")

    def test_naming_the_installed_provider_is_accepted(self) -> None:
        self._install("claude")
        self.assertEqual(self._editor("claude").returncode, 0)
        self.assertIn("SNIPER_PROVIDER=claude SNIPER_BRAIN_PROVIDER=legacy", self._calls("claude"))

    def test_persisted_switch_moves_editor_and_app_together(self) -> None:
        self._install("codex")
        self._install("claude")  # what use-provider.command claude runs (the installer's configuration step)
        done = self._editor()
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self._calls("claude")
        self.assertIn("[--model=opus]", calls)
        self.assertIn('[--settings] [{"forceLoginMethod":"claudeai"}]', calls)
        self.assertIn("SNIPER_PROVIDER=claude SNIPER_BRAIN_PROVIDER=legacy SNIPER_CLAUDE_MODEL=opus", calls)
        env = (self.pkg / "runtime/sniper.env").read_text()
        self.assertIn("SNIPER_PROVIDER=claude\n", env)
        self.assertIn("SNIPER_BRAIN_PROVIDER=legacy\n", env)

    def test_a_model_override_reaches_the_editor_and_the_app_alike(self) -> None:
        self._install("codex")
        (self.pkg / "runtime/sniper.local.env").write_text("SNIPER_CODEX_MODEL=gpt-6-astra\n")
        self.assertEqual(self._editor().returncode, 0)
        calls = self._calls("codex")
        self.assertIn("[--model=gpt-6-astra]", calls)
        self.assertIn("SNIPER_CODEX_MODEL=gpt-6-astra", calls)

    def test_a_provider_set_in_the_local_file_is_refused_everywhere(self) -> None:
        self._install("codex")
        (self.pkg / "runtime/sniper.local.env").write_text("SNIPER_BRAIN_PROVIDER=legacy\n")
        done = self._editor()
        self.assertEqual(done.returncode, 1)
        self.assertIn("use-provider.command", done.stderr)
        self.assertEqual(self._calls("codex") + self._calls("claude"), "")

    def test_an_unsafe_model_value_is_refused_before_reaching_a_cli(self) -> None:
        self._install("claude")
        (self.pkg / "runtime/sniper.local.env").write_text("SNIPER_CLAUDE_MODEL='--dangerously-skip-permissions'\n")
        done = self._editor()
        self.assertEqual(done.returncode, 1)
        self.assertIn("SNIPER_CLAUDE_MODEL", done.stderr)
        self.assertEqual(self._calls("claude"), "")


if __name__ == "__main__":
    unittest.main()
