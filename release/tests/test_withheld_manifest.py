"""The build's withheld manifest lists everything the source has that the package does not.

The package gate excuses a declared evidence test only for a missing file this
manifest lists, so the manifest must be complete for withheld evidence and must
never list folders the install itself creates.
"""
from __future__ import annotations

import subprocess
import unittest

from release import payload
from release.build_package import ROOT


class WithheldManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True,
                                 check=True).stdout.splitlines()
        self.shipped = [path for path in tracked if path.startswith("scripts/producer/headless/")]
        self.records = payload.withheld_records(ROOT, [("scripts/producer/x/__pycache__/a.pyc", "byte cache")],
                                                self.shipped)
        self.by_path = {row["path"]: row for row in self.records}

    def test_withheld_evidence_folders_are_listed_as_folders(self) -> None:
        for folder in ("artifacts", "scripts/producer/artifacts", "docs/audits", "templates/motion/container"):
            self.assertEqual(self.by_path[folder].get("kind"), "folder", folder)

    def test_folders_the_install_creates_are_never_listed(self) -> None:
        for folder in ("node_modules", "templates/motion/node_modules", ".venv", ".next", "__pycache__"):
            self.assertNotIn(folder, self.by_path, folder)

    def test_tracked_files_that_do_not_ship_are_listed(self) -> None:
        self.assertIn("docs/producer/command-driven-editing/contracts/hyperframes-rate-matrix-v1.json", self.by_path)
        self.assertIn("release/package_spec.py", self.by_path)

    def test_shipped_files_and_skipped_files(self) -> None:
        self.assertFalse(set(self.shipped) & set(self.by_path), "a shipped file is listed as withheld")
        self.assertEqual(self.by_path["scripts/producer/x/__pycache__/a.pyc"]["reason"], "byte cache")


if __name__ == "__main__":
    unittest.main()
