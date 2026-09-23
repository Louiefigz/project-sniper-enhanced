"""Item 8: install/studio.command runs Studio with the install's settings, not bare.

Run: .venv/bin/python -m unittest release.tests.test_studio_wrapper
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from release.tests import _fixture as fx

REAL_NODE = shutil.which("node", path="/opt/homebrew/bin:/usr/local/bin")
FAKE_PYTHON = r'''#!/bin/bash
# stands in for the app's venv Python: helpers (the lock, -c snippets) run on a real
# Python; the Studio entry point only reports what studio.command gave it.
case "$1" in *sniper_lock.py|-c|-I) exec "$REAL_PYTHON" "$@" ;; esac
{ printf 'ARGV'; printf ' [%s]' "$@"; printf '\n'
  printf 'NODE=%s KEY=%s WRAPPER=%s LOCK=%s PWD=%s\n' "$SNIPER_NODE_PATH" "${ANTHROPIC_API_KEY:-unset}" \
    "$SNIPER_STUDIO_COMMAND" "$SNIPER_LOCK_MODE" "$PWD"
  printf 'PATH_FIRST=%s\n' "${PATH%%:*}"; } > "$STUB_LOG_DIR/python.calls"
'''


@unittest.skipUnless(REAL_NODE, "no Node on this Mac to record as the install's Node")
class StudioWrapper(unittest.TestCase):
    """studio.command in a fixture package whose venv Python is a recorder."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-studio-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.pkg = fx.make_package(self.base)
        done = fx.write_settings(self.pkg, str(self.base / "videos"), {"NODE_BIN": str(Path(REAL_NODE).resolve())})
        self.assertEqual(done.returncode, 0, done.stderr)
        python = self.pkg / ".venv/bin/python3"  # replaces the fixture's wrapper file with a recorder
        python.write_text(FAKE_PYTHON)
        python.chmod(0o755)
        self.env = {**fx.base_env(self.pkg), "ANTHROPIC_API_KEY": "sk-test-not-a-real-key",
                    "REAL_PYTHON": sys.executable}

    def _studio(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["/bin/bash", str(self.pkg / "install/studio.command"), *args], capture_output=True,
                              text=True, timeout=60, env=self.env, check=False)

    def test_open_runs_studio_review_with_the_install_settings(self) -> None:
        done = self._studio("open", str(self.base / "videos/demo/producer"))
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = (Path(self.env["STUB_LOG_DIR"]) / "python.calls").read_text()
        self.assertIn("scripts/producer/studio/studio_review.py] [open]", calls)
        self.assertIn(f"NODE={Path(REAL_NODE).resolve()}", calls)
        self.assertIn("KEY=unset", calls, "an API key from the shell reached Studio")
        pkg = self.pkg.resolve()
        self.assertIn(f"WRAPPER={pkg}/install/studio.command", calls)
        self.assertIn("LOCK=shared", calls)
        self.assertIn(f"PWD={pkg}\n", calls)   # the package folder is the app folder
        self.assertIn(f"PATH_FIRST={pkg}/runtime/bin", calls)

    def test_unknown_subcommand_is_refused(self) -> None:
        done = self._studio("render", "x")
        self.assertEqual(done.returncode, 1)
        self.assertIn("Usage: install/studio.command", done.stderr)


if __name__ == "__main__":
    unittest.main()
