"""Fail-closed visual-review frame planning and extraction tests."""

import tempfile
import unittest
from unittest.mock import patch

from _common import *  # noqa: F401,F403

from audit import audit_frames as af


class GraphicFramePlanningTests(unittest.TestCase):
    """Every declared graphic receives useful, extractable review phases."""

    def test_normal_graphic_gets_settled_mid_and_exit(self) -> None:
        plan = {"graphicsTrack": [{"outStart": 1.0, "outEnd": 3.0}]}

        frames = [ref for ref in af.plan_frames(plan, 10.0)
                  if ref.kind == "graphic"]

        self.assertEqual(
            [ref.label for ref in frames],
            ["graphic0_settled", "graphic0_mid", "graphic0_exit"])
        self.assertEqual([ref.timestamp for ref in frames], [1.5, 2.0, 2.5])

    def test_clipped_window_is_clamped_and_deduped(self) -> None:
        plan = {"graphicsTrack": [{"outStart": 9.95, "outEnd": 20.0}]}

        frames = [ref for ref in af.plan_frames(plan, 10.0)
                  if ref.kind == "graphic"]

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].timestamp, 9.9)
        self.assertEqual(frames[0].label, "graphic0_settled")

    def test_overlapping_events_each_keep_their_review_phases(self) -> None:
        plan = {"graphicsTrack": [
            {"outStart": 1.0, "outEnd": 3.0},
            {"outStart": 1.0, "outEnd": 3.0},
        ]}

        frames = [ref for ref in af.plan_frames(plan, 10.0)
                  if ref.kind == "graphic"]

        self.assertEqual(len(frames), 6)
        self.assertEqual({ref.label.split("_")[0] for ref in frames},
                         {"graphic0", "graphic1"})

    def test_motion_and_transition_phases_are_reviewed(self) -> None:
        plan = {
            "punchIns": [{"outStart": 2.0, "outEnd": 4.0}],
            "transitions": [{"outTime": 6.0}],
        }

        frames = af.plan_frames(plan, 10.0)
        motion = [ref for ref in frames if ref.kind == "motion"]
        transitions = [ref for ref in frames if ref.kind == "transition"]

        self.assertEqual([ref.label for ref in motion],
                         ["motion0_settled", "motion0_mid", "motion0_exit"])
        self.assertEqual([ref.timestamp for ref in transitions], [5.9, 6.0, 6.1])
        self.assertTrue(all(ref.note for ref in motion + transitions))

    def test_every_internal_cut_gets_before_seam_after_frames(self) -> None:
        plan = {"cutTrack": [
            {"start": 0.0, "end": 2.0, "speed": 1.0},
            {"start": 4.0, "end": 8.0, "speed": 2.0},
            {"start": 9.0, "end": 10.0, "speed": 1.0},
        ]}

        frames = [ref for ref in af.plan_frames(plan, 6.0)
                  if ref.kind == "cut"]

        self.assertEqual([ref.label for ref in frames], [
            "cut0_before", "cut0_seam", "cut0_after",
            "cut1_before", "cut1_seam", "cut1_after",
        ])
        self.assertEqual([ref.timestamp for ref in frames],
                         [1.9, 2.0, 2.1, 3.9, 4.0, 4.1])


class RequiredExtractionTests(unittest.TestCase):
    """A missing planned review image is an Audit B failure."""

    def test_failed_extraction_is_recorded_and_fails(self) -> None:
        refs = [af.FrameRef("graphic0_mid", "graphic", 2.0, "")]
        with tempfile.TemporaryDirectory() as out_dir:
            with patch.object(af, "extract_frame", return_value=False):
                extracted = af.extract_review_frames("final.mp4", out_dir, refs)

        result = af.check_frame_extraction(extracted)

        self.assertEqual(extracted[0].path, "")
        self.assertEqual(result.status, af.FAIL)
        self.assertIn("graphic0_mid", result.detail)

    def test_all_required_frames_extracted_passes(self) -> None:
        refs = [af.FrameRef("cover", "cover", 0.2, "/tmp/cover.jpg")]

        result = af.check_frame_extraction(refs)

        self.assertEqual(result.status, af.PASS)
        self.assertIn("1/1", result.measured)


if __name__ == "__main__":
    unittest.main(verbosity=2)
