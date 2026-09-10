"""Pure explicit-class controls; no live admission, render or QC completion."""
from __future__ import annotations

from copy import deepcopy
import unittest

import guided_presenter_profile as profiles
from _guided_proposal_presenter_fixture import values
from guided_media_profile import opening_profile, profile_for_plan, manual_short_plan
from opening_prefix_contract import PrefixClock


def fixture(short: bool = False, captioned: bool = False) -> tuple[dict, PrefixClock]:
    """Declare TEST geometry only, without manufacturing request or media proof."""
    _accepted, plan, _packet, _manifest = values()
    plan.pop("unrelated")
    plan["captions"] = {"burn": captioned}
    if captioned:
        plan["captionsTrack"] = {"schemaVersion": 1, "source": "kept-transcript",
                                 "defaultPolicy": "line", "groups": []}
    if short:
        plan["target"].update(mode="short", width=1080, height=1920)
        plan["reframe"] = {"layout": "fill", "crop": [0, 0, 1, 1], "track": False}
        for row in plan["cutTrack"]:
            row["sourceId"] = "raw-2"
        plan["presenterLayouts"][0]["layout"]["sourceIds"] = ["raw-2"]
    return plan, PrefixClock("30/1", 600, plan["target"]["width"], plan["target"]["height"])


class PresenterProfileTests(unittest.TestCase):
    """New metadata tokens must not silently activate old renderer owners."""

    def test_four_distinct_classes_keep_exact_pairing_and_inputs(self) -> None:
        rows = ((False, False, profiles.PRESENTER_PROFILE, profiles.PRESENTER_BODY_PROFILE),
                (True, False, profiles.PRESENTER_SHORT_PROFILE, profiles.PRESENTER_SHORT_BODY_PROFILE),
                (False, True, profiles.PRESENTER_CAPTION_PROFILE, profiles.PRESENTER_CAPTION_BODY_PROFILE),
                (True, True, profiles.PRESENTER_CAPTION_SHORT_PROFILE, profiles.PRESENTER_CAPTION_SHORT_BODY_PROFILE))
        for short, captioned, opening, body in rows:
            plan, clock = fixture(short, captioned)
            before = deepcopy(plan)
            with self.subTest(profile=opening):
                self.assertEqual(profiles.presenter_profile_for_plan(plan, clock), opening)
                self.assertEqual(profiles.presenter_opening_profile(opening), opening)
                self.assertEqual(profiles.presenter_body_profile(opening), body)
                self.assertEqual(profiles.presenter_caption_profile(opening), captioned)
                self.assertEqual(profiles.presenter_manual_profile(opening), short)
                self.assertEqual(plan, before)
                with self.assertRaises(RuntimeError):
                    opening_profile(opening)
                with self.assertRaises(RuntimeError):
                    profile_for_plan(plan)

    def test_missing_empty_or_noncanonical_layout_does_not_select_a_class(self) -> None:
        for layouts in (None, [], {}, False, [None]):
            plan, clock = fixture()
            plan["presenterLayouts"] = layouts
            with self.subTest(layouts=layouts), self.assertRaises((ValueError, RuntimeError)):
                profiles.presenter_profile_for_plan(plan, clock)
        plan, clock = fixture()
        del plan["presenterLayouts"]
        with self.assertRaises(ValueError):
            profiles.presenter_profile_for_plan(plan, clock)

    def test_burn_off_is_exact_boolean_and_track_cannot_be_null(self) -> None:
        for captions in (None, {}, {"burn": 0}, {"burn": True}, {"burn": False, "style": "x"}):
            plan, clock = fixture()
            plan["captions"] = captions
            with self.subTest(captions=captions), self.assertRaises(RuntimeError):
                profiles.presenter_profile_for_plan(plan, clock)
        for track in (None, [], {}):
            plan, clock = fixture()
            plan["captionsTrack"] = track
            with self.subTest(track=track), self.assertRaises(RuntimeError):
                profiles.presenter_profile_for_plan(plan, clock)

    def test_native_clock_and_no_extra_finishing_lane(self) -> None:
        mutations = (("presenter", None), ("overlays", []), ("punchIns", [{}]),
                     ("transitions", [{}]), ("audioGain", {"gain": 1}),
                     ("baselineLook", {"grade": "warm"}), ("reframe", {"strategy": "track"}),
                     ("persistentText", "hello"), ("faceBBoxNorm", [0, 0, 1, 1]), ("chapters", [{}]),
                     ("captionCorrectionLedger", None), ("captionStyles", {}), ("dialogueCaptionAuthority", None))
        for key, value in mutations:
            plan, clock = fixture()
            plan[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                profiles.presenter_profile_for_plan(plan, clock)
        plan, _clock = fixture()
        for clock in (PrefixClock("60/2", 600, 1920, 1080), PrefixClock("30/1", 600, 1280, 720),
                      PrefixClock("1/2", 600, 1920, 1080), PrefixClock("30/1", 72001, 1920, 1080),
                      PrefixClock("30", 600, 1920, 1080)):
            with self.subTest(clock=clock), self.assertRaises((ValueError, RuntimeError)):
                profiles.presenter_profile_for_plan(plan, clock)

    def test_changed_speed_boolean_lead_and_manual_sources_are_rejected(self) -> None:
        for key, value in (("speed", True), ("speed", 1.1), ("audioLeadMs", False), ("audioLeadMs", 1)):
            plan, clock = fixture()
            plan["cutTrack"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                profiles.presenter_profile_for_plan(plan, clock)
        plan, clock = fixture(True)
        plan["cutTrack"][1]["sourceId"] = "another"
        with self.assertRaisesRegex(RuntimeError, "one used source"):
            profiles.presenter_profile_for_plan(plan, clock)
        plan, _clock = fixture(True)
        with self.assertRaisesRegex(RuntimeError, "presenterLayouts"):
            manual_short_plan(plan)


class PresenterGraphMetadataTests(unittest.TestCase):
    """Full-program native cost and half-open coexistence are conservative gates."""

    def test_each_asset_occurrence_is_counted_at_original_native_size(self) -> None:
        clock = PrefixClock("30/1", 18000, 1920, 1080)
        result = profiles.presenter_graph_workload(clock, 1, True, ((1920, 1080),) * 2)
        self.assertEqual(result["captionPageBound"], 20)
        self.assertEqual(result["presenterOccurrences"], 2)
        self.assertEqual(result["fullGraphInputPixels"], 24 * 1920 * 1080)
        self.assertIs(result["productionPerformanceQualified"], False)

    def test_whole_body_cost_and_aggregate_boundary_cannot_drop_inputs(self) -> None:
        clock = PrefixClock("30/1", 600, 1920, 1080)
        profiles.presenter_graph_workload(clock, 30, False, ((1920, 1080),))
        with self.assertRaisesRegex(RuntimeError, "no requested inputs may be dropped"):
            profiles.presenter_graph_workload(clock, 31, False, ((1920, 1080),))
        profiles.presenter_graph_workload(clock, 10, True, ((1920, 1080),) * 2)
        with self.assertRaises(RuntimeError):
            profiles.presenter_graph_workload(PrefixClock("30/1", 18000, 1920, 1080), 10, True, ((1920, 1080),) * 2)

    def test_workload_rejects_boolean_and_missing_asset_inventory(self) -> None:
        clock = PrefixClock("30/1", 600, 1920, 1080)
        for count, captioned, canvases in ((True, False, ((2, 2),)), (0, 0, ((2, 2),)),
                                          (0, False, ()), (0, False, ((True, 2),)), (0, False, ((2, 2),) * 33)):
            with self.subTest(canvases=canvases), self.assertRaises(RuntimeError):
                profiles.presenter_graph_workload(clock, count, captioned, canvases)

    def test_future_body_overlap_is_rejected_but_exact_adjacency_is_allowed(self) -> None:
        window = [{"startFrame": 300, "endFrameExclusive": 570}]
        adjacent = [{"startFrame": 0, "endFrameExclusive": 300}, {"startFrame": 570, "endFrameExclusive": 600}]
        profiles.assert_presenter_graphics_disjoint(adjacent, window, 600)
        for start, end in ((299, 301), (569, 571), (400, 401)):
            with self.subTest(start=start), self.assertRaisesRegex(RuntimeError, "overlaps"):
                profiles.assert_presenter_graphics_disjoint([{"startFrame": start, "endFrameExclusive": end}], window, 600)

    def test_half_open_inventory_is_strict_and_bounded(self) -> None:
        window = [{"startFrame": 0, "endFrameExclusive": 30}]
        for row in ({"startFrame": False, "endFrameExclusive": 30}, {"startFrame": 1, "endFrameExclusive": 1},
                    {"startFrame": 30, "endFrameExclusive": 601}, None):
            with self.subTest(row=row), self.assertRaises(RuntimeError):
                profiles.assert_presenter_graphics_disjoint([row], window, 600)


if __name__ == "__main__":
    unittest.main()
