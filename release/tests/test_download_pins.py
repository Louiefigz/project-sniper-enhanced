"""Item 5 (build side): the build refuses unpinned or inconsistent download pins.

Run: .venv/bin/python -m unittest release.tests.test_download_pins
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from release import pins
from release.stage import StagingError

PAYLOAD = Path(__file__).resolve().parents[1] / "payload_files/install"
CODEX, CLAUDE = "codex-cli 0.144.1", "2.1.247 (Claude Code)"


class DownloadPins(unittest.TestCase):
    """The shipped pins pass; each kind of tampering or staleness is refused."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-pins-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        shutil.copytree(PAYLOAD / "cli", self.base / "cli")

    def test_shipped_pins_are_complete(self) -> None:
        pins.check_python_lock(PAYLOAD / "requirements.lock.txt")
        pins.check_cli_lock(PAYLOAD / "cli", CODEX, CLAUDE)
        self.assertEqual(set(pins.browser_hashes(json.loads(pins.BROWSER_PIN.read_text())["version"])),
                         {"mac-arm64", "mac-x64"})

    def test_a_python_requirement_without_a_hash_is_refused(self) -> None:
        lock = self.base / "lock.txt"
        text = (PAYLOAD / "requirements.lock.txt").read_text()
        lock.write_text(text + "sneaky-package==1.0\n")
        with self.assertRaises(StagingError) as caught:
            pins.check_python_lock(lock)
        self.assertIn("sneaky-package", str(caught.exception))

    def test_cli_manifest_must_match_the_admitted_versions(self) -> None:
        with self.assertRaises(StagingError):
            pins.check_cli_lock(self.base / "cli", "codex-cli 0.145.0", CLAUDE)

    def test_cli_lock_entry_without_integrity_is_refused(self) -> None:
        lock_path = self.base / "cli/package-lock.json"
        lock = json.loads(lock_path.read_text())
        del lock["packages"]["node_modules/@openai/codex-darwin-arm64"]["integrity"]
        lock_path.write_text(json.dumps(lock))
        with self.assertRaises(StagingError) as caught:
            pins.check_cli_lock(self.base / "cli", CODEX, CLAUDE)
        self.assertIn("codex-darwin-arm64", str(caught.exception))

    def test_browser_pin_for_another_version_is_refused(self) -> None:
        stale = self.base / "pin.json"
        stale.write_text(json.dumps({"version": "150.0.0.0", "archives": {}}))
        with mock.patch.object(pins, "BROWSER_PIN", stale), self.assertRaises(StagingError):
            pins.browser_hashes("152.0.7977.30")


if __name__ == "__main__":
    unittest.main()
