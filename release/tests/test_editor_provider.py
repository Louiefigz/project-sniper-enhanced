"""F1: the editor window, the app settings and every edit agree on provider, brain and model.

Runs the shipped install/editor.command against stub CLIs that record their argv and
the environment they were given (never a real provider).

Run: .venv/bin/python -m unittest release.tests.test_editor_provider
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from release.tests import _fixture as fx


def _settings_json(calls: str) -> dict:
    """The JSON passed after --settings in a recorded stub call."""
    start = calls.index("[--settings] [") + len("[--settings] [")
    return json.JSONDecoder().raw_decode(calls[start:])[0]


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

    def test_codex_window_asks_before_commands_instead_of_nesting_sandboxes(self) -> None:
        # Inside Codex's own sandbox Producer's media check cannot apply its macOS sandbox
        # (codex-route evidence); the window runs unsandboxed but asks before each command.
        self._install("codex")
        done = self._editor()
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self._calls("codex")
        self.assertIn("[--sandbox] [danger-full-access]", calls)
        self.assertIn("[--ask-for-approval] [untrusted]", calls)
        for never in ("[never]", "[on-failure]", "[--dangerously-bypass-approvals-and-sandbox]", "[--full-auto]"):
            self.assertNotIn(never, calls)

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
        self.assertIn("[--setting-sources] [project,local]", calls)
        settings = _settings_json(calls)
        self.assertEqual(settings["forceLoginMethod"], "claudeai")
        base = self.base.resolve()  # the launchers work from the resolved package path
        self.assertIn(str(base / "CLAUDE.md"), settings["claudeMdExcludes"], "folders above the app are excluded")
        self.assertIn(str(base / ".claude/CLAUDE.md"), settings["claudeMdExcludes"])
        self.assertNotIn(str(base / "pkg/app/CLAUDE.md"), settings["claudeMdExcludes"], "the app's own file still loads")
        self.assertIn("SNIPER_PROVIDER=claude SNIPER_BRAIN_PROVIDER=legacy SNIPER_CLAUDE_MODEL=opus", calls)
        env = (self.pkg / "runtime/sniper.env").read_text()
        self.assertIn("SNIPER_PROVIDER=claude\n", env)
        self.assertIn("SNIPER_BRAIN_PROVIDER=legacy\n", env)

    def test_the_editor_never_receives_a_paid_api_key(self) -> None:
        for provider in ("codex", "claude"):
            self._install(provider)
            (self.pkg / "runtime/sniper.local.env").write_text(
                "ANTHROPIC_API_KEY=sk-ant-test-only\nOPENAI_API_KEY=sk-test-only\n")
            self.assertEqual(self._editor().returncode, 0)
            self.assertIn("KEYS anthropic= openai=", self._calls(provider), provider)

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
