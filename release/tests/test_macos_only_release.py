"""The release has one dynamic macOS package and no Windows distribution surface."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from release.runtime_target import SUPPORTED

ROOT = Path(__file__).resolve().parents[2]
REMOVED = (
    "release/payload_files/sniper.cmd",
    "release/payload_files/sniper.ps1",
    "release/payload_files/install/install.ps1",
    "release/payload_files/install/deps/win-64.lock",
    ".github/workflows/windows-qualification.yml",
    "scripts/producer/headless/windows_media_runtime.py",
)
BUYER_TEXT = (
    "AGENTS.md", "CLAUDE.md", "release/payload_files/START-HERE.html",
    "release/payload_files/RELEASE-NOTES.md", "release/payload_files/PENDING-OWNER-DECISIONS.txt",
    "release/payload_files/manual/index.html", "release/payload_files/manual/install.html",
    "release/payload_files/manual/privacy.html", "release/payload_files/manual/troubleshooting.html",
    "release/payload_files/manual/license-and-updates.html",
)
FORBIDDEN = ("sniper.cmd", "win-64", "windows x64", "appcontainer", "install.ps1")


class MacOSOnlyRelease(unittest.TestCase):
    """Keep the supported target matrix and shipped instructions Mac-only."""

    def test_target_and_browser_pins_cover_both_mac_architectures(self) -> None:
        self.assertEqual(SUPPORTED, ("osx-arm64", "osx-64"))
        pin = json.loads((ROOT / "release/pins/chrome-headless-shell.json").read_text())
        self.assertEqual(set(pin["archives"]), {"mac-arm64", "mac-x64"})

    def test_windows_distribution_files_are_absent(self) -> None:
        self.assertFalse([path for path in REMOVED if (ROOT / path).exists()])

    def test_buyer_instructions_name_only_the_mac_launcher(self) -> None:
        for relative in BUYER_TEXT:
            text = (ROOT / relative).read_text(encoding="utf-8").lower()
            with self.subTest(relative=relative):
                self.assertFalse([token for token in FORBIDDEN if token in text])


if __name__ == "__main__":
    unittest.main()
