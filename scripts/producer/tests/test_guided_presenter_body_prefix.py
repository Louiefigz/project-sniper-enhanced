"""Actual acquisition/cold-read control flow; all decoded/media facts are TEST stubs."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import subprocess
import unittest
from unittest.mock import patch

from _guided_presenter_capture_fixture import PresenterCaptureFixture
from cut_preview_io import digest
from graphics.composite_core import CompositeOptions
from graphics.owned_execution import GraphicsComposition
from guided_body_prefix import BodyPrefixBinding
from guided_opening_presenter import OpeningPresenterContext, _graph
from guided_presenter_body_prefix import presenter_body_prefix
from guided_presenter_capture import acquire_presenter_execution
from guided_presenter_read import verify_opening_presenter_layers
from opening_prefix_contract import CompositorPrefixRequest, PrefixClock, PrefixRanges
from opening_prefix_presenter import presenter_graph_payload
from test_opening_prefix_contract import held


class PresenterBodyPrefixTests(unittest.TestCase):
    """No cold receipt gains execution; only the separately acquired actual owner runs."""

    def setUp(self) -> None:
        """Acquire real tiny-file identities with explicit native metadata and probe stubs."""
        self.fixture = PresenterCaptureFixture(repeated=True)
        self.addCleanup(self.fixture.close)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        results = [subprocess.CompletedProcess([], 0, raw, "") for raw in self.fixture.probe.raw()]
        self.stack.enter_context(patch("guided_presenter_observation.run_text", side_effect=results))
        self.owner = self.stack.enter_context(acquire_presenter_execution(self.fixture.inputs, self.fixture.context))
        self.inputs = self.fixture.inputs
        self.authority = self.inputs.documents["authority"]
        path = self.fixture.probe.root / "TEST-base-not-media.mp4"
        path.write_bytes(b"TEST metadata only, not actual full-program preparation")
        self.base = held(path)
        clock = PrefixClock(self.authority["frameRate"], self.authority["totalFrames"], 1920, 1080)
        self.request = CompositorPrefixRequest(self.base, (), (), (), clock, PrefixRanges((0, 24), (0, 24)))
        _spec, record = _graph(OpeningPresenterContext(self.owner, self.inputs.documents["candidatePlan"], self.base),
                              self.authority, (), None)
        ranges = {"core": {"TEST": "no decoded media"}, "review": {"TEST": "no decoded media"}}
        pictures = {"presenterLayers": {**record, "pictureRangesHash": digest(ranges)}, "ranges": ranges}
        self.binding = BodyPrefixBinding(self.inputs, {"pictures": pictures}, path.parent)
        options = CompositeOptions(eof_pass=True, video_only=True, frame_rate=clock.frame_rate, presenter=self.owner.full_graph())
        self.value = GraphicsComposition(str(path), str(path.parent / "TEST-output"), (), options,
            (1920, 1080), (clock.frame_rate, clock.total_frames), presenter=self.owner)

    def test_original_record_is_read_only_and_live_body_keeps_full_future_window(self) -> None:
        original = digest(self.binding.original_result)
        with patch("guided_presenter_read.verify_opening_presenter_layers", wraps=verify_opening_presenter_layers) as reader:
            result = presenter_body_prefix(self.request, self.value, self.binding)
        reader.assert_called_once()
        self.assertIs(result.presenter.observations, self.owner.observed)
        self.assertEqual(len(result.presenter.full.windows), 2)
        self.assertEqual(len(result.presenter.opening.windows), 1)
        self.assertEqual(presenter_graph_payload(result.presenter.full), presenter_graph_payload(self.owner.full_graph()))
        self.assertEqual(digest(self.binding.original_result), original)
        self.assertIsNone(self.request.presenter)

    def test_unowned_or_json_only_body_cannot_reuse_a_genuine_opening_record(self) -> None:
        for owner in (None, {"status": "complete"}):
            with self.subTest(owner=owner), self.assertRaisesRegex(RuntimeError, "live.*owner"):
                presenter_body_prefix(self.request, replace(self.value, presenter=owner), self.binding)

    def test_changed_actual_compositor_geometry_is_not_replaced_by_read_record(self) -> None:
        graph = self.owner.full_graph()
        changed = replace(graph, windows=graph.windows[:1])
        value = replace(self.value, options=replace(self.value.options, presenter=changed))
        with patch("guided_presenter_read.verify_opening_presenter_layers") as reader:
            with self.assertRaisesRegex(RuntimeError, "actual compositor options"):
                presenter_body_prefix(self.request, value, self.binding)
        reader.assert_not_called()

    def test_cold_graph_and_observation_drift_cannot_gain_body_execution(self) -> None:
        record = self.binding.original_result["pictures"]["presenterLayers"]
        record["fullPresenterGraphHash"] = "0" * 64
        with self.assertRaises(RuntimeError):
            presenter_body_prefix(self.request, self.value, self.binding)

    def test_failed_cold_read_is_never_replaced_by_the_current_live_owner(self) -> None:
        with patch("guided_presenter_read.verify_opening_presenter_layers", side_effect=RuntimeError("TEST held receipt differs")):
            with self.assertRaisesRegex(RuntimeError, "held receipt differs"):
                presenter_body_prefix(self.request, self.value, self.binding)

    def test_second_presenter_attachment_and_expired_original_clock_fail(self) -> None:
        attached = replace(self.request, presenter=self.owner.prefix_graphs(24))
        with self.assertRaisesRegex(RuntimeError, "single actual"):
            presenter_body_prefix(attached, self.value, self.binding)
        self.fixture.probe.deadline.expired = True
        try:
            with self.assertRaisesRegex(RuntimeError, "original deadline expired"):
                presenter_body_prefix(self.request, self.value, self.binding)
        finally:
            self.fixture.probe.deadline.expired = False


if __name__ == "__main__":
    unittest.main()
