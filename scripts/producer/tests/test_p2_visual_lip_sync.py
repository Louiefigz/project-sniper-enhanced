"""Controlled real-media gates for selected-source visual lip sync."""
from __future__ import annotations

import unittest

from edit.cut_repair_visual_lip_sync import qualify_visual_lip_sync
from edit.cut_repair_visual_lip_sync_types import (
    RegionPpm,
    VisualLipSyncBlocker,
)
from tests._p2_visual_lip_sync_fixture import (
    FFMPEG,
    VisualLipSyncFixture,
)


@unittest.skipUnless(FFMPEG, "ffmpeg required")
class VisualLipSyncOracleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = VisualLipSyncFixture()

    def tearDown(self) -> None:
        self.fixture.clean()

    def _blocked(self, mode: str, code: str,
                 region: RegionPpm | None = None) -> None:
        with self.assertRaises(VisualLipSyncBlocker) as raised:
            qualify_visual_lip_sync(self.fixture.request(mode, region))
        self.assertEqual(raised.exception.code, code)

    def test_aligned_candidate_binds_selected_source_and_exact_ranges(self) -> None:
        receipt = qualify_visual_lip_sync(self.fixture.request("aligned"))
        self.assertEqual(receipt["lipSyncDisposition"], "passed")
        self.assertEqual(receipt["visualMappingOffsetFrames"], 0)
        self.assertEqual(receipt["audioMappingOffsetFrames"], 0)
        self.assertEqual(receipt["avOffsetFrames"], 0)
        self.assertEqual(
            receipt["evidenceSemantics"],
            "caller-supplied-roi-source-av-temporal-mapping-"
            "not-face-mouth-or-phoneme-proof")
        self.assertEqual(receipt["alternateTakeSelectionReceiptHash"], "3" * 64)
        self.assertEqual(
            receipt["sourceFrameRange"]["endFrameExclusive"], 60)
        self.assertEqual(
            receipt["outputSampleRange"]["endSampleExclusive"], 96_000)
        self.assertGreaterEqual(receipt["visibleUncoveredFrameCount"], 12)

    def test_three_frame_audio_delay_fails_visible_speech_offset(self) -> None:
        self._blocked("delayed", "VISIBLE_SPEECH_AV_OFFSET")

    def test_solid_cover_fails_as_occluded_or_substituted(self) -> None:
        self._blocked(
            "occluded", "VISUAL_SPEECH_OCCLUDED_OR_SUBSTITUTED")

    def test_static_region_fails_unmeasurable(self) -> None:
        self._blocked(
            "aligned", "VISUAL_ORACLE_UNMEASURABLE",
            RegionPpm(0, 0, 200_000, 200_000))

    def test_periodic_visual_mapping_fails_ambiguous(self) -> None:
        self._blocked("periodic", "VISUAL_ORACLE_AMBIGUOUS_MAPPING")

    def test_candidate_byte_drift_fails_before_decode(self) -> None:
        request = self.fixture.request("aligned")
        with open(request.candidate.path, "ab") as stream:
            stream.write(b"drift")
        with self.assertRaises(VisualLipSyncBlocker) as raised:
            qualify_visual_lip_sync(request)
        self.assertEqual(raised.exception.code, "VISUAL_ORACLE_INPUT_DRIFT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
