"""Pure manual-short admission/version negatives; no media or approval claims."""
from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from cut_preview_io import digest
from guided_body_contract import parse_body_input, parse_current_body_input
from guided_media_profile import (OPENING_PROFILE, SHORT_PROFILE, SHORT_BODY_PROFILE,
                                  body_profile, manual_short_plan, profile_for_plan)
from guided_opening_frames import _profile, executable_frames, full_program_frames
from guided_opening_inputs import read_inputs, read_current_inputs
from plan_lint_reframe import check_reframe
from producer_config import MODES
from guided_short_geometry import _metadata, preflight_short_source
from test_guided_body_contract import body_input
from test_guided_body_frames import fixture, rebind


def short_inputs():
    """Metadata-only TEST packet; never a real admitted invocation."""
    inputs = fixture(0)
    inputs.value["profile"] = SHORT_PROFILE
    plan = inputs.documents["candidatePlan"]
    plan["target"].update(mode="short", width=1080, height=1920)
    plan.update(reframe={"layout": "fill", "crop": [0.25, 0, 0.5, 1], "track": False}, captions={"burn": False})
    inputs.documents["frameBindings"]["targetHash"] = digest(plan["target"])
    rebind(inputs)
    return inputs


class ManualShortProfileTests(unittest.TestCase):
    """Exactly authored crop; current metadata cannot unlock other finishing lanes."""

    def test_explicit_short_keeps_candidate_and_exact_frame_bindings(self) -> None:
        inputs = short_inputs()
        before = copy.deepcopy(inputs)
        self.assertEqual(profile_for_plan(inputs.documents["candidatePlan"]), SHORT_PROFILE)
        self.assertEqual(executable_frames(inputs), [])
        self.assertEqual(full_program_frames(inputs), [])
        self.assertEqual(inputs, before)
        self.assertEqual(body_profile(SHORT_PROFILE), SHORT_BODY_PROFILE)

    def test_historical_profile_does_not_gain_manual_geometry(self) -> None:
        plan = short_inputs().documents["candidatePlan"]
        with self.assertRaisesRegex(RuntimeError, "requested lanes"):
            _profile(plan, OPENING_PROFILE)
        inputs = short_inputs()
        inputs.value["profile"] = OPENING_PROFILE
        with self.assertRaises(RuntimeError):
            full_program_frames(inputs)

    def test_existing_short_lint_is_not_weakened_to_make_none_work(self) -> None:
        class Report:
            errors: list[str] = []
            def error(self, value: str) -> None:
                self.errors.append(value)
            def warn(self, value: str) -> None:
                pass
        report = Report()
        check_reframe({"target": {"mode": "short"}, "reframe": {"strategy": "none"}}, MODES["short"], report)
        self.assertTrue(any("9:16 reframe" in error for error in report.errors))
        report.errors = []
        check_reframe(short_inputs().documents["candidatePlan"], MODES["short"], report)
        self.assertEqual(report.errors, [])

    def test_crop_rejects_nonfinite_boolean_outside_tiny_and_unknown_geometry(self) -> None:
        for crop in ([True, 0, 0.5, 1], [float("nan"), 0, 0.5, 1], [0, 0, float("inf"), 1],
                     [-0.1, 0, 0.5, 1], [0.7, 0, 0.5, 1], [0, 0, 0.049, 1], [0, 0, 1]):
            plan = short_inputs().documents["candidatePlan"]
            plan["reframe"]["crop"] = crop
            with self.subTest(crop=crop), self.assertRaises(RuntimeError):
                manual_short_plan(plan)
        for extra in ({"strategy": "face"}, {"track": True}, {"continuousTracking": False}, {"layout": "split"}):
            plan = short_inputs().documents["candidatePlan"]
            plan["reframe"].update(extra)
            with self.subTest(extra=extra), self.assertRaises(RuntimeError):
                manual_short_plan(plan)

    def test_explicit_caption_off_and_one_source_are_not_defaults(self) -> None:
        for captions in (None, {}, {"burn": 0}, {"burn": None}, {"burn": True}):
            plan = short_inputs().documents["candidatePlan"]
            plan["captions"] = captions
            with self.subTest(captions=captions), self.assertRaises(RuntimeError):
                manual_short_plan(plan)
        plan = short_inputs().documents["candidatePlan"]
        plan["cutTrack"].append({"sourceId": "another", "start": 1, "end": 2})
        with self.assertRaisesRegex(RuntimeError, "one used source"):
            manual_short_plan(plan)

    def test_other_lanes_stay_blocked_without_candidate_mutation(self) -> None:
        for key, value in (("captionsTrack", [{}]), ("baselineLook", {"grade": "warm"}), ("punchIns", [{}]),
                           ("transitions", [{}]), ("audioEnhance", {"preset": "voice"}), ("audioGain", [{}]),
                           ("overlays", [{}]), ("presenter", {"animatedPip": True})):
            inputs = short_inputs()
            inputs.documents["candidatePlan"][key] = value
            before = copy.deepcopy(inputs.documents)
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                full_program_frames(inputs)
            self.assertEqual(inputs.documents, before)

    def test_body_parser_dispatch_is_distinct_and_historical_parser_stays_closed(self) -> None:
        value = body_input()
        value["profile"] = SHORT_BODY_PROFILE
        with self.assertRaisesRegex(RuntimeError, "profile"):
            parse_body_input(value)
        self.assertEqual(parse_current_body_input(value), value)
        with self.assertRaises(RuntimeError):
            parse_current_body_input({**value, "profile": "automatic"})

    def test_historical_input_parser_rejects_short_before_any_dependent_read(self) -> None:
        inputs = short_inputs()
        row = {"schemaVersion": 1, "kind": "guided-opening-media-input", "profile": SHORT_PROFILE,
            "executionId": "12345678-1234-4234-8234-123456789abc", "documents": {}, "pipeline": {}}
        row["executionInputHash"] = digest(row)
        with patch("guided_opening_inputs._json", return_value=(row, 1)), patch("guided_opening_inputs._documents") as documents:
            with self.assertRaisesRegex(RuntimeError, "unsupported"):
                read_inputs(inputs.path, inputs.sha256)
            documents.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, "document set"):
                read_current_inputs(inputs.path, inputs.sha256)

    def test_source_geometry_rejects_anamorphic_unknown_and_multiple_videos(self) -> None:
        row = {"width": 480, "height": 270, "r_frame_rate": "30000/1001", "avg_frame_rate": "30000/1001",
            "start_pts": 0, "sample_aspect_ratio": "1:1"}
        invalid = [[{**row, "sample_aspect_ratio": sar}] for sar in ("4:3", "0:1", None, "N/A")]
        invalid += [[row, row], [], [{**row, "avg_frame_rate": "30"}], [{**row, "start_pts": 1}],
            [{**row, "side_data_list": [{"rotation": 45}]}]]
        for streams in invalid:
            with self.subTest(streams=streams), patch("guided_short_geometry.run_audio", return_value=json.dumps({"streams": streams})):
                with self.assertRaises(RuntimeError):
                    _metadata("/TEST/source", "/TEST/ffprobe", "30000/1001")
        with patch("guided_short_geometry.run_audio", return_value=json.dumps({"streams": [row]})) as command:
            self.assertEqual(_metadata("/TEST/source", "/TEST/ffprobe", "30000/1001")["displayWidth"], 480)
            self.assertEqual(command.call_args.args[0][4], "v")
        row["side_data_list"] = [{"rotation": 90}]
        with patch("guided_short_geometry.run_audio", return_value=json.dumps({"streams": [row]})):
            self.assertEqual(_metadata("/TEST/source", "/TEST/ffprobe", "30000/1001")["displayWidth"], 270)

    def test_short_source_metadata_preflight_happens_before_ordinary_render(self) -> None:
        import guided_opening_prepare as prepare
        inputs = short_inputs()
        inputs.documents["manifest"] = {"sources": []}
        inputs.value["documents"] = {"manifest": {"path": "/TEST/manifest", "sha256": "f" * 64}}
        with patch.object(prepare, "validate_render_documents"), patch.object(prepare, "verify_execution_media_authority"), \
                patch.object(prepare, "preflight_short_source", side_effect=RuntimeError("TEST unsupported SAR")), \
                patch.object(prepare, "render") as render:
            with self.assertRaisesRegex(RuntimeError, "unsupported SAR"):
                prepare.prepare_full_program(inputs, inputs.path.parent)
            render.assert_not_called()
        historical = copy.deepcopy(inputs)
        historical.value["profile"] = OPENING_PROFILE
        with patch("guided_short_geometry.run_audio") as command:
            preflight_short_source(historical)
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
