"""Run guided setup in a real terminal with offline subscription/doctor stand-ins.

The real connection UI, settings loader, editor launcher and maintenance locks run.
No provider login, account, API request or paid call is made by these tests.
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
if [ "$1" = --provider-only ]; then
  [ -f "$STUB_LOG_DIR/signed-in" ]; exit $?
fi
[ "${FAIL_DOCTOR:-0}" = 0 ] || { echo 'FAIL: sample admission'; exit 1; }
echo 'All required checks passed.'
'''
SIGN_IN = '''#!/bin/bash
echo sign-in >> "$STUB_LOG_DIR/order"
[ "${FAIL_SIGN_IN:-0}" = 0 ] || exit 1
touch "$STUB_LOG_DIR/signed-in"
'''


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
    """Success launches after validation; failures never claim readiness or launch."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-guided-")
        self.addCleanup(self.temp.cleanup)
        self.pkg = fx.make_package(Path(self.temp.name))
        self.env = fx.base_env(self.pkg)
        self.logs = Path(self.env["STUB_LOG_DIR"])
        # The shared fixture's regular wrapper file around this interpreter (never a link to it).
        self.python = self.pkg / "app/.venv/bin/python3"
        self.assertTrue(self.python.is_file() and not self.python.is_symlink())
        self.assertEqual(fx.write_settings(self.pkg, "codex", str(self.pkg.parent / "videos")).returncode, 0)
        for name, content in (("doctor.command", DOCTOR), ("sign-in.command", SIGN_IN)):
            (self.pkg / "install" / name).write_text(content)
        # The real editor calls this CLI; its fixture logs argv, provider and lock mode.
        self.command = str(self.pkg / "install/setup.command")

    def test_new_user_is_signed_in_checked_and_editor_opens(self) -> None:
        code, output = run_terminal([self.command], self.env)
        self.assertEqual(code, 0, output)
        self.assertIn("Deepgram (optional)", output)
        self.assertIn("Ready.", output)
        self.assertEqual((self.logs / "order").read_text().splitlines(),
                         ["doctor --provider-only", "sign-in", "doctor "])
        self.assertIn("LOCK=shared", (self.logs / "codex.calls").read_text())

    def test_existing_login_is_not_repeated(self) -> None:
        (self.logs / "signed-in").touch()
        code, output = run_terminal([self.command], self.env)
        self.assertEqual(code, 0, output)
        self.assertIn("Already signed in.", output)
        self.assertNotIn("\nsign-in\n", (self.logs / "order").read_text())

    def test_sign_in_failure_does_not_launch_or_claim_ready(self) -> None:
        code, output = run_terminal([self.command], {**self.env, "FAIL_SIGN_IN": "1"})
        self.assertNotEqual(code, 0)
        self.assertIn("Reopen install/setup.command", output)
        self.assertNotIn("Ready.", output)
        self.assertFalse((self.logs / "codex.calls").exists())

    def test_doctor_failure_does_not_launch_or_claim_ready(self) -> None:
        code, output = run_terminal([self.command], {**self.env, "FAIL_DOCTOR": "1"})
        self.assertNotEqual(code, 0)
        self.assertIn("Setup is not ready yet.", output)
        self.assertFalse((self.logs / "codex.calls").exists())

    def test_installer_finish_never_opens_editor_under_exclusive_lock(self) -> None:
        code, output = run_terminal([self.command, "--finish-install"], self.env)
        self.assertEqual(code, 0, output)
        self.assertIn("double-click install/editor.command", output)
        self.assertFalse((self.logs / "codex.calls").exists())

    def test_noninteractive_setup_does_not_read_secrets(self) -> None:
        result = subprocess.run([self.command], input="not-a-key\n", text=True,
                                capture_output=True, env=self.env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Terminal window", result.stderr)
        self.assertNotIn("not-a-key", result.stdout + result.stderr)
        self.assertFalse((self.pkg / "runtime/deepgram.env").exists())


if __name__ == "__main__":
    unittest.main()
