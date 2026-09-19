"""Items 6-7 at fixture level: the maintenance lock in every wrapper, and a truthful uninstall.

The real shipped scripts run in a fixture package; a lock holder is the same helper the
wrappers use (scripts/infra/sniper_lock.py hold), standing in for a ./sniper command, a
render or a second installer. Sniper installs no Codex or Claude and signs nobody out:
the buyer's own logins and settings (checked by digest) are never touched. release/tests/lifecycle_integration.sh
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

MADE_BY_INSTALLER = ("node_modules/next/index.js", "templates/motion/node_modules/h/x.js",
                     # Never overwrite .venv/bin/python3: the scripts run it, and placeholder text
                     # there is an executable shell script that runs whatever its words name.
                     ".venv/lib/python3.14/site-packages/marker.py", "runtime/whisper/model.bin",
                     "runtime/state/receipts/npm-app",
                     "runtime/deepgram.env",
                     "templates/motion/.sniper-native-runtime/abc/hyperframes/dist/cli.js",
                     "templates/motion/.sniper-native-runtime/abc/frame-cache/f.bin")
KEPT = ("runtime/sniper.local.env",
        "templates/motion/.sniper-native-runtime/native-export-history/p/1.json")


def _content(rel: str) -> str:
    """Recognisable file content; the buyer's settings file must also be valid shell."""
    if rel.endswith("sniper.local.env"):
        return f"# my own settings\nMY_NOTE='{rel}'\n"
    if rel.endswith("deepgram.env"):   # a data file the loader reads literally
        return "# sniper-settings-v1 — written by install/setup.command\nDEEPGRAM_API_KEY=\n"
    return rel


def _digest(folder: Path) -> str:
    """One hash over every file name and content under a folder (global-state check).

    Sniper's own tools folder (~/.project-sniper) is not the owner's state: uninstall removes
    it on purpose, and the uninstall tests assert that separately.
    """
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if path.is_file() and ".project-sniper" not in path.relative_to(folder).parts[:1]:
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
        self.assertEqual(fx.write_settings(self.pkg, str(self.base / "videos")).returncode, 0)
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
        proc = subprocess.Popen([sys.executable, str(self.pkg / "scripts/infra/sniper_lock.py"), "hold",
                                 "--state-dir", str(self.pkg / "runtime/state"), "--mode", mode, "--label", label],
                                stdout=subprocess.PIPE, text=True)
        self.holders.append(proc)
        self.assertTrue(proc.stdout.readline().startswith("held"))
        return proc

    # ---------------------------------------------------------------- uninstall
    def test_uninstall_removes_and_keeps_user_data(self) -> None:
        done = self._run("uninstall.command", "--yes")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("login", done.stdout.lower().replace("their logins", ""))
        for rel in MADE_BY_INSTALLER:
            self.assertFalse((self.pkg / rel).exists(), rel)
        for rel in KEPT:
            self.assertEqual((self.pkg / rel).read_text(), _content(rel), rel)
        self.assertTrue((self.base / "videos").is_dir(), "the video workspace was touched")
        self.assertFalse(fx.runtime_prefix(Path(self.env["HOME"])).exists(), "Sniper's own tools were left behind")
        self.assertIn("Removed Sniper's own tools", done.stdout)

    def test_a_reinstall_uses_the_same_projects_folder(self) -> None:
        """A chosen workspace survives uninstall: the reinstall's settings name it again."""
        done = self._run("uninstall.command", "--yes")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse((self.pkg / "runtime/sniper.env").exists())
        self.assertIn("runtime/workspace.env", done.stdout)
        # What setup's write_settings starts from when no --workspace is given:
        kept = fx.bash(self.pkg, 'printf %s "$(kept_workspace)"')
        self.assertEqual(kept.stdout, str(self.base / "videos"), kept.stderr)

    def test_projects_inside_the_sniper_folder_are_kept(self) -> None:
        inside = self.pkg / "projects"
        self.assertEqual(fx.write_settings(self.pkg, str(inside)).returncode, 0)
        (inside / "demo/producer").mkdir(parents=True)
        (inside / "demo/producer/final.mp4").write_text("my edit")
        done = self._run("uninstall.command", "--yes")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((inside / "demo/producer/final.mp4").read_text(), "my edit")
        self.assertIn(str(inside), done.stdout)
        self.assertIn("including your projects if they are in projects/", done.stdout)

    def test_uninstall_keeps_tools_another_install_uses(self) -> None:
        other = fx.make_package(self.base, "other")   # same HOME: both use one tools folder
        self.assertEqual(fx.write_settings(other, str(self.base / "videos")).returncode, 0)
        for pkg in (self.pkg, other):
            self.assertEqual(fx.bash(pkg, "deps_paths && deps_register", self.env).returncode, 0)
        done = self._run("uninstall.command", "--yes")
        self.assertEqual(done.returncode, 0, done.stderr)
        prefix = fx.runtime_prefix(Path(self.env["HOME"]))
        self.assertTrue((prefix / "bin/ffmpeg").exists(), "tools another install uses were removed")
        self.assertIn("another Sniper install uses them", done.stdout)
        self.assertEqual([p.read_text() for p in (prefix / ".sniper-users").iterdir()], [str(other.resolve())])

    # ---------------------------------------------------------------- mutual exclusion
    def test_every_maintenance_command_refuses_while_the_install_is_in_use(self) -> None:
        self._hold("shared", "sniper python3")
        for script, args in (("uninstall.command", ("--yes",)), ("clean-caches.command", ("--yes",)),
                             ("install.command", ())):
            with self.subTest(script):
                done = self._run(script, *args)
                self.assertEqual(done.returncode, 75, done.stderr)
                self.assertIn("In use by: sniper python3", done.stderr)
        self.assertTrue((self.pkg / "node_modules/next/index.js").exists())
        self.assertTrue((self.pkg / "templates/motion/.sniper-native-runtime/abc/frame-cache/f.bin").exists())

    def test_a_second_installer_and_the_doctor_refuse_while_an_installer_runs(self) -> None:
        self._hold("exclusive", "installer")
        self._mark_installed()
        for script in ("install.command", "doctor.command"):
            with self.subTest(script):
                done = self._run(script)
                self.assertEqual(done.returncode, 75, done.stderr)
                self.assertIn("In use by: installer", done.stderr)
        done = subprocess.run([str(self.pkg / "sniper"), "/usr/bin/true"], capture_output=True, text=True,
                              timeout=60, env=self.env, check=False, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 75, done.stderr)
        self.assertIn("In use by: installer", done.stderr)

    def _mark_installed(self) -> None:
        receipt = self.pkg / "runtime/state/receipts/installed"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(str(self.pkg.resolve()))

    def test_lock_left_by_a_killed_holder_does_not_block(self) -> None:
        holder = self._hold("exclusive", "installer")
        holder.send_signal(signal.SIGKILL)
        holder.wait()
        done = self._run("install.command", "--no-such-option")
        self.assertNotIn("In use by", done.stderr)
        self.assertIn("Unknown option: --no-such-option", done.stderr, "it did not get past the lock")


if __name__ == "__main__":
    unittest.main()
