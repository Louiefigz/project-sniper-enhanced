"""Live ownership faults with explicitly stubbed media observations, not admission."""
from __future__ import annotations

import subprocess
import unittest
from dataclasses import replace
from fractions import Fraction
from unittest.mock import Mock, patch

from _guided_presenter_observation_fixture import ObservationFixture
from graphics.presenter_layout_contract import PresenterCanvas, declaration_payload
from graphics.presenter_layout_geometry import compile_presenter_geometry
from guided_presenter_execution import OwnedPresenterExecution
from guided_presenter_observation import observe_presenter_asset


class OwnedPresenterExecutionTests(unittest.TestCase):
    """No stub JSON is counted as real decode, external admission or output QC."""

    def setUp(self) -> None:
        """Acquire the real control-flow result with only TEST probe stdout stubbed."""
        self.fixture = ObservationFixture()
        self.addCleanup(self.fixture.close)
        self.runtime = replace(self.fixture.runtime, guard=Mock())
        results = [subprocess.CompletedProcess([], 0, raw, "") for raw in self.fixture.raw()]
        with patch("guided_presenter_observation.run_text", side_effect=results):
            self.observed = observe_presenter_asset(self.fixture.selected, self.fixture.source,
                                                    "30000/1001", self.runtime)
        self.runtime.guard.reset_mock()

    def owner(self, selected: tuple | None = None) -> OwnedPresenterExecution:
        """Build a live TEST object; it grants no actual source or render approval."""
        return OwnedPresenterExecution(selected or (self.fixture.selected,), (self.observed,),
                                       "30000/1001", self.runtime)

    def window(self, index: int, span: tuple[int, int], offset: Fraction = Fraction(0)) -> object:
        """Compile each TEST occurrence on the full48-frame canvas with exact offset."""
        payload = declaration_payload(self.fixture.selected.geometry)
        payload["assetStart"] = {"numerator": offset.numerator, "denominator": offset.denominator}
        geometry = compile_presenter_geometry(payload, PresenterCanvas(64, 36, 48, "yuv420p"), span)
        return replace(self.fixture.selected, operation_index=index, geometry=geometry)

    def test_repeated_windows_share_observation_but_keep_original_index_and_origin(self) -> None:
        """Two occurrences use one retained decode without coalescing their windows."""
        selected = (self.window(7, (2, 18)), self.window(1, (26, 42)))
        with patch("guided_presenter_observation.run_text") as probe:
            owner = self.owner(selected)
            graph = owner.full_graph()
            pair = owner.prefix_graphs(30)
        probe.assert_not_called()
        self.assertEqual(len(owner.held_assets()), 1)
        self.assertEqual([row.operation_index for row in graph.windows], [7, 1])
        self.assertEqual(pair.opening, graph)
        self.assertEqual(pair.opening.windows[1].geometry.timing.end_frame_exclusive, 42)
        self.assertEqual(pair.full.canvas.total_frames, 48)
        self.assertIs(pair.observations, owner.observed)

    def test_later_occurrence_cannot_borrow_first_windows_asset_coverage(self) -> None:
        """A covered first window does not hide an overflowing later asset offset."""
        selected = (self.window(7, (2, 18)), self.window(1, (26, 42), Fraction(20 * 1001, 30000)))
        with self.assertRaisesRegex(ValueError, "coverage is insufficient"):
            self.owner(selected)

    def test_construction_uses_light_original_clock_for_each_retained_frame(self) -> None:
        """Frame validation cannot multiply expensive whole-source guard work."""
        before = self.fixture.deadline.calls
        self.owner()
        self.assertGreater(self.fixture.deadline.calls - before, 24)
        self.assertEqual(self.runtime.guard.call_count, 2)

    def test_original_expiry_and_guard_failure_propagate_without_new_probe(self) -> None:
        """No completed observation refreshes the original execution allowance."""
        owner = self.owner()
        self.fixture.deadline.expired = True
        with patch("guided_presenter_observation.run_text") as probe:
            with self.assertRaisesRegex(RuntimeError, "original deadline expired"):
                owner.full_graph()
        probe.assert_not_called()
        self.fixture.deadline.expired = False
        self.runtime.guard.side_effect = RuntimeError("TEST original source changed")
        with self.assertRaisesRegex(RuntimeError, "source changed"):
            owner.assert_current()

    def test_clock_expiry_inside_retained_validation_cannot_wait_for_next_asset(self) -> None:
        """Expire during actual frame-loop validation, not only at outer boundaries."""
        original = self.fixture.deadline.remaining
        start = self.fixture.deadline.calls

        def remaining() -> float:
            """Trip this TEST original clock while the first retained asset is parsed."""
            if self.fixture.deadline.calls - start >= 12:
                raise RuntimeError("TEST frame-loop deadline expired")
            return original()

        with patch.object(self.fixture.deadline, "remaining", side_effect=remaining):
            with self.assertRaisesRegex(RuntimeError, "frame-loop deadline expired"):
                self.owner()

    def test_selection_admission_and_extra_or_duplicate_observations_are_not_inferred(self) -> None:
        """An otherwise valid record cannot supply a different selected receipt."""
        selected = replace(self.fixture.selected,
                           admission=replace(self.fixture.selected.admission, receipt_sha256="b" * 64))
        with self.assertRaisesRegex(RuntimeError, "differs from selected"):
            self.owner((selected,))
        for observed in ((), (self.observed, self.observed)):
            with self.assertRaises(RuntimeError):
                OwnedPresenterExecution((self.fixture.selected,), observed, "30000/1001", self.runtime)

    def test_observation_from_another_tool_does_not_acquire_current_owner(self) -> None:
        """A current source reference does not replace the exact observed executable."""
        runtime = replace(self.runtime, ffprobe=replace(self.runtime.ffprobe, sha256="b" * 64))
        with self.assertRaisesRegex(RuntimeError, "different held probe tools"):
            OwnedPresenterExecution((self.fixture.selected,), (self.observed,), "30000/1001", runtime)

    def test_all_future_and_crossing_review_windows_keep_full_original_geometry(self) -> None:
        """Select whole original windows; never shorten ramps to the preview boundary."""
        owner = self.owner()
        self.assertIsNone(owner.prefix_graphs(2).opening)
        pair = owner.prefix_graphs(3)
        self.assertEqual(pair.opening, owner.full_graph())
        self.assertEqual(pair.opening.windows[0].geometry.timing.end_frame_exclusive, 18)
        for end in (False, 0, 25, 3.0):
            with self.assertRaises(RuntimeError):
                owner.prefix_graphs(end)

    def test_graph_return_is_isolated_and_actual_plan_track_is_exact(self) -> None:
        """A callback copy cannot alter its owner or inject unrequested plan windows."""
        owner = self.owner()
        graph = owner.full_graph()
        object.__setattr__(graph.windows[0], "operation_index", 12)
        self.assertEqual(owner.full_graph().windows[0].operation_index, 7)
        window = self.fixture.selected
        plan = {"presenterLayouts": [{"operationIndex": 7, "startFrame": 2, "endFrameExclusive": 18,
                                      "layout": declaration_payload(window.geometry)}]}
        owner.assert_plan(plan)
        plan["presenterLayouts"][0]["startFrame"] = 3
        with self.assertRaisesRegex(RuntimeError, "exact requested plan"):
            owner.assert_plan(plan)

    def test_boolean_replacement_cannot_compare_equal_to_original_integer(self) -> None:
        """Python0==False is not unchanged selected operation identity."""
        selected = replace(self.fixture.selected, operation_index=0)
        owner = self.owner((selected,))
        object.__setattr__(selected, "operation_index", False)
        with self.assertRaisesRegex(RuntimeError, "selection/observation/graph changed"):
            owner.assert_current()

    def test_replaced_observation_or_original_runtime_is_not_a_new_owner(self) -> None:
        """Typed snapshot equality includes tool/source/raw evidence and original clock."""
        owner = self.owner()
        object.__setattr__(self.observed.graph_asset, "total_frames", 24.0)
        with self.assertRaisesRegex(RuntimeError, "selection/observation/graph changed"):
            owner.assert_current()
        object.__setattr__(self.observed.graph_asset, "total_frames", 24)
        object.__setattr__(owner, "runtime", replace(self.runtime, deadline=Mock()))
        with self.assertRaisesRegex(RuntimeError, "runtime/guard/deadline changed"):
            owner.assert_current()

    def test_canvas_rate_count_changes_do_not_reinterpret_geometry(self) -> None:
        """The compositor cannot stretch the geometry or silently change cadence."""
        owner = self.owner()
        owner.assert_clock((64, 36), ("30000/1001", 24))
        for canvas, clock in (((66, 36), ("30000/1001", 24)), ((64, 36), ("30", 24)),
                              ((64, 36), ("30000/1001", 24.0))):
            with self.assertRaises(RuntimeError):
                owner.assert_clock(canvas, clock)


if __name__ == "__main__":
    unittest.main()
