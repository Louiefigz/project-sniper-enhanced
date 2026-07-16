"""hook_contract tests — the hard, content-derived, scope-aware intro contract."""
import unittest

from _common import *  # noqa: F401,F403
import hook_contract as hc
import plan_lint


def _w(text: str, t: float) -> dict:
    return {"word": text, "punctuated_word": text, "start": float(t), "end": float(t) + 0.4}


# Hook naming two tools (ChatGPT/Claude), a "decade" credibility claim, and a product.
_SENT = ("I tested ChatGPT and Claude for this . I have spent a decade building "
         "content systems . The angle generator workbook changes everything .").split()
HOOK_WORDS = [_w(w, i * 0.5) for i, w in enumerate(_SENT)]


def _target(scope: str = "full", lanes: dict | None = None) -> dict:
    t = {"mode": "longform", "scope": scope}
    if lanes:
        t["lanes"] = lanes
    return t


def _check(plan: dict, target: dict) -> plan_lint.Report:
    rep = plan_lint.Report()
    hc.check_hook_contract(plan, HOOK_WORDS, target, rep)
    return rep


COVERED_PLAN = {
    "graphicsTrack": [
        {"outStart": 0.8, "outEnd": 3.0},   # chips over ChatGPT@1.0 + Claude@2.0
        {"outStart": 3.5, "outEnd": 6.0},   # credibility card over the decade beat@4.0
    ],
    "punchIns": [{"role": "emphasis", "outStart": 1.0, "outEnd": 1.8, "zoom": 1.15}],
    "captions": {"burn": True},
    "transitions": [{"kind": "white-flash", "outTime": 1.0}],
}


class FullScopeEnforcesTests(unittest.TestCase):
    def test_empty_plan_fails_visual_obligations(self) -> None:
        rep = _check({"captions": {}}, _target("full"))
        errs = " ".join(rep.errors)
        self.assertIn("ChatGPT", errs)          # a named tool owes a graphic
        self.assertIn("credibility", errs)      # the decade claim owes a PIP/card
        self.assertIn("importance-push", errs)  # the strong beat owes a push
        # captions are SHORTS-ONLY, and this is longform, so they never fail here
        # (see the short-mode caption tests for the words-on-screen obligation).
        self.assertNotIn("caption", errs.lower())

    def test_fully_covered_plan_passes(self) -> None:
        rep = _check(COVERED_PLAN, _target("full"))
        self.assertEqual(rep.errors, [], rep.errors)

    def test_missing_only_the_push_is_caught(self) -> None:
        plan = dict(COVERED_PLAN, punchIns=[{"role": "aliveness", "outStart": 1.0,
                                             "outEnd": 30.0, "zoom": 1.01}])
        rep = _check(plan, _target("full"))
        self.assertTrue(any("importance-push" in e for e in rep.errors), rep.errors)
        self.assertFalse(any("ChatGPT" in e for e in rep.errors), rep.errors)

    def test_generic_category_owes_no_graphic(self) -> None:
        # "AI" is a generic category (R12), not a named tool — it must NOT be
        # required to carry a graphic even in full scope with no graphics at all.
        words = [_w("I", 0.5), _w("love", 1.0), _w("AI", 1.5), _w("tools", 2.0)]
        rep = plan_lint.Report()
        hc.check_hook_contract({"captions": {"burn": True}}, words,
                               {"mode": "longform", "scope": "full"}, rep)
        self.assertFalse(any("AI" in e and "graphic" in e for e in rep.errors), rep.errors)

    def test_operator_broll_can_cover_an_entity(self) -> None:
        plan = dict(COVERED_PLAN)
        plan["graphicsTrack"] = [{"outStart": 3.5, "outEnd": 6.0}]  # only credibility
        plan["brollTrack"] = [{"outStart": 0.5, "outEnd": 2.5}]     # b-roll over the tools
        rep = _check(plan, _target("full"))
        self.assertFalse(any("ChatGPT" in e or "Claude" in e for e in rep.errors), rep.errors)


class ScopeAndDirectiveGatingTests(unittest.TestCase):
    def test_trim_scope_enforces_nothing(self) -> None:
        rep = _check({"captions": {}}, _target("trim"))
        self.assertEqual(rep.errors, [], rep.errors)

    def test_light_scope_drops_the_produced_stack(self) -> None:
        # "light" turns off graphics/credibility/pushes — none of the produced
        # obligations may fire (captions here are the longform sidecar).
        rep = _check({"captions": {}}, _target("light"))
        errs = " ".join(rep.errors)
        self.assertEqual(rep.errors, [], errs)

    def test_captions_flagged_when_genuinely_absent(self) -> None:
        # A short with every other lane waived: only the caption obligation is live.
        # A short defaults to burn=True, so genuine absence means explicit burn:False
        # (and a short has no SRT sidecar), which MUST fail.
        target = {"mode": "short", "scope": "full",
                  "lanes": {"graphics": "off", "credibility": "off",
                            "motion": "off", "transitions": "off"}}
        short_words = [_w("ChatGPT", 0.5), _w("changed", 1.2), _w("everything", 2.0)]
        rep = plan_lint.Report()
        hc.check_hook_contract({"captions": {"burn": False}}, short_words, target, rep)
        self.assertTrue(any("captions" in e for e in rep.errors), rep.errors)

    def test_longform_never_requires_captions(self) -> None:
        # Long-form has NO on-screen captions — the obligation must not fire even
        # with the captions lane fully active and nothing authored.
        target = {"mode": "longform", "scope": "full",
                  "lanes": {"graphics": "off", "credibility": "off",
                            "motion": "off", "transitions": "off"}}
        rep = plan_lint.Report()
        hc.check_hook_contract({"captions": {"burn": False}}, HOOK_WORDS, target, rep)
        self.assertFalse(any("caption" in e.lower() for e in rep.errors), rep.errors)

    def test_shorts_default_burn_satisfies_captions(self) -> None:
        # A short omitting captions.burn still renders captions (mode default True),
        # so the contract must NOT spuriously fail it (fixes the plan_lint/contract
        # caption disagreement).
        target = {"mode": "short", "scope": "full",
                  "lanes": {"graphics": "off", "credibility": "off",
                            "motion": "off", "transitions": "off"}}
        rep = plan_lint.Report()
        hc.check_hook_contract({}, [_w("hi", 0.5)], target, rep)
        self.assertFalse(any("captions" in e for e in rep.errors), rep.errors)

    def test_waiving_graphics_drops_entity_obligation(self) -> None:
        rep = _check({"captions": {"burn": True}, "punchIns": COVERED_PLAN["punchIns"],
                      "graphicsTrack": [{"outStart": 3.5, "outEnd": 6.0}]},
                     _target("full", {"graphics": "off"}))
        self.assertFalse(any("ChatGPT" in e for e in rep.errors), rep.errors)

    def test_waiving_credibility_drops_that_obligation(self) -> None:
        plan = dict(COVERED_PLAN)
        plan["graphicsTrack"] = [{"outStart": 0.8, "outEnd": 3.0}]  # tools only, no cred card
        rep = _check(plan, _target("full", {"credibility": "off"}))
        self.assertFalse(any("credibility" in e for e in rep.errors), rep.errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class HookOpensDressedTests(unittest.TestCase):
    """PRO_INTRO_ENVELOPE: a produced longform hook must not open bare."""

    def test_late_first_graphic_fails(self) -> None:
        plan = dict(COVERED_PLAN)
        plan["graphicsTrack"] = [{"outStart": 6.0, "outEnd": 9.0}]
        rep = _check(plan, _target("full"))
        self.assertTrue(any("no graphic/overlay opens by" in e for e in rep.errors),
                        rep.errors)

    def test_early_overlay_passes_the_open(self) -> None:
        rep = _check(COVERED_PLAN, _target("full"))   # first graphic at 0.8s
        self.assertFalse([e for e in rep.errors if "opens by" in e], rep.errors)

    def test_graphics_waived_scope_skips(self) -> None:
        plan = dict(COVERED_PLAN, graphicsTrack=[])
        rep = _check(plan, _target("full", {"graphics": "off"}))
        self.assertFalse([e for e in rep.errors if "opens by" in e], rep.errors)
