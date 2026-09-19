"""./sniper: the one command a buyer's own Codex or Claude Code runs Sniper's tools through.

It runs the shipped `sniper` file in a fixture package (the package folder is the app
folder) with Sniper's settings written by the installer's own functions.

Run: .venv/bin/python -m unittest release.tests.test_sniper_command
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from release.tests import _fixture as fx


class SniperCommand(unittest.TestCase):
    """Refuses before setup; after it, runs a command with Sniper's tools under the shared lock."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-cmd-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.pkg = fx.make_package(self.base)
        self.env = fx.base_env(self.pkg)
        self.workspace = self.pkg / "projects"

    def _sniper(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(self.pkg / "sniper"), *args], capture_output=True, text=True, timeout=60,
                              env=self.env, check=False, stdin=subprocess.DEVNULL)

    def _install(self) -> None:
        self.assertEqual(fx.write_settings(self.pkg, str(self.workspace)).returncode, 0)
        receipt = self.pkg / "runtime/state/receipts/installed"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(str(self.pkg.resolve()))

    def test_before_setup_it_refuses_and_names_the_fix(self) -> None:
        done = self._sniper("/usr/bin/true")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("Run: ./sniper setup", done.stderr)

    def test_workspace_prints_the_project_folder(self) -> None:
        self._install()
        done = self._sniper("workspace")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), str(self.workspace))

    def test_a_command_runs_here_with_sniper_tools_under_the_shared_lock(self) -> None:
        self._install()
        probe = 'printf "%s|%s|%s|%s" "$SNIPER_LOCK_MODE" "$(command -v ffmpeg)" "$PWD" "${ANTHROPIC_API_KEY:-none}"'
        done = subprocess.run([str(self.pkg / "sniper"), "/bin/sh", "-c", probe], capture_output=True, text=True,
                              timeout=60, env={**self.env, "ANTHROPIC_API_KEY": "sk-not-for-sniper"},
                              check=False, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 0, done.stderr)
        lock, ffmpeg, cwd, key = done.stdout.split("|")
        pkg = self.pkg.resolve()
        self.assertEqual(lock, "shared")
        self.assertEqual(ffmpeg, f"{pkg}/runtime/bin/ffmpeg")
        self.assertEqual(cwd, str(pkg))
        self.assertEqual(key, "none", "a key from the caller's shell never reaches Sniper's tools")

    def test_setup_and_doctor_hand_over_to_the_installer_scripts(self) -> None:
        text = (self.pkg / "sniper").read_text()
        self.assertIn('setup) shift; exec "$here/install/install.command"', text)
        self.assertIn('doctor) shift; exec "$here/install/doctor.command"', text)
        for word in ("codex", "claude "):
            self.assertNotIn(f'"{word}', text.lower(), "./sniper never starts a provider")


if __name__ == "__main__":
    unittest.main()
