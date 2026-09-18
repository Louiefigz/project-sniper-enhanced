"""Real held TEST metadata and inert owner hooks; no media/render invocation."""
from __future__ import annotations

import copy
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _guided_caption_fixture import fixture, guard
from guided_caption_profile import (CAPTION_PROFILE, CAPTION_SHORT_PROFILE, SCREENED_CAPTION_PROFILE,
    SCREENED_CAPTION_SHORT_PROFILE, caption_screen_fields)
from guided_caption_projection import capture_caption_projection
from guided_caption_screen import (CaptionScreenContext, admit_screen, held_cues, require_screen,
    screen_context, screen_intent_preflight, screen_result, supported_layout)
from guided_caption_screen_read import verify_screen
from guided_media_profile import body_profile, profile_for_plan
from test_guided_caption_profile import caption_plan


def row(order: int = 2) -> dict:
    """An explicit TEST agenda occurrence, not an authored user proposal."""
    return {"graphicId": "TEST-agenda", "order": order, "startFrame": 30, "endFrameExclusive": 150,
        "entry": {"kind": "agenda-slide", "anchor": "own-screen", "spec": {"layout": "caption-safe-upper-v1"}}}


def admission_context(rows: list[dict]) -> CaptionScreenContext:
    """Stub-only admission context; never call the strong caption reader on this."""
    inputs = SimpleNamespace(value={"profile": SCREENED_CAPTION_PROFILE}, documents={"authority": {
        "frameRate": "30000/1001", "target": {"width": 1920, "height": 1080}}})
    return CaptionScreenContext(inputs, None, tuple(rows), {"startFrame": 0, "endFrameExclusive": 100})


class ScreeningAdmissionTests(unittest.TestCase):
    def test_fresh_and_held_profiles_are_distinct_and_never_coerced(self) -> None:
        for short, old, new in ((False, CAPTION_PROFILE, SCREENED_CAPTION_PROFILE),
                                (True, CAPTION_SHORT_PROFILE, SCREENED_CAPTION_SHORT_PROFILE)):
            plan = caption_plan(short)
            self.assertEqual(profile_for_plan(plan), new)
            self.assertEqual(profile_for_plan(plan, old), old)
            self.assertEqual(profile_for_plan(plan, new), new)
            self.assertEqual(caption_screen_fields(old), set())
            self.assertEqual(caption_screen_fields(body_profile(new)), {"captionLayoutScreen"})
            wrong = SCREENED_CAPTION_PROFILE if short else SCREENED_CAPTION_SHORT_PROFILE
            with self.assertRaises(RuntimeError):
                profile_for_plan(plan, wrong)
            for malformed in (None, True, {}, [], body_profile(new)):
                with self.assertRaises(RuntimeError):
                    profile_for_plan(plan, malformed)

    def test_unsupported_simultaneity_refuses_before_first_graphic_spawn(self) -> None:
        from guided_opening_graphics import render_opening_graphics
        value = row()
        value["entry"]["kind"] = "module-pipeline"
        value["entry"]["spec"]["layout"] = "full-canvas"
        context = admission_context([value])
        clock = SimpleNamespace(remaining=guard, phase=lambda _name, call: call())
        with patch("guided_caption_screen.held_cues", return_value=[{"startFrame": 40, "endFrameExclusive": 60}]), \
                patch("guided_opening_graphics.graphics_runtime", side_effect=AssertionError("must not spawn")):
            with self.assertRaisesRegex(RuntimeError, "unqualified"):
                render_opening_graphics(context.inputs, [value], (None, None, clock, None), context)

    def test_same_unsupported_kind_in_genuine_cue_gap_is_not_a_conflict(self) -> None:
        value = row()
        value["entry"]["kind"] = "unsupported-body-only"
        context = admission_context([value])
        with patch("guided_caption_screen.held_cues", return_value=[{"startFrame": 100, "endFrameExclusive": 150}]):
            self.assertEqual(admit_screen(context, guard), set())
        with patch("guided_caption_screen.held_cues", return_value=[{"startFrame": 99, "endFrameExclusive": 150}]):
            with self.assertRaises(RuntimeError):
                admit_screen(context, guard)

    def test_prebase_does_not_guess_speech_overlap_or_replace_graphic(self) -> None:
        value = row()
        value["entry"]["kind"] = "not-yet-observed"
        context = admission_context([value])
        before = copy.deepcopy(value)
        screen_intent_preflight(context.inputs, [value])
        self.assertEqual(value, before)
        value["entry"]["kind"] = "agenda-slide"
        context.inputs.documents["authority"]["target"] = {"width": 1080, "height": 1920}
        with self.assertRaisesRegex(RuntimeError, "class"):
            screen_intent_preflight(context.inputs, [value])

    def test_native_limits_are_exact_not_a_generic_template_capability(self) -> None:
        context, value = admission_context([]), row()
        authority = context.inputs.documents["authority"]
        self.assertTrue(supported_layout(value, authority))
        for field, item in (("kind", "other"), ("anchor", "left"), ("spec", {"layout": "full-canvas"})):
            changed = copy.deepcopy(value)
            changed["entry"][field] = item
            self.assertFalse(supported_layout(changed, authority))
        value["endFrameExclusive"] = value["startFrame"] + 1799
        self.assertFalse(supported_layout(value, authority))

    def test_legacy_never_accepts_serialized_observation_or_screen(self) -> None:
        self.assertIsNone(screen_context(SimpleNamespace(value={"profile": CAPTION_PROFILE}), None, False))
        self.assertIsNone(screen_result(None, [], guard))
        with self.assertRaises(RuntimeError):
            screen_result(None, [{"captionLayoutObservation": {}}], guard)
        with self.assertRaises(RuntimeError):
            verify_screen({"graphics": [], "captionLayoutScreen": {"state": "screened-no-overlap"}}, None, guard)
        for state in ("unqualified", "envelope-conflict"):
            with self.assertRaises(RuntimeError):
                require_screen({"state": state})


class HeldScreenMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-screen-TEST-")
        root = Path(self.temp.name).resolve()
        ctx, binding = fixture(root)
        self.held = capture_caption_projection(ctx, binding, guard)
        rate, frames, width, height = binding.frame_clock
        inputs = SimpleNamespace(value={"profile": SCREENED_CAPTION_SHORT_PROFILE,
            "executionInputHash": binding.execution_input_hash,
            "documents": {"candidatePlan": asdict(binding.plan), "manifest": asdict(binding.manifest)}},
            documents={"authority": {"frameRate": rate, "totalFrames": frames,
                "target": {"width": width, "height": height}, "review": {"endFrameExclusive": 120}}})
        self.context = CaptionScreenContext(inputs, self.held, (), {"startFrame": 0, "endFrameExclusive": 120})

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_real_held_cold_read_has_whole_later_cues_and_no_graphics(self) -> None:
        cues = held_cues(self.context, guard)
        self.assertTrue(any(row["startFrame"] >= 900 for row in cues))
        result = screen_result(self.context, [], guard)
        self.assertEqual(result["state"], "not-applicable")
        self.assertEqual(result["clock"]["totalFrames"], 960)
        self.assertEqual(result["graphics"], [])
        self.assertEqual(result["captionProjectionHash"], self.held.data_hash)
        verify_screen({"graphics": [], "captionLayoutScreen": result}, self.context, guard)
        result["coverage"]["endFrameExclusive"] -= 1
        with self.assertRaises(RuntimeError):
            verify_screen({"graphics": [], "captionLayoutScreen": result}, self.context, guard)

    def test_wrong_original_clock_and_parent_binding_reject(self) -> None:
        context = self.context
        for key, value in (("frameRate", "30/1"), ("totalFrames", 959)):
            inputs = copy.deepcopy(context.inputs)
            inputs.documents["authority"][key] = value
            with self.assertRaises(RuntimeError):
                held_cues(replace(context, inputs=inputs), guard)
        inputs = copy.deepcopy(context.inputs)
        inputs.value["documents"]["candidatePlan"]["sha256"] = "f" * 64
        with self.assertRaises(RuntimeError):
            held_cues(replace(context, inputs=inputs), guard)

    def test_actual_shard_mutation_cannot_reuse_serialized_not_applicable(self) -> None:
        result = screen_result(self.context, [], guard)
        path = next(Path(row.path) for row in self.held.files if row.path.endswith(".mov"))
        path.write_bytes(path.read_bytes() + b"TEST drift")
        with self.assertRaises(RuntimeError):
            verify_screen({"graphics": [], "captionLayoutScreen": result}, self.context, guard)
