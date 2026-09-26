"""Build-side Windows target, source approval and payload checks."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from release import payload, runtime_tools

ROOT = Path(__file__).resolve().parents[2]
HEADLESS = ROOT / "scripts/producer/headless"


class WindowsRelease(unittest.TestCase):
    """The dynamic package carries a complete, internally consistent Windows lane."""

    def test_windows_runtime_lock_verifies(self) -> None:
        result = runtime_tools.check("win-64")
        self.assertEqual(result["runtime_min_windows"], "10.0.19045")
        self.assertIn("BtbN/FFmpeg-Builds", result["runtime_tools"]["ffmpeg"])

    def test_windows_jail_sources_match_the_approval(self) -> None:
        approval = json.loads((HEADLESS / "windows_media_runtime_approval.json").read_text())
        found = {name: hashlib.sha256((HEADLESS / name).read_bytes()).hexdigest()
                 for name in approval["approved"]}
        self.assertEqual(found, approval["approved"])

    def test_windows_buyer_entry_points_exist(self) -> None:
        required = ("sniper.cmd", "sniper.ps1", "install/install.ps1", "install/doctor.ps1",
                    "install/uninstall.ps1", "install/studio.cmd", "install/studio.ps1")
        self.assertFalse([name for name in required if not (payload.PAYLOAD / name).is_file()])

    def test_windows_powershell_sources_are_ascii(self) -> None:
        scripts = (payload.PAYLOAD / "install").rglob("*.ps1")
        non_ascii = [str(script.relative_to(payload.PAYLOAD)) for script in scripts
                     if not script.read_bytes().isascii()]
        self.assertEqual(non_ascii, [], "Windows PowerShell 5 misreads BOM-less UTF-8")


if __name__ == "__main__":
    unittest.main()
