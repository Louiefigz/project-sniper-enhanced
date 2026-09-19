"""Run guided setup in a real terminal with an offline doctor stand-in.

The real connection UI, settings loader and maintenance locks run. Setup never signs in
to or opens Codex or Claude: buyers use their own. No account, API request or paid call
is made by these tests.
"""
from __future__ import annotations

import errno
import os
import pty
import select
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from release.tests import _fixture as fx

DOCTOR = '''#!/bin/bash
echo "doctor $*" >> "$STUB_LOG_DIR/order"
[ "${FAIL_DOCTOR:-0}" = 0 ] || { echo 'FAIL: sample admission'; exit 1; }
echo 'All required checks passed.'
'''
RETIRED = ("editor.command", "sign-in.command", "use-provider.command", "start.command", "stop.command")


def run_terminal(argv: list[str], env: dict[str, str]) -> tuple[int, str]:
    """Answer the real optional-connection prompt and collect its terminal output."""
    master, slave = pty.openpty()
    process = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, env=env)
    os.close(slave)
    output = b""
    deadline = time.monotonic() + 30
    answered = False
    try:
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    break
                if not chunk:
                    break
                output += chunk
            if not answered and b"Choose [2]:" in output:
                os.write(master, b"2\n")
                answered = True
            if process.poll() is not None and not select.select([master], [], [], 0)[0]:
                break
        return process.wait(timeout=3), output.decode(errors="replace")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)


class GuidedSetup(unittest.TestCase):
    """Setup finishes the install, offers Deepgram and checks; failures never claim readiness."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-guided-")
        self.addCleanup(self.temp.cleanup)
        self.pkg = fx.make_package(Path(self.temp.name))
        self.env = fx.base_env(self.pkg)
        self.logs = Path(self.env["STUB_LOG_DIR"])
        # The shared fixture's regular wrapper file around this interpreter (never a link to it).
        self.python = self.pkg / ".venv/bin/python3"
        self.assertTrue(self.python.is_file() and not self.python.is_symlink())
        self.assertEqual(fx.write_settings(self.pkg, str(self.pkg.parent / "videos")).returncode, 0)
        self._mark_installed(self.pkg.resolve())  # a finished installation of this folder
        (self.pkg / "install/doctor.command").write_text(DOCTOR)
        self.command = str(self.pkg / "install/setup.command")

    def _mark_installed(self, root: Path | None) -> None:
        """Write (root) or remove (None) the installer's completion receipt."""
        receipt = self.pkg / "runtime/state/receipts/installed"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        if root is None:
            receipt.unlink(missing_ok=True)
        else:
            receipt.write_text(str(root))

    def _stand_in_installer(self, finishes: bool) -> None:
        """Offline installer stand-in: records the call; writes the receipt only when it finishes."""
        receipt = self.pkg.resolve() / "runtime/state/receipts/installed"
        body = f'printf "%s" "{self.pkg.resolve()}" > "{receipt}"; exit 0' if finishes else "exit 1"
        installer = self.pkg / "install/install.command"
        installer.write_text(f'#!/bin/bash\necho installer >> "$STUB_LOG_DIR/order"\n{body}\n')
        installer.chmod(0o755)

    def _order(self) -> list[str]:
        order = self.logs / "order"
        return order.read_text().splitlines() if order.exists() else []

    def test_interrupted_install_is_resumed_on_every_reopen(self) -> None:
        # Settings exist (step 8 wrote them) but the install stopped at step 9 or 10.
        self._mark_installed(None)
        self._stand_in_installer(finishes=False)
        for attempt in (1, 2):
            code, output = run_terminal([self.command], self.env)
            self.assertNotEqual(code, 0, output)
            self.assertIn("resuming the installation", output)
            self.assertEqual(self._order().count("installer"), attempt, "setup must resume the installer")
            self.assertNotIn("Ready.", output)

    def test_resumed_install_that_finishes_hands_over_to_the_installer(self) -> None:
        # The real installer offers Deepgram and runs the doctor itself at its end.
        self._mark_installed(None)
        self._stand_in_installer(finishes=True)
        code, output = run_terminal([self.command], self.env)
        self.assertEqual(code, 0, output)
        self.assertEqual(self._order(), ["installer"])

    def test_moved_install_is_resumed(self) -> None:
        self._mark_installed(Path("/elsewhere/project-sniper"))
        self._stand_in_installer(finishes=False)
        code, _output = run_terminal([self.command], self.env)
        self.assertNotEqual(code, 0)
        self.assertEqual(self._order(), ["installer"])

    def test_completed_install_does_not_rerun_the_installer(self) -> None:
        self._stand_in_installer(finishes=False)  # would fail loudly if called
        code, output = run_terminal([self.command], self.env)
        self.assertEqual(code, 0, output)
        self.assertNotIn("installer", self._order())

    def test_connection_modes_never_start_the_installer(self) -> None:
        self._mark_installed(None)
        self._stand_in_installer(finishes=True)
        done = subprocess.run([self.command, "--connections"], capture_output=True, text=True, env=self.env,
                              stdin=subprocess.DEVNULL, check=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("Installation has not finished", done.stderr)
        done = subprocess.run([self.command, "--finish-install"], capture_output=True, text=True, env=self.env,
                              stdin=subprocess.DEVNULL, check=False)
        self.assertNotEqual(done.returncode, 0, "the retired finish hand-off is refused")
        self.assertNotIn("installer", self._order())

    def test_installer_marks_completion_only_after_its_last_step(self) -> None:
        # Structural (a real install downloads); the real-install harness checks behaviour.
        # Step 1 (Sniper's own tools) runs before the maintenance lock, so it cannot clear the
        # receipt; an interruption there leaves the tools unmarked, which install_complete
        # refuses (test_missing_tools_resume_the_installer). Everything after it is covered here.
        text = (fx.INSTALL_SRC / "install.command").read_text()
        cleared, verified = text.index("clear_receipt installed"), text.index("\nverify_runtime_tools\n")
        built, written = text.index("studio/native_runtime.py\" --repair"), text.index('write_receipt installed "$PKG_ROOT"')
        offer = text.index("setup.command\" --connections --if-needed")
        self.assertLess(cleared, verified, "an interrupted run must not keep an earlier completion")
        self.assertLess(built, written, "completion is written after the last step")
        self.assertLess(written, offer, "the Deepgram offer sees a completed install")

    def test_missing_tools_resume_the_installer(self) -> None:
        # A finished install whose private tools were removed (or never finished) is not complete.
        prefix = fx.runtime_prefix(Path(self.env["HOME"]))
        for damage in ("marker", "tool"):
            with self.subTest(damage=damage):
                fx.make_runtime(Path(self.env["HOME"]))
                (prefix / ".sniper-runtime-complete" if damage == "marker" else prefix / "bin/ffmpeg").unlink()
                done = fx.bash(self.pkg, "install_complete && echo complete || echo incomplete", self.env)
                self.assertEqual(done.stdout.strip(), "incomplete", done.stderr)
        fx.make_runtime(Path(self.env["HOME"]))
        done = fx.bash(self.pkg, "install_complete && echo complete || echo incomplete", self.env)
        self.assertEqual(done.stdout.strip(), "complete", done.stderr)

    def test_new_user_is_offered_deepgram_checked_and_sent_to_their_own_agent(self) -> None:
        code, output = run_terminal([self.command], self.env)
        self.assertEqual(code, 0, output)
        self.assertIn("Deepgram (optional)", output)
        self.assertIn("Ready. Open this folder in Codex or Claude Code", output)
        self.assertEqual(self._order(), ["doctor "])

    def test_doctor_failure_does_not_claim_ready(self) -> None:
        code, output = run_terminal([self.command], {**self.env, "FAIL_DOCTOR": "1"})
        self.assertNotEqual(code, 0)
        self.assertIn("Setup is not ready yet.", output)
        self.assertNotIn("Ready.", output)

    def test_setup_never_signs_in_to_or_opens_a_provider(self) -> None:
        for name in RETIRED:
            self.assertFalse((fx.INSTALL_SRC / name).exists(), f"{name} is retired")
        for script in sorted(fx.INSTALL_SRC.glob("*.command")):
            text = script.read_text()
            for name in RETIRED:
                self.assertNotIn(name, text, f"{script.name} still names {name}")

    def test_noninteractive_setup_does_not_read_secrets(self) -> None:
        result = subprocess.run([self.command], input="not-a-key\n", text=True,
                                capture_output=True, env=self.env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Terminal window", result.stderr)
        self.assertNotIn("not-a-key", result.stdout + result.stderr)
        self.assertFalse((self.pkg / "runtime/deepgram.env").exists())


if __name__ == "__main__":
    unittest.main()
