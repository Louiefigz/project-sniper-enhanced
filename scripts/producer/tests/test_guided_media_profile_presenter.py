"""Property-presence fences for existing profiles; no media or source authority."""
from __future__ import annotations

import copy
import unittest

from guided_caption_profile import (CAPTION_PROFILE, CAPTION_SHORT_PROFILE,
                                    SCREENED_CAPTION_PROFILE, SCREENED_CAPTION_SHORT_PROFILE)
from guided_media_profile import (OPENING_PROFILE, SHORT_PROFILE, manual_short_plan,
                                  manual_caption_short_plan, profile_for_plan)
from guided_opening_frames import _profile


def candidate(short: bool, captioned: bool) -> dict:
    """Construct explicit TEST metadata, never real execution/approval evidence."""
    plan = {"target": {"mode": "short" if short else "longform", "width": 1080 if short else 1920,
                       "height": 1920 if short else 1080},
            "cutTrack": [{"sourceId": "TEST", "start": 0, "end": 2}], "captions": {"burn": captioned}}
    if short:
        plan["reframe"] = {"layout": "fill", "crop": [0, 0, 1, 1], "track": False}
    if captioned:
        plan["captionsTrack"] = {"schemaVersion": 1, "source": "kept-transcript",
                                 "defaultPolicy": "line", "groups": []}
    return plan


def cases() -> list[tuple[dict, str, str]]:
    """Keep all six existing profile tokens and their exact fresh/held relation."""
    return [(candidate(False, False), OPENING_PROFILE, OPENING_PROFILE),
            (candidate(True, False), SHORT_PROFILE, SHORT_PROFILE),
            (candidate(False, True), CAPTION_PROFILE, SCREENED_CAPTION_PROFILE),
            (candidate(False, True), SCREENED_CAPTION_PROFILE, SCREENED_CAPTION_PROFILE),
            (candidate(True, True), CAPTION_SHORT_PROFILE, SCREENED_CAPTION_SHORT_PROFILE),
            (candidate(True, True), SCREENED_CAPTION_SHORT_PROFILE, SCREENED_CAPTION_SHORT_PROFILE)]


class ExistingProfilePresenterFenceTests(unittest.TestCase):
    """No new field may silently select a profile that cannot execute its intent."""

    def test_absent_field_keeps_old_fresh_and_explicit_held_profiles(self) -> None:
        """Historical plans with no new property retain unchanged selection."""
        for plan, held, fresh in cases():
            before = copy.deepcopy(plan)
            self.assertEqual(profile_for_plan(plan), fresh)
            self.assertEqual(profile_for_plan(plan, held), held)
            _profile(plan, held)
            self.assertEqual(plan, before)

    def test_present_field_rejects_before_selecting_any_old_profile(self) -> None:
        """Null, empty and false are still declarations the old executor cannot own."""
        rows = [(dict(plan, presenterLayouts=value), held) for plan, held, _fresh in cases()
                for value in (None, [], False, {}, 0, "", [{"assetId": "TEST"}])]
        for plan, held in rows:
            before = copy.deepcopy(plan)
            with self.assertRaisesRegex(RuntimeError, "presenterLayouts"):
                profile_for_plan(plan)
            with self.assertRaisesRegex(RuntimeError, "presenterLayouts"):
                profile_for_plan(plan, held)
            self.assertEqual(plan, before)

    def test_explicit_held_frame_profile_does_not_bypass_selector_fence(self) -> None:
        """Direct frame/body readback checks cannot rely only on fresh selection."""
        rows = [(dict(plan, presenterLayouts=value), held) for plan, held, _fresh in cases()
                for value in (None, [], False, {}, 0, "", [{"assetId": "TEST"}])]
        for plan, held in rows:
            before = copy.deepcopy(plan)
            with self.assertRaisesRegex(RuntimeError, "no presenterLayouts execution owner"):
                _profile(plan, held)
            self.assertEqual(plan, before)

    def test_manual_geometry_validators_reject_empty_presenter_field(self) -> None:
        """Direct geometry calls must retain the unsupported field rather than erase it."""
        for value in (None, [], False):
            with self.assertRaisesRegex(RuntimeError, "presenterLayouts"):
                manual_short_plan(dict(candidate(True, False), presenterLayouts=value))
            with self.assertRaisesRegex(RuntimeError, "presenterLayouts"):
                manual_caption_short_plan(dict(candidate(True, True), presenterLayouts=value))


if __name__ == "__main__":
    unittest.main()
