"""Exact current receipt flags/geometry only; no released presenter execution or QC."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import unittest

from guided_caption_profile import caption_full_fields, caption_profile, caption_screen_fields, screened_caption_profile
from guided_media_profile import body_profile, opening_profile, profile_for_plan
from guided_presenter_profile import (
    PRESENTER_PROFILE, PRESENTER_SHORT_PROFILE, PRESENTER_CAPTION_PROFILE, PRESENTER_CAPTION_SHORT_PROFILE,
    presenter_body_profile,
)
from guided_short_geometry import _manual_intent
from test_guided_presenter_profile import fixture


class PresenterReceiptFieldTests(unittest.TestCase):
    """Distinct new tokens require exact retained caption/crop evidence, not old token upgrades."""

    def test_exact_new_caption_receipts_require_both_projection_and_graphic_screen(self) -> None:
        """Presenter clearance supplements the actual caption/graphic screen; it cannot replace it."""
        for profile in (PRESENTER_CAPTION_PROFILE, PRESENTER_CAPTION_SHORT_PROFILE):
            with self.subTest(profile=profile):
                self.assertTrue(caption_profile(profile))
                self.assertTrue(screened_caption_profile(profile))
                self.assertEqual(caption_full_fields(profile), {"captionProjection"})
                self.assertEqual(caption_screen_fields(profile), {"captionLayoutScreen"})
                self.assertEqual(caption_screen_fields(presenter_body_profile(profile)), {"captionLayoutScreen"})

    def test_uncaptioned_new_tokens_unknown_and_omission_do_not_acquire_caption_fields(self) -> None:
        """Truthiness cannot activate a caption workflow."""
        for profile in (PRESENTER_PROFILE, PRESENTER_SHORT_PROFILE, None, "TEST unknown", {}, []):
            with self.subTest(profile=profile):
                self.assertFalse(caption_profile(profile))
                self.assertFalse(screened_caption_profile(profile))
                self.assertEqual(caption_full_fields(profile), set())
                self.assertEqual(caption_screen_fields(profile), set())

    def test_new_caption_flags_do_not_expand_historical_public_selectors(self) -> None:
        """Metadata consumers may recognize fields while public legacy render routing remains closed."""
        for profile in (PRESENTER_CAPTION_PROFILE, PRESENTER_CAPTION_SHORT_PROFILE):
            with self.assertRaises(RuntimeError):
                opening_profile(profile)
            with self.assertRaises(RuntimeError):
                body_profile(profile)
        plan, _clock = fixture(True, True)
        with self.assertRaisesRegex(RuntimeError, "presenterLayouts"):
            profile_for_plan(plan)

    def test_manual_new_geometry_uses_original_plan_without_stripping_layouts(self) -> None:
        """Geometry is only the observed reframe intent, never source-color or subject approval."""
        for captioned, profile in ((False, PRESENTER_SHORT_PROFILE), (True, PRESENTER_CAPTION_SHORT_PROFILE)):
            plan, _clock = fixture(True, captioned)
            before = deepcopy(plan)
            inputs = SimpleNamespace(value={"profile": profile}, documents={"candidatePlan": plan})
            value = _manual_intent(inputs)
            self.assertEqual(value["reframe"], plan["reframe"])
            self.assertFalse(value["captionsBurned"])
            self.assertEqual(plan, before)
            plan["reframe"]["track"] = True
            with self.assertRaisesRegex(RuntimeError, "track:false"):
                _manual_intent(inputs)


if __name__ == "__main__":
    unittest.main()
