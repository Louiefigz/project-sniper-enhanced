"""Opt-in actual networkless tiny synthetic decoder tests; no grade/approval.

Set SNIPER_GRADE_TEST_ADMITTED_PRODUCER plus existing approved Docker settings.
The host encoder only constructs deliberately hostile test media. Every claimed
metadata decode runs inside the same attested production image. Artifacts stay.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from _grade_observation_media_fixture import admitted_synthetic, hostile_copies, late_metadata_source
from color.grade_observation_read import read_observation
from cut_preview_io import digest, file_hash, write_new
from headless.grade_observation_policy import GradeIsolationError, run_isolated_grade


@unittest.skipUnless(os.environ.get("SNIPER_GRADE_TEST_ADMITTED_PRODUCER"), "opt-in approved isolated media tests")
class GradeObservationMediaTests(unittest.TestCase):
    """Actual complete and hostile decoding, explicitly not creator-video quality."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.producer = Path(os.environ["SNIPER_GRADE_TEST_ADMITTED_PRODUCER"]).resolve()
        cls.source = admitted_synthetic(cls.producer)
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-grade-media-regression-")).resolve()
        cls.hostile = hostile_copies(cls.source, cls.root)
        cls.metadata = late_metadata_source(cls.root)
        print(f"\nRetained synthetic grade evidence: {cls.root}", flush=True)

    def execute(self, path: Path, name: str) -> tuple[Path, dict, dict]:
        root = self.root / name
        root.mkdir(mode=0o700)
        sha = file_hash(path)
        request = {"sourceSha256": sha, "frameCount": 180, "timeoutSeconds": 120}
        return root, run_isolated_grade(str(path), request, root), request

    def context(self, sha: str) -> tuple[dict, dict]:
        declaration = {"schemaVersion": 1, "sourceId": self.source["id"], "sourceProfile": "bt709-sdr",
            "cameraProfile": "Deliberately synthetic test only", "historyState": "known", "transformHistory": [],
            "lightingGroups": [{"id": "whole", "startFrame": 0, "endFrame": 180,
                "intent": "neutral", "description": "No correction or quality conclusion"}]}
        return ({"sourceId": self.source["id"], "sourceSha256": sha, "admissionReceiptSha256": self.source["admissionReceiptSha256"],
            "projectHistorySha256": file_hash(self.producer.parent / "project.json"),
            "declarationSha256": digest(declaration), "fps": "2", "frameCount": 180}, declaration)

    def test_actual_full_source_including_frame179_metadata_is_covered(self) -> None:
        started = time.monotonic()
        root, held, request = self.execute(Path(self.source["path"]), "full-source")
        result = read_observation(root, self.context(request["sourceSha256"]), held)
        self.assertEqual(result.records.decoded_record_count, 180)
        self.assertFalse(result.grade_applicable)
        self.assertTrue(held["cleanupVerified"])
        write_new(root / "test-result.json", {"decodedFrames": 180, "lateSeconds": 89.5,
            "elapsedMs": round((time.monotonic() - started) * 1000), "syntheticTestOnly": True,
            "gradeApplicable": False, "deliveryApproved": False})

    def test_actual_corrupted_late_packet_and_truncated_copy_reject(self) -> None:
        for name, path in self.hostile.items():
            with self.subTest(name=name), self.assertRaises(GradeIsolationError) as raised:
                self.execute(path, name + "-attempt")
            error = raised.exception
            self.assertTrue(error.cleanup_verified)
            self.assertEqual(error.evidence["status"], "failed")
            self.assertFalse(error.evidence["gradeApplicable"])
            if name == "late-corrupt":
                decoder = error.evidence["worker"]["decoder"]
                self.assertGreaterEqual(decoder["frames"], 100)
                self.assertGreater(decoder["stderrBytes"], 0)

    def test_actual_late_stream_metadata_change_cannot_be_homogeneous_bt709(self) -> None:
        root, held, request = self.execute(self.metadata, "late-metadata-attempt")
        raw = (root / "result/frames.ffprobe").read_text()
        self.assertIn("color_transfer=bt709", raw)
        self.assertIn("color_transfer=smpte2084", raw)
        with self.assertRaisesRegex(ValueError, "color metadata"):
            read_observation(root, self.context(request["sourceSha256"]), held)
        self.assertTrue(held["cleanupVerified"])


if __name__ == "__main__":
    unittest.main()
