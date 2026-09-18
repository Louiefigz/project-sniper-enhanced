"""Actual local PNG/video observation; TEST admission metadata, not isolated authority."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from _guided_presenter_observation_fixture import held
from _guided_presenter_observation_media_fixture import PresenterObservationMediaFixture
from guided_presenter_observation import validate_presenter_observation
from guided_presenter_probe_identity import probe_deadline_remaining


class PresenterObservationMediaTests(unittest.TestCase):
    """Run installed local tools once; preserve every failed/successful fixture root."""

    @classmethod
    def setUpClass(cls) -> None:
        """Both actual source classes share one original180s fixture allowance."""
        cls.fixture = PresenterObservationMediaFixture()

    def test_actual_tagged_png_metadata_and_single_decoded_frame(self) -> None:
        """Real emitted chunks and decoder observations agree without invented sRGB tags."""
        case = self.fixture.cases["still"]
        self.assertEqual(case.source, held(Path(case.source.path)))
        self.assertEqual(case.observed.graph_asset.total_frames, 1)
        self.assertEqual(case.observed.graph_asset.pixel_format, "rgb24")
        self.assertEqual(case.observed.graph_asset.color_policy, "srgb-display-to-bt709-bt1886-v1")
        self.assertIn("sRGB", case.observed.evidence.png_metadata.color_chunks)
        self.assertIn("pHYs", dict(case.observed.evidence.png_metadata.metadata))
        self.assertEqual(len(json.loads(case.observed.evidence.frames_json)["frames"]), 1)

    def test_actual_video_all_frames_have_exact_original_ntsc_clock(self) -> None:
        """Header,24 decoded PTS/durations and actual EOF are independently retained."""
        case = self.fixture.cases["video"]
        asset, evidence = case.observed.graph_asset, case.observed.evidence
        self.assertEqual((asset.frame_rate, asset.total_frames), ("30000/1001", 24))
        self.assertEqual((asset.pixel_format, asset.color_policy), ("yuv420p", "bt709-limited-video"))
        header = json.loads(evidence.header_json)
        self.assertEqual([row["codec_type"] for row in header["streams"]], ["video", "audio"])
        self.assertEqual(header["streams"][1]["codec_name"], "aac")
        frames = json.loads(evidence.frames_json)["frames"]
        self.assertEqual([row["pts"] for row in frames], [index * 1001 for index in range(24)])
        self.assertEqual([row["duration"] for row in frames], [1001] * 24)
        self.assertEqual(len(self.fixture.commands), 6)

    def test_actual_retained_revalidation_never_decodes_again(self) -> None:
        """The same live observations are reusable under the original deadline only."""
        runtime = self.fixture.runtime
        with patch("guided_presenter_observation.run_text", side_effect=AssertionError("unexpected second decode")):
            for case in self.fixture.cases.values():
                validate_presenter_observation(case.observed, lambda: probe_deadline_remaining(runtime))
        self.assertFalse(case.observed.executable)
        self.assertFalse(case.observed.rights_verified)


if __name__ == "__main__":
    unittest.main()
