"""The deep study only ever decodes admitted reference snapshots."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from _native_media_fixture import HAVE_NATIVE, valid_mp4
from headless.admit_external_media_cli import admit_reference
from study.study_admission import STORE_NAME, admitted_study_input


@unittest.skipUnless(HAVE_NATIVE, "needs macOS and ffmpeg")
class StudyAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.clip = valid_mp4(self.root / "reference.mp4")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_raw_file_is_admitted_before_study(self) -> None:
        studied = Path(admitted_study_input(str(self.clip), str(self.root / "study")))
        self.assertEqual(studied.parent, self.root / "study" / STORE_NAME)
        self.assertRegex(studied.name, r"^[0-9a-f]{64}\.media$")
        self.assertEqual(studied.read_bytes(), self.clip.read_bytes())

    def test_admitted_snapshot_is_studied_without_a_second_admission(self) -> None:
        snapshot = admit_reference(str(self.clip), str(self.root / "gui"))["snapshotPath"]
        self.assertEqual(admitted_study_input(snapshot, str(self.root / "study")), snapshot)
        self.assertFalse((self.root / "study" / STORE_NAME).exists())

    def test_tampered_snapshot_is_not_trusted(self) -> None:
        snapshot = Path(admit_reference(str(self.clip), str(self.root / "gui"))["snapshotPath"])
        snapshot.chmod(0o600)
        snapshot.write_bytes(snapshot.read_bytes()[:-16])
        studied = Path(admitted_study_input(str(snapshot), str(self.root / "study")))
        self.assertNotEqual(studied, snapshot, "a changed snapshot is re-admitted, never trusted")
        self.assertEqual(studied.parent, self.root / "study" / STORE_NAME)


if __name__ == "__main__":
    unittest.main()
