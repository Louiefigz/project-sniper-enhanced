"""Strict caption profile/preset tests; no renderer, ASR or human decision."""
from __future__ import annotations

import copy
import unittest

from guided_caption_profile import (CAPTION_PROFILE, CAPTION_SHORT_PROFILE, caption_preset_plan,
    SCREENED_CAPTION_PROFILE, SCREENED_CAPTION_SHORT_PROFILE)
from guided_media_profile import OPENING_PROFILE, SHORT_PROFILE, body_profile, profile_for_plan
from guided_opening_frames import _profile
from test_guided_manual_short import short_inputs


def caption_plan(short: bool = False) -> dict:
    """Explicit TEST preset; no user intent or approval is manufactured."""
    plan = short_inputs().documents["candidatePlan"] if short else {
        "target": {"mode": "longform", "width": 1920, "height": 1080},
        "cutTrack": [{"sourceId": "TEST", "start": 0, "end": 2}]}
    return {**plan, "captions": {"burn": True}, "captionsTrack": {
        "schemaVersion": 1, "source": "kept-transcript", "defaultPolicy": "line", "groups": []}}


class CaptionProfileTests(unittest.TestCase):
    def test_actual_media_fixture_plan_passes_native_template_hold_and_ordinary_lint(self) -> None:
        """Preflight TEST data without launching a renderer or using source authority."""
        from _guided_caption_integration_fixture import plan_for_profile
        from guided_graphic_template import read_graphic_template
        from plan_lint import lint
        manifest = {"sources": [{"id": "TEST", "path": "/TEST/metadata-only.mp4", "duration": 4.1041}]}
        for short in (False, True):
            plan = plan_for_profile(short)
            self.assertEqual(lint(plan, manifest).errors, [])
            row = {"entry": plan["graphicsTrack"][0], "startFrame": 3, "endFrameExclusive": 77 if short else 78}
            template = read_graphic_template(row, "30000/1001")
            self.assertEqual(template.dimensions, (1080, 1920) if short else (1920, 1080))
            self.assertAlmostEqual(sum(cut["end"] - cut["start"] for cut in plan["cutTrack"]), 4.004)
            self.assertEqual(row["entry"]["outEnd"], plan["cutTrack"][0]["end"])
            self.assertTrue(all(any(cut["start"] <= start < end <= cut["end"] for cut in plan["cutTrack"])
                                for start, end in ((.2, .6), (.65, 1.1), (3.3001, 3.9001))))

    def test_explicit_presets_have_separate_profiles_and_preserve_plan(self) -> None:
        for short, profile in ((False, CAPTION_PROFILE), (True, CAPTION_SHORT_PROFILE)):
            for preset in ("line", "karaoke"):
                plan = caption_plan(short)
                plan["captionsTrack"]["defaultPolicy"] = preset
                before = copy.deepcopy(plan)
                self.assertEqual(profile_for_plan(plan), SCREENED_CAPTION_SHORT_PROFILE if short else SCREENED_CAPTION_PROFILE)
                self.assertEqual(profile_for_plan(plan, profile), profile)
                _profile(plan, profile)
                self.assertEqual(plan, before)
                self.assertIn("caption-pages", body_profile(profile))
                with self.assertRaises(RuntimeError):
                    _profile(plan, SHORT_PROFILE if short else OPENING_PROFILE)

    def test_custom_and_omitted_caption_authority_cannot_be_silently_normalized(self) -> None:
        for field, value in (("captionStyles", {}), ("captionCorrectionLedger", {}),
                             ("captionChapters", []), ("dialogueCaptionAuthority", {}), ("chapters", [{}])):
            plan = {**caption_plan(), field: value}
            with self.assertRaises(RuntimeError):
                caption_preset_plan(plan)
        for value in ({"defaultPolicy": "off"}, {"groups": [{}]}, {"transcriptCorrectionHash": "a" * 64},
                      {"schemaVersion": True}, {"source": "guessed-subtitles"}):
            plan = caption_plan()
            plan["captionsTrack"].update(value)
            with self.assertRaises((RuntimeError, ValueError)):
                caption_preset_plan(plan)

    def test_no_geometry_lanes_or_implicit_caption_burn_are_enabled(self) -> None:
        for patch in ({"captions": {}}, {"captions": {"burn": 1}}, {"captions": {"burn": True, "bandYOffsetPx": 2}},
                      {"target": {"mode": "longform", "width": 1280, "height": 720}},
                      {"reframe": {"strategy": "face"}}, {"transitions": [{}]}, {"audioGain": 2}):
            with self.assertRaises((RuntimeError, ValueError)):
                _profile({**caption_plan(), **patch}, CAPTION_PROFILE)


if __name__ == "__main__":
    unittest.main()
