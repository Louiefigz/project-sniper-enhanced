"""Fail-closed cut manifestation and downstream delivery authority tests."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import *  # noqa: F401,F403

import cut_delivery_authority as cda
import cut_manifestation_authority as cma
from cut_elementary_proof import ElementaryStream, SequenceProof
from fingerprint_io import file_sha256
from fingerprints import plan_content_hash


PLAN = {
    "planVersion": 2,
    "target": {"mode": "short", "treatment": "produced"},
    "cutTrack": [
        {"sourceId": "raw", "start": 10.0, "end": 12.0, "speed": 1.0},
        {"sourceId": "raw", "start": 13.0, "end": 14.5, "speed": 1.0},
        {"sourceId": "raw", "start": 16.0, "end": 18.5, "speed": 1.0},
    ],
    "graphicsTrack": [],
    "music": {"enabled": False},
}
TIMELINE = {
    "outputDuration": 6.0,
    "segments": [
        {"index": 0, "source_id": "raw", "src_start": 10.0,
         "src_end": 12.0, "speed": 1.0, "out_start": 0.0,
         "out_end": 2.0, "audio_lead_s": 0.0},
        {"index": 1, "source_id": "raw", "src_start": 13.0,
         "src_end": 14.5, "speed": 1.0, "out_start": 2.0,
         "out_end": 3.5, "audio_lead_s": 0.0},
        {"index": 2, "source_id": "raw", "src_start": 16.0,
         "src_end": 18.5, "speed": 1.0, "out_start": 3.5,
         "out_end": 6.0, "audio_lead_s": 0.0},
    ],
}


class CutManifestationAuthorityTests(unittest.TestCase):
    """Exercise retained-work deletion and authority-tampering failures."""

    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="cut-manifest-authority-")
        self.timeline = os.path.join(self.root, "timeline_map.json")
        Path(self.timeline).write_text(json.dumps(TIMELINE), encoding="utf-8")
        self.parts = [os.path.join(self.root, f"part_{i}.mp4")
                      for i in range(3)]
        self.concat = os.path.join(self.root, "mezzanine.mp4")
        self.base = os.path.join(self.root, "base_final.mp4")
        self.final = os.path.join(self.root, "final.mp4")
        for index, path in enumerate(
                [*self.parts, self.concat, self.base, self.final]):
            Path(path).write_bytes(f"media-{index}".encode())
        self.frames = {
            os.path.abspath(self.parts[0]): 4,
            os.path.abspath(self.parts[1]): 3,
            os.path.abspath(self.parts[2]): 5,
            os.path.abspath(self.concat): 12,
            os.path.abspath(self.base): 12,
            os.path.abspath(self.final): 12,
        }
        patcher = mock.patch.object(
            cma, "probe_video_frames",
            side_effect=lambda path: self.frames[os.path.abspath(path)])
        self.addCleanup(patcher.stop)
        patcher.start()
        elementary = mock.patch.object(
            cma, "prove_video_sequence", side_effect=self._elementary)
        self.addCleanup(elementary.stop)
        elementary.start()
        self._manifest()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _manifest(self) -> dict:
        proof = {
            "videoDuration": 6.0, "containerDuration": 6.02,
            "expectedDuration": 6.0, "videoFrames": 12,
            "driftFrames": 0.0, "toleranceFrames": 2.5, "segments": 3,
        }
        return cma.write_manifestation(cma.ManifestationInputs(
            PLAN, self.timeline, self.parts, self.concat, "2/1", proof))

    def _elementary(self, parts: list[str], concat: str) -> SequenceProof:
        """Synthetic lossless sequence proof; media framing is tested elsewhere."""
        rows = [
            ElementaryStream(str(index + 1) * 64, size)
            for index, size in enumerate((4, 3, 5))
        ]
        ordered = ElementaryStream("a" * 64, 12)
        return SequenceProof(rows, ordered, ordered)

    def _assembled(self) -> None:
        cda.seal_render_delivery(self.root, self.base, PLAN, True)
        sidecar = {
            "videoFingerprint": "irrelevant",
            "graphicsFingerprint": "irrelevant",
            "planHash": plan_content_hash(PLAN),
            "authorityHash": file_sha256(self.final),
        }
        Path(self.final + ".assembled.json").write_text(
            json.dumps(sidecar), encoding="utf-8")
        cda.seal_assembled_delivery(self.base, self.final, PLAN)

    def test_actual_producer_rounding_binds_fractional_timeline(self) -> None:
        """The cut producer emits four-decimal durations and three-decimal drift."""
        proof = {"videoDuration": 683.7664, "expectedDuration": 683.7083,
                 "driftFrames": 1.395}
        cma._verify_clock("24000/1001", {"outputDuration": 683.70825}, proof, 16394)
        proof["expectedDuration"] = 683.70825
        cma._verify_clock("24000/1001", {"outputDuration": 683.70825}, proof, 16394)

    def test_rounding_does_not_admit_another_duration_or_frame_clock(self) -> None:
        """Wrong rounding, wrong drift, and nonfinite timelines remain rejected."""
        proof = {"videoDuration": 683.7664, "expectedDuration": 683.7082,
                 "driftFrames": 1.395}
        with self.assertRaisesRegex(ValueError, "timeline duration"):
            cma._verify_clock("24000/1001", {"outputDuration": 683.70825}, proof, 16394)
        proof["expectedDuration"] = 683.7083
        with self.assertRaisesRegex(ValueError, "frame clock"):
            cma._verify_clock("24000/1001", {"outputDuration": 683.70825}, proof, 16395)
        with self.assertRaisesRegex(ValueError, "timeline duration"):
            cma._verify_clock("24000/1001", {"outputDuration": float("nan")}, proof, 16394)

    def test_work_parts_may_disappear_after_sealing(self) -> None:
        self._assembled()
        for path in [*self.parts, self.concat]:
            os.remove(path)
        proof = cda.verify_delivered_cuts(self.root, self.final, PLAN)
        self.assertEqual((proof.parts, proof.frames, proof.mode),
                         (3, 12, "assembled-final"))

    def test_repeated_assembly_extends_the_same_base_again(self) -> None:
        self._assembled()
        first = cda.verify_delivered_cuts(self.root, self.final, PLAN)
        cda.seal_assembled_delivery(self.base, self.final, PLAN)
        second = cda.verify_delivered_cuts(self.root, self.final, PLAN)
        self.assertEqual(first, second)

    def test_timeline_mutation_invalidates_manifestation(self) -> None:
        changed = json.loads(Path(self.timeline).read_text())
        changed["segments"][1]["src_start"] = 13.1
        Path(self.timeline).write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "current timeline"):
            cma.verify_manifestation(self.root, PLAN)

    def test_part_receipt_mutation_is_detected(self) -> None:
        path = os.path.join(self.root, cma.MANIFESTATION_NAME)
        receipt = json.loads(Path(path).read_text())
        receipt["parts"][0]["partFrames"] = 99
        Path(path).write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "receipt hash"):
            cma.verify_manifestation(self.root, PLAN)

    def test_final_byte_mutation_invalidates_delivery(self) -> None:
        self._assembled()
        Path(self.final).write_bytes(b"replaced-final")
        with self.assertRaisesRegex(ValueError, "bytes or frames"):
            cda.verify_delivered_cuts(self.root, self.final, PLAN)

    def test_wrong_base_cannot_be_extended_through_assemble(self) -> None:
        cda.seal_render_delivery(self.root, self.base, PLAN, True)
        Path(self.base).write_bytes(b"wrong-base")
        sidecar = {"planHash": plan_content_hash(PLAN),
                   "authorityHash": file_sha256(self.final)}
        Path(self.final + ".assembled.json").write_text(
            json.dumps(sidecar), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not match"):
            cda.seal_assembled_delivery(self.base, self.final, PLAN)


if __name__ == "__main__":
    unittest.main(verbosity=2)
