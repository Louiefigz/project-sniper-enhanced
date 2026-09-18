"""Fail-closed produced-longform intro retention regression tests."""
import copy
import unittest

from _common import *  # noqa: F401,F403
import hook_contract as hook
import plan_lint


def _word(text: str, start: float) -> dict:
    return {"word": text, "punctuated_word": text,
            "start": start, "end": start + 0.35}


def _failed_44s_plan() -> dict:
    """The observed failure shape: 29% dressed, no transition, 15.8s quiet."""
    return {
        "target": {"mode": "longform", "scope": "full", "excerpt": True},
        "cutTrack": [
            {"sourceId": "raw-1", "start": 0.0, "end": 5.0, "speed": 1.0},
            {"sourceId": "raw-1", "start": 6.0, "end": 13.0, "speed": 1.0},
            {"sourceId": "raw-1", "start": 14.0, "end": 30.43, "speed": 1.0},
            {"sourceId": "raw-1", "start": 31.0, "end": 46.8, "speed": 1.0},
        ],
        "graphicsTrack": [
            {"outStart": 0.44, "outEnd": 3.71},
            {"outStart": 8.0, "outEnd": 11.7},
            {"outStart": 25.2, "outEnd": 31.2},
        ],
        "punchIns": [
            {"role": "emphasis", "outStart": t, "outEnd": t + 0.8}
            for t in (3.0, 15.0, 19.0, 23.0)
        ],
        "transitions": [],
    }


class FailedIntroRegressionTests(unittest.TestCase):
    def test_observed_44s_draft_fails_all_three_retention_walls(self) -> None:
        plan = _failed_44s_plan()
        rep = plan_lint.Report()
        plm.check_pacing(plan, 44.23, "longform", rep)
        hook.check_hook_contract(
            plan, [_word("This", 0.2), _word("works", 0.7)], plan["target"], rep)
        findings = "\n".join(rep.errors)
        self.assertIn("29% of the first 44s", findings)
        self.assertIn("NO visual change [28-44s]", findings)
        self.assertIn("evidence-backed clean-hook decision", findings)

    def test_light_scope_is_an_explicit_minimal_escape(self) -> None:
        plan = _failed_44s_plan()
        plan["target"]["scope"] = "light"
        rep = plan_lint.Report()
        plm.check_pacing(plan, 44.23, "longform", rep)
        self.assertFalse([e for e in rep.errors if "non-head visuals" in e],
                         rep.errors)

    def test_operator_off_visual_lanes_escape_nonhead_wall(self) -> None:
        plan = _failed_44s_plan()
        plan["target"]["lanes"] = {"graphics": "off", "broll": "operator"}
        rep = plan_lint.Report()
        plm.check_pacing(plan, 44.23, "longform", rep)
        self.assertFalse([e for e in rep.errors if "non-head visuals" in e],
                         rep.errors)

    def test_clean_hook_receipt_must_cover_every_seam(self) -> None:
        plan = _failed_44s_plan()
        plan["transitionRationale"] = {
            "decision": "clean-hook",
            "reason": "Continuous delivery makes each hard cut more legible.",
            "seams": [
                {"outTime": t, "evidence": "Continuous sentence delivery"}
                for t in (5.0, 12.0, 28.43)
            ],
        }
        rep = plan_lint.Report()
        hook.check_hook_contract(
            plan, [_word("This", 0.2), _word("works", 0.7)], plan["target"], rep)
        self.assertFalse([e for e in rep.errors if "clean-hook" in e], rep.errors)

        missing = copy.deepcopy(plan)
        missing["transitionRationale"]["seams"].pop()
        rep = plan_lint.Report()
        hook.check_hook_contract(
            missing, [_word("This", 0.2)], missing["target"], rep)
        self.assertTrue([e for e in rep.errors if "clean-hook" in e], rep.errors)

    def test_mixed_transition_and_clean_hook_decide_every_seam(self) -> None:
        plan = _failed_44s_plan()
        plan["transitions"] = [{"outTime": 5.0, "kind": "panel-sweep"}]
        plan["transitionRationale"] = {
            "decision": "clean-hook",
            "reason": "The remaining sentence continuations read as direct cuts.",
            "seams": [
                {"outTime": time, "evidence": "Continuous sentence delivery"}
                for time in (12.0, 28.43)
            ],
        }
        rep = plan_lint.Report()
        hook.check_hook_contract(
            plan, [_word("This", 0.2), _word("works", 0.7)], plan["target"], rep)
        self.assertFalse([e for e in rep.errors if "clean-hook" in e], rep.errors)


class RetentionWindowTests(unittest.TestCase):
    def test_explicit_excerpt_uses_60s_hook_and_splits_boundary_gap(self) -> None:
        plan = {
            "target": {"mode": "longform", "scope": "full", "excerpt": True},
            "cutTrack": [{"sourceId": "raw-1", "start": 0, "end": 75,
                          "speed": 1}],
            "graphicsTrack": [{"outStart": float(t)}
                              for t in list(range(2, 51, 3)) + [65]],
        }
        report = pac.pacing_report(plan, 75.0, "longform")
        self.assertEqual(report["hook_window"], 60.0)
        self.assertIn((50.0, 60.0), report["gaps"])

    def test_produced_intro_activity_wall_extends_through_three_minutes(self) -> None:
        plan = {
            "target": {"mode": "longform", "scope": "produced"},
            "cutTrack": [{"sourceId": "raw-1", "start": 0, "end": 180,
                          "speed": 1}],
            "graphicsTrack": [{"outStart": float(t), "outEnd": float(t) + 2}
                              for t in list(range(2, 61, 3)) + list(range(90, 180, 3))],
        }
        rep = plan_lint.Report()
        plm.check_pacing(plan, 180.0, "longform", rep)
        self.assertTrue([e for e in rep.errors
                         if "produced intro has no perceived visual change" in e],
                        rep.errors)

    def test_visual_state_zone_boundaries_count_as_retention_events(self) -> None:
        plan = {
            "cutTrack": [{"sourceId": "raw-1", "start": 0, "end": 12,
                          "speed": 1}],
            "treatmentMap": [{"outStart": t, "outEnd": t + 3,
                              "visualState": "talking-head"}
                             for t in (0.0, 3.0, 6.0, 9.0)],
        }
        self.assertEqual(pac.active_retention_gaps(plan, 12.0, 4.0), [])

    def test_screen_share_zone_is_continuously_active(self) -> None:
        plan = {
            "cutTrack": [{"sourceId": "raw-1", "start": 0, "end": 20,
                          "speed": 1}],
            "treatmentMap": [{"outStart": 0.0, "outEnd": 20.0,
                              "visualState": "screen-share"}],
        }
        self.assertEqual(pac.active_retention_gaps(plan, 20.0, 4.0), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
