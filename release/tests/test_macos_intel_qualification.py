"""Native-Intel qualification assembly and workflow contracts."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from release import prepare_macos_qualification, runtime_tools

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/macos-intel-qualification.yml"


class MacosIntelQualification(unittest.TestCase):
    """The qualification lane uses the pinned artifact on a native Intel runner."""

    def test_assembly_carries_exact_intel_runtime(self) -> None:
        target = runtime_tools.runtime_target("osx-64")
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "Project Sniper Intel"
            prepare_macos_qualification.assemble(package)
            pin = target.ffmpeg_pin.read_text(encoding="utf-8")
            artifact = runtime_tools.DIST / "sniper-ffmpeg-8.0.3-1-osx-64.tar.xz"
            installed = package / "install/deps" / artifact.name
            self.assertEqual(runtime_tools.file_sha256(installed), runtime_tools.file_sha256(artifact))
            self.assertIn('"platform": "osx-64"', pin)
            self.assertTrue((package / "sniper").is_file())

    def test_workflow_uses_native_intel_and_fixed_artifact_identity(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        pin = runtime_tools.runtime_target("osx-64").ffmpeg_pin.read_text(encoding="utf-8")
        self.assertIn("runs-on: macos-15-intel", text)
        self.assertIn("test \"$(uname -m)\" = x86_64", text)
        self.assertIn("cfe4ecc62fb4ff633380adb3bc26aec78734361857f4c3b73f7501240d98b0dd", text)
        self.assertIn("17918488", text)
        self.assertIn('"sha256": "cfe4ecc62fb4ff633380adb3bc26aec78734361857f4c3b73f7501240d98b0dd"', pin)
        for command in ("./sniper setup", "./sniper doctor --json", "./sniper workspace"):
            self.assertIn(command, text)


if __name__ == "__main__":
    unittest.main()
