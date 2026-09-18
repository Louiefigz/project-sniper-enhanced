"""Items 6-7 at fixture level: the maintenance lock in every wrapper, and a truthful uninstall.

The real shipped scripts run in a fixture package with stub CLIs; a lock holder is the
same helper the wrappers use (scripts/infra/sniper_lock.py hold), standing in for an
editor window, a render or a second installer. release/tests/lifecycle_integration.sh
repeats the important cases on a real installed package.

Run: .venv/bin/python -m unittest release.tests.test_lifecycle_fixture
"""
from __future__ import annotations

import hashlib
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from release.tests import _fixture as fx

MADE_BY_INSTALLER = ("app/node_modules/next/index.js", "app/templates/motion/node_modules/h/x.js",
                     "app/.venv/bin/python3", "app/.next/BUILD_ID", "runtime/whisper/model.bin",
                     "runtime/state/receipts/build", "runtime/codex-home/auth.json",
                     "app/templates/motion/.sniper-native-runtime/abc/hyperframes/dist/cli.js",
                     "app/templates/motion/.sniper-native-runtime/abc/frame-cache/f.bin")
KEPT = ("runtime/sniper.local.env", "app/.env.local",
        "app/templates/motion/.sniper-native-runtime/native-export-history/p/1.json")


def _content(rel: str) -> str:
    """Recognisable file content; the buyer's settings file must also be valid shell."""
    return f"# my own settings\nMY_NOTE='{rel}'\n" if rel.endswith("sniper.local.env") else rel


def _digest(folder: Path) -> str:
    """One hash over every file name and content under a folder (global-state check)."""
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(folder)).encode() + path.read_bytes())
    return digest.hexdigest()


class Lifecycle(unittest.TestCase):
    """A configured fixture install with files where the installer would put them."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-life-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.pkg = fx.make_package(self.base)
        self.env = fx.base_env(self.pkg)
        self.logs = Path(self.env["STUB_LOG_DIR"])
        self.assertEqual(fx.write_settings(self.pkg, "codex", str(self.base / "videos")).returncode, 0)
        for rel in MADE_BY_INSTALLER + KEPT:
            (self.pkg / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.pkg / rel).write_text(_content(rel))
        home = Path(self.env["HOME"])
        for rel in (".codex/auth.json", ".claude/settings.json", ".claude.json"):
            (home / rel).parent.mkdir(parents=True, exist_ok=True)
            (home / rel).write_text("owner's own " + rel)
        self.home_before = _digest(home)
        self.holders: list[subprocess.Popen] = []

    def tearDown(self) -> None:
        for proc in self.holders:
            proc.kill()
            proc.wait()
            proc.stdout.close()
        self.assertEqual(_digest(Path(self.env["HOME"])), self.home_before, "global Codex/Claude state changed")

    def _run(self, script: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["/bin/bash", str(self.pkg / "install" / script), *args], capture_output=True,
                              text=True, timeout=120, env=self.env, check=False, stdin=subprocess.DEVNULL)

    def _hold(self, mode: str, label: str) -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, str(self.pkg / "app/scripts/infra/sniper_lock.py"), "hold",
                                 "--state-dir", str(self.pkg / "runtime/state"), "--mode", mode, "--label", label],
                                stdout=subprocess.PIPE, text=True)
        self.holders.append(proc)
        self.assertTrue(proc.stdout.readline().startswith("held"))
        return proc

    def _sign_in(self, *clis: str) -> None:
        for cli in clis:
            (self.logs / f"{cli}.signed-in").write_text("yes")

    # ---------------------------------------------------------------- uninstall
    def test_uninstall_signs_out_removes_and_keeps_user_data(self) -> None:
        self._sign_in("codex", "claude")
        done = self._run("uninstall.command", "--yes")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Sniper's codex login: signed out.", done.stdout)
        self.assertIn("Sniper's claude login: signed out.", done.stdout)
        for rel in MADE_BY_INSTALLER:
            self.assertFalse((self.pkg / rel).exists(), rel)
        for rel in KEPT:
            self.assertEqual((self.pkg / rel).read_text(), _content(rel), rel)
        self.assertTrue((self.base / "videos").is_dir(), "the video workspace was touched")
        claude = (self.logs / "claude.calls").read_text()
        self.assertIn("[--setting-sources] [] [auth] [status] [--json]", claude)
        self.assertIn("[--setting-sources] [] [auth] [logout]", claude)
        self.assertNotIn(f"cwd={self.env['HOME']}", claude, "your home settings folder must not be the working folder")

    def test_claude_sign_in_reads_no_setting_sources_from_your_home(self) -> None:
        # Sign-in ends with the doctor's provider check; this test is about the login call only.
        doctor = self.pkg / "install/doctor.command"
        doctor.write_text("#!/bin/bash\nexit 0\n")
        doctor.chmod(0o755)
        done = self._run("sign-in.command", "claude")
        self.assertEqual(done.returncode, 0, done.stderr)
        claude = (self.logs / "claude.calls").read_text()
        self.assertIn('[--setting-sources] [] [--settings] [{"forceLoginMethod":"claudeai"}] [auth] [login]', claude)
        self.assertIn(f"cwd={(self.pkg / 'runtime').resolve()}", claude)

    def test_failed_sign_out_is_reported_and_nothing_is_removed(self) -> None:
        self._sign_in("codex", "claude")
        (self.logs / "claude.logout-fails").write_text("yes")
        done = self._run("uninstall.command", "--yes")
        self.assertEqual(done.returncode, 1)
        self.assertIn("Signing out of Sniper's claude login failed", done.stderr)
        self.assertIn("could not reach the sign-out service", done.stderr)
        self.assertNotIn("Removed.", done.stdout)
        for rel in MADE_BY_INSTALLER + KEPT:
            self.assertTrue((self.pkg / rel).exists(), rel)

    def test_keep_logins_removes_the_rest_and_says_what_stays(self) -> None:
        self._sign_in("claude")
        (self.logs / "claude.logout-fails").write_text("yes")
        done = self._run("uninstall.command", "--yes", "--keep-logins")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Claude Code-credentials-", done.stderr)
        self.assertFalse((self.pkg / "app/node_modules").exists())

    def test_failed_stop_is_reported_and_nothing_is_removed(self) -> None:
        (self.pkg / "runtime/state/app.pid").write_text("99999")
        (self.pkg / "install/stop.command").write_text("#!/bin/bash\necho 'The app did not stop within 30 seconds (pid 99999).' >&2\nexit 1\n")
        done = self._run("uninstall.command", "--yes")
        self.assertEqual(done.returncode, 1)
        self.assertIn("Stopping the app failed, so nothing was removed", done.stderr)
        self.assertTrue((self.pkg / "app/node_modules/next/index.js").exists())

    # ---------------------------------------------------------------- mutual exclusion
    def test_every_maintenance_command_refuses_while_the_install_is_in_use(self) -> None:
        self._hold("shared", "editor window (codex)")
        for script, args in (("uninstall.command", ("--yes",)), ("clean-caches.command", ("--yes",)),
                             ("install.command", ("--provider", "codex")), ("use-provider.command", ("claude",))):
            with self.subTest(script):
                done = self._run(script, *args)
                self.assertEqual(done.returncode, 75, done.stderr)
                self.assertIn("In use by: editor window (codex)", done.stderr)
        self.assertTrue((self.pkg / "app/node_modules/next/index.js").exists())
        self.assertTrue((self.pkg / "app/templates/motion/.sniper-native-runtime/abc/frame-cache/f.bin").exists())

    def test_a_second_installer_and_the_doctor_refuse_while_an_installer_runs(self) -> None:
        self._hold("exclusive", "installer")
        for script in ("install.command", "doctor.command", "editor.command", "sign-in.command"):
            with self.subTest(script):
                done = self._run(script)
                self.assertEqual(done.returncode, 75, done.stderr)
                self.assertIn("In use by: installer", done.stderr)
        self.assertEqual((self.logs / "codex.calls").exists(), False, "a CLI ran under the installer")

    def test_lock_left_by_a_killed_holder_does_not_block(self) -> None:
        holder = self._hold("exclusive", "installer")
        holder.send_signal(signal.SIGKILL)
        holder.wait()
        done = self._run("install.command", "--no-such-option")
        self.assertNotIn("In use by", done.stderr)
        self.assertIn("Unknown option: --no-such-option", done.stderr, "it did not get past the lock")


if __name__ == "__main__":
    unittest.main()
