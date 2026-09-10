"""Strong actual-file read paths over TEST metadata; no native media/admission."""
from __future__ import annotations

import copy
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _presenter_caption_clearance_fixture import ClearanceFixture
from cut_preview_io import digest
from graphics.presenter_layout_contract import declaration_payload
from guided_caption_layout import _cue
from guided_caption_screen import CaptionScreenContext, screen_result
from guided_presenter_caption_clearance import (
    _MAX_PAIRS, inspect_presenter_caption_clearance,
    verify_presenter_caption_clearance,
)


class PresenterCaptionBindingTests(unittest.TestCase):
    """No fixture-produced metadata is claimed to be actual decoded caption pixels."""

    def setUp(self) -> None:
        """Build an actual live TEST owner with only the decoder result stubbed."""
        self.fixture = ClearanceFixture()
        self.addCleanup(self.fixture.close)
        self.context = self.fixture.context

    def inspect(self) -> dict:
        """Exercise actual caption held-file readback and live presenter validation."""
        return inspect_presenter_caption_clearance(self.context, self.fixture.guard)

    def test_real_held_projection_report_has_false_approval_and_lossless_json(self) -> None:
        """Strong metadata binding works without mistaking fake fixture media for QC."""
        result = self.inspect()
        self.assertEqual(result["state"], "screened-no-overlap")
        self.assertEqual(result["gutterPx"], 16)
        self.assertTrue(all(result[key] is False for key in (
            "pictureProofBound", "qcPassed", "creativeApproved", "deliveryApproved")))
        self.assertEqual(result["binding"]["captionProjectionHash"], self.context.held.data_hash)
        self.assertEqual(result["binding"]["candidatePlanHash"], digest(self.context.inputs.documents["candidatePlan"]))
        verify_presenter_caption_clearance(self.context, json.loads(json.dumps(result)), self.fixture.guard)
        self.assertEqual(result["binding"]["presenterObservations"][0]["source"]["sha256"], self.fixture.probe.source.sha256)

    def test_actual_ntsc_metadata_clock_and_exact_adjacent_frame_bounds(self) -> None:
        """Compile real rational caption metadata and retain the same live graph rate."""
        fixture = ClearanceFixture("30000/1001")
        self.addCleanup(fixture.close)
        result = inspect_presenter_caption_clearance(fixture.context, fixture.guard)
        self.assertEqual(result["binding"]["clock"]["frameRate"], "30000/1001")
        self.assertEqual(result["binding"]["presenterGraph"]["frameRate"], "30000/1001")
        cue = fixture.cue((120, 130), (440, 600, 460, 620))
        body = replace(fixture.context, coverage={"startFrame": 0, "endFrameExclusive": 960})
        with patch("guided_presenter_caption_clearance._captions", return_value=[cue]):
            self.assertEqual(inspect_presenter_caption_clearance(body, fixture.guard)["state"], "not-applicable")
        cue["startFrame"] = 119
        with patch("guided_presenter_caption_clearance._captions", return_value=[cue]):
            with self.assertRaisesRegex(RuntimeError, "clearance conflict"):
                inspect_presenter_caption_clearance(body, fixture.guard)

    def test_empty_graphic_not_applicable_does_not_bypass_subject_collision(self) -> None:
        """The old graphics screen's success never authorizes a presenter report."""
        old = screen_result(CaptionScreenContext(self.context.inputs, self.context.held, (), self.context.coverage),
                            [], self.fixture.guard)
        self.assertEqual(old["state"], "not-applicable")
        cue = self.fixture.cue((0, 15), (440, 600, 460, 620))
        with patch("guided_presenter_caption_clearance._captions", return_value=[cue]):
            with self.assertRaisesRegex(RuntimeError, "clearance conflict"):
                self.inspect()

    def test_changed_actual_shard_or_page_invalidates_prior_report(self) -> None:
        """Neither a page nor original shard can drift beneath serialized clearance."""
        report = self.inspect()
        for token in ("caption-shard-", "caption-page-"):
            row = next(row for row in self.context.held.files if token in row.path and row.path.endswith(".mov"))
            path, raw = Path(row.path), Path(row.path).read_bytes()
            path.write_bytes(raw + b"TEST drift")
            with self.assertRaises(RuntimeError):
                verify_presenter_caption_clearance(self.context, report, self.fixture.guard)
            path.write_bytes(raw)

    def test_late_cue_geometry_change_between_captures_rejects(self) -> None:
        """A final strong reread cannot silently adopt a newly changed safe box."""
        first = self.fixture.cue((30, 60), (50, 50, 70, 70))
        second = {**first, "box": (51, 50, 70, 70)}
        with patch("guided_presenter_caption_clearance._captions", side_effect=[[first], [second]]):
            with self.assertRaisesRegex(RuntimeError, "changed during inspection"):
                self.inspect()

    def test_original_window_and_runtime_mutations_reject(self) -> None:
        """Even still-valid replacements are not the original captured execution."""
        report = self.inspect()
        geometry = self.context.presenter.selected[0].geometry
        object.__setattr__(geometry.timing, "end_frame_exclusive", 119)
        with self.assertRaisesRegex(RuntimeError, "changed"):
            verify_presenter_caption_clearance(self.context, report, self.fixture.guard)
        object.__setattr__(geometry.timing, "end_frame_exclusive", 120)
        changed = replace(self.context.presenter.runtime, working_directory="/TEST/different")
        object.__setattr__(self.context.presenter, "runtime", changed)
        with self.assertRaisesRegex(RuntimeError, "runtime/guard/deadline changed"):
            self.inspect()

    def test_page_changed_after_final_caption_byte_read_cannot_return_clearance(self) -> None:
        """A later live-owner observation callback cannot bypass the final byte-read fence."""
        from opening_prefix_presenter import _observation_record
        path = Path(next(row.path for row in self.context.held.files
                         if "caption-page-" in row.path and row.path.endswith(".mov")))
        calls = 0

        def observe(row: object) -> dict:
            """Mutate exactly after the second capture's strong caption reader returned."""
            nonlocal calls
            calls += 1
            if calls == 2:
                path.write_bytes(path.read_bytes() + b"TEST late page change")
            return _observation_record(row)

        with patch("guided_presenter_caption_clearance._observation_record", side_effect=observe):
            with self.assertRaisesRegex(RuntimeError, "changed around their strong read"):
                self.inspect()

    def test_changed_source_or_tool_and_original_expiry_fail_without_decode(self) -> None:
        """Cheap original guard/deadline failures propagate and never start a child."""
        path = self.fixture.probe.path
        path.write_bytes(path.read_bytes() + b"TEST mutation")
        with patch("guided_presenter_observation.run_text") as run:
            with self.assertRaisesRegex(RuntimeError, "source/tool changed"):
                self.inspect()
        run.assert_not_called()
        self.fixture.probe.deadline.expired = True
        with self.assertRaisesRegex(RuntimeError, "original deadline expired"):
            self.inspect()

    def test_no_serialized_owner_partial_coverage_or_report_relabel(self) -> None:
        """Dataclass-shaped JSON and a safe subrange do not create execution authority."""
        report = self.inspect()
        contexts = (replace(self.context, presenter={"status": "complete"}),
                    replace(self.context, coverage={"startFrame": 30, "endFrameExclusive": 60}),
                    replace(self.context, coverage={"startFrame": False, "endFrameExclusive": 120}))
        for context in contexts:
            with self.assertRaises((RuntimeError, ValueError)):
                inspect_presenter_caption_clearance(context, self.fixture.guard)
        report["pictureProofBound"] = True
        with self.assertRaisesRegex(RuntimeError, "differs from original"):
            verify_presenter_caption_clearance(self.context, report, self.fixture.guard)

    def test_candidate_and_original_caption_binding_disagreement_rejects(self) -> None:
        """Rehashed candidate-only changes cannot replace the held caption plan."""
        inputs = copy.deepcopy(self.context.inputs)
        inputs.documents["candidatePlan"]["TEST_extra"] = "changed"
        inputs.documents["authority"]["candidatePlanHash"] = digest(inputs.documents["candidatePlan"])
        with self.assertRaisesRegex(RuntimeError, "actual candidate bytes"):
            inspect_presenter_caption_clearance(replace(self.context, inputs=inputs), self.fixture.guard)
        inputs = copy.deepcopy(self.context.inputs)
        inputs.value["executionInputHash"] = "f" * 64
        with self.assertRaisesRegex(RuntimeError, "original whole-program"):
            inspect_presenter_caption_clearance(replace(self.context, inputs=inputs), self.fixture.guard)

    def test_pair_workload_refuses_before_strong_caption_read(self) -> None:
        """The existing pair cap applies even to entirely future or empty coverage."""
        data = copy.deepcopy(self.context.held.data)
        data["shards"]["entries"] *= 4097
        context = replace(self.context, held=replace(self.context.held, data=data))
        with patch("guided_presenter_caption_clearance.held_cues") as read:
            with self.assertRaisesRegex(RuntimeError, "bounded cue/window pairs"):
                inspect_presenter_caption_clearance(context, self.fixture.guard)
        read.assert_not_called()
        self.assertEqual(_MAX_PAIRS, 32768)

    def test_pair_cap_applies_below_individual_cue_and_window_limits(self) -> None:
        """Legal individual counts cannot multiply into unbounded screening work."""
        selected = tuple(self.fixture.window((index * 32, index * 32 + 32), index) for index in range(16))
        owner = self.fixture.make_owner(selected)
        inputs = copy.deepcopy(self.context.inputs)
        inputs.documents["candidatePlan"]["presenterLayouts"] = [{"operationIndex": row.operation_index,
            "startFrame": row.geometry.timing.start_frame, "endFrameExclusive": row.geometry.timing.end_frame_exclusive,
            "layout": declaration_payload(row.geometry)} for row in selected]
        inputs.documents["authority"]["candidatePlanHash"] = digest(inputs.documents["candidatePlan"])
        data = copy.deepcopy(self.context.held.data)
        data["shards"]["entries"] = [data["shards"]["entries"][0]] * 2049
        context = replace(self.context, inputs=inputs, presenter=owner, held=replace(self.context.held, data=data))
        with patch("guided_presenter_caption_clearance.held_cues") as read:
            with self.assertRaisesRegex(RuntimeError, "bounded cue/window pairs"):
                inspect_presenter_caption_clearance(context, self.fixture.guard)
        read.assert_not_called()

    def test_inclusive_alpha_edges_become_half_open_and_malformed_bounds_reject(self) -> None:
        """Retain the shared actual-shard conversion, including exact frame coverage."""
        clock = {"width": 1080, "height": 1920, "totalFrames": 960}
        value = {"cueId": "TEST", "startFrame": 30, "endFrameExclusive": 60,
            "media": {"path": "/TEST/caption.mov", "sha256": "a" * 64},
            "shapedSafeBounds": {"minX": 10, "minY": 20, "maxX": 30, "maxY": 40, "framesMeasured": 30}}
        self.assertEqual(_cue(value, clock)["box"], (10, 20, 31, 41))
        for key, item in (("framesMeasured", 29), ("minX", True), ("maxY", float("nan"))):
            changed = copy.deepcopy(value)
            changed["shapedSafeBounds"][key] = item
            with self.assertRaises(ValueError):
                _cue(changed, clock)


if __name__ == "__main__":
    unittest.main()
