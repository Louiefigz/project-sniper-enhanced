"""Pure trajectory/intersection controls; TEST boxes are not actual caption pixels."""
from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from unittest.mock import patch

from _presenter_caption_clearance_fixture import ClearanceFixture
from graphics.presenter_layout_contract import PresenterCanvas
from graphics.presenter_layout_geometry import compile_presenter_geometry, presenter_frame
from guided_presenter_caption_clearance import (
    _pair, inspect_presenter_caption_clearance, swept_subject_bounds,
)
from test_presenter_layout_geometry import _payload


class PresenterCaptionGeometryTests(unittest.TestCase):
    """Prove bounded manual-envelope math independently of media/projection seams."""

    def geometry(self, kind: str = "inset", total: int = 120) -> object:
        """Use existing explicit TEST declarations on the full original canvas."""
        return compile_presenter_geometry(_payload(kind), PresenterCanvas(1920, 1080, total, "yuv420p"), (3, total))

    def test_swept_bounds_enclose_every_frame_and_all_opposite_corners(self) -> None:
        """A circle's mask must not turn a rectangular protected envelope into its centre."""
        for kind in ("inset", "bubble", "split"):
            geometry = self.geometry(kind)
            bounds = swept_subject_bounds(geometry, (3, 120))
            self.assert_enclosed(geometry, bounds)

    def assert_enclosed(self, geometry: object, bounds: list[float]) -> None:
        """Independent exhaustive TEST-only projection checks every written frame."""
        for frame in range(3, 120):
            state = presenter_frame(geometry, frame)
            points = [(state.scale * x + state.translation[0], state.scale * y + state.translation[1])
                      for x, y in geometry.shape.surfaces.protected.corners()]
            self.assertTrue(all(bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3] for x, y in points))

    def test_long_duration_uses_at_most_four_original_frame_evaluations(self) -> None:
        """A long hold changes endpoints, not the number of geometry evaluations."""
        geometry = self.geometry(total=432000)
        with patch("guided_presenter_caption_clearance.presenter_frame", wraps=presenter_frame) as evaluate:
            swept_subject_bounds(geometry, (3, 432000))
        self.assertLessEqual(evaluate.call_count, 4)
        self.assertEqual(evaluate.call_args_list[-1].args[1], 431999)

    def test_invalid_or_boolean_intersection_is_not_clamped(self) -> None:
        """No caller can silently change its covered original frame interval."""
        for span in ((False, 120), (2, 120), (3, 121), (7, 7)):
            with self.assertRaises(RuntimeError):
                swept_subject_bounds(self.geometry(), span)


class PresenterCaptionIntersectionTests(unittest.TestCase):
    """Live TEST owners plus explicitly stubbed cue projection; no actual media."""

    def setUp(self) -> None:
        """Prepare real immutable metadata once per independently isolated test."""
        self.fixture = ClearanceFixture()
        self.addCleanup(self.fixture.close)
        self.context = self.fixture.context
        self.window = self.context.presenter.full_graph().windows[0]

    def inspect(self, cues: list[dict], context: object = None) -> dict:
        """Stub only cue pixels; source/runtime/plan/clock binding remains exercised."""
        with patch("guided_presenter_caption_clearance._captions", return_value=cues):
            return inspect_presenter_caption_clearance(context or self.context, self.fixture.guard)

    def test_safe_final_position_cannot_hide_entry_and_exit_collision(self) -> None:
        """A cue under the original subject is safe at hold but conflicts at both ramps."""
        box = (440, 600, 460, 620)
        safe = self.inspect([self.fixture.cue((30, 60), box)])
        self.assertEqual(safe["state"], "screened-no-overlap")
        for span in ((0, 15), (105, 120)):
            with self.assertRaisesRegex(RuntimeError, "clearance conflict"):
                self.inspect([self.fixture.cue(span, box)])

    def test_exact_adjacency_does_not_intersect_and_one_frame_does(self) -> None:
        """Frame endpoints, rather than rounded seconds, decide temporal overlap."""
        cue = self.fixture.cue((120, 130), (440, 600, 460, 620))
        self.assertIsNone(_pair(self.window, cue, {"startFrame": 0, "endFrameExclusive": 960}))
        cue["startFrame"] = 119
        self.assertTrue(_pair(self.window, cue, {"startFrame": 0, "endFrameExclusive": 960})["conflict"])

    def test_crossing_opening_keeps_original_exit_not_a_shortened_animation(self) -> None:
        """Opening coverage must not restart or pull forward the full-window exit."""
        inputs = copy.deepcopy(self.context.inputs)
        inputs.documents["authority"]["review"]["endFrameExclusive"] = 60
        context = replace(self.context, inputs=inputs, coverage={"startFrame": 0, "endFrameExclusive": 60})
        report = self.inspect([self.fixture.cue((30, 110), (440, 600, 460, 620))], context)
        self.assertEqual(report["intersections"][0]["endFrameExclusive"], 60)
        self.assertEqual(report["binding"]["presenterGraph"]["windows"][0]["frameRange"], [0, 120])

    def test_future_body_only_collision_cannot_borrow_opening_clearance(self) -> None:
        """The same full graph has a genuine opening gap and a later body conflict."""
        window = self.fixture.window((300, 420))
        owner = self.fixture.make_owner((window,))
        inputs = copy.deepcopy(self.context.inputs)
        track = inputs.documents["candidatePlan"]["presenterLayouts"][0]
        track.update(startFrame=300, endFrameExclusive=420)
        from cut_preview_io import digest
        inputs.documents["authority"]["candidatePlanHash"] = digest(inputs.documents["candidatePlan"])
        opening = replace(self.context, inputs=inputs, presenter=owner)
        cue = self.fixture.cue((300, 310), (440, 600, 460, 620))
        self.assertEqual(self.inspect([cue], opening)["state"], "not-applicable")
        body = replace(opening, coverage={"startFrame": 0, "endFrameExclusive": 960})
        with self.assertRaisesRegex(RuntimeError, "clearance conflict"):
            self.inspect([cue], body)

    def test_fixed_gutter_and_inclusive_caption_maxima_are_not_waived(self) -> None:
        """Exactly16-pixel clearance is allowed, one pixel less remains a conflict."""
        bounds = swept_subject_bounds(self.window.geometry, (30, 60))
        box = (int(bounds[2]) + 16, 1300, int(bounds[2]) + 20, 1310)
        self.assertFalse(_pair(self.window, self.fixture.cue((30, 60), box), self.context.coverage)["conflict"])
        box = (box[0] - 1, *box[1:])
        self.assertTrue(_pair(self.window, self.fixture.cue((30, 60), box), self.context.coverage)["conflict"])


if __name__ == "__main__":
    unittest.main()
