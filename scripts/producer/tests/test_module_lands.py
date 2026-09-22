"""Narration-paced module builds (MODULE_STUDY §5 item 4).

The fill seam: brain picks WHICH kept words, ``graphics_copy.fill_module_lands``
converts to comp-relative ``spec.moduleLands``; ``plan_lint_motion`` validates
lands (strictly increasing, >= MOTION["module_lands"]["min_spacing_s"] apart,
inside the hold). Both halves are exercised here.
"""
import unittest

from _common import *  # noqa: F401,F403
from producer_config import MOTION
from graphics.template_visual_contract import module_land_variables
from plan_lint_visual import check_first_land


def _w(t: float) -> dict:
    return {"word": "x", "start": float(t), "end": float(t) + 0.3}


# Kept words in OUTPUT time (the output_words shape) — narration beats at
# 10.0 / 10.8 / 12.0 / 12.1s.
WORDS_OUT = [_w(10.0), _w(10.8), _w(12.0), _w(12.1)]
MODULE_SPEC = {
    "headlineLines": "Transcript|Proof",
    "axisLabel": "CUTS",
    "bars": "1~92~92",
    "verdict": "VERIFIED",
    "spectrum": "START|END",
}
ENTRY = {"outStart": 10.0, "outEnd": 16.0,
         "kind": "module-bullet-bars", "anchor": "free-band",
         "reason": "x", "spec": MODULE_SPEC}


class FillModuleLandsTests(unittest.TestCase):
    def test_picked_words_become_comp_relative_lands(self) -> None:
        out = gcopy.fill_module_lands(ENTRY, [0, 1, 2], WORDS_OUT)
        self.assertIsNotNone(out)
        self.assertEqual(out["spec"]["moduleLands"], [0.0, 0.8, 2.0])
        # existing spec copy is preserved, input entry untouched (pure seam)
        self.assertEqual(out["spec"]["bars"], "1~92~92")
        self.assertNotIn("moduleLands", ENTRY["spec"])

    def test_out_of_range_index_returns_none(self) -> None:
        self.assertIsNone(gcopy.fill_module_lands(ENTRY, [0, 9], WORDS_OUT))
        self.assertIsNone(gcopy.fill_module_lands(ENTRY, [0, -1], WORDS_OUT))
        self.assertIsNone(gcopy.fill_module_lands(ENTRY, [0, True], WORDS_OUT))

    def test_land_outside_hold_returns_none(self) -> None:
        # word at 12.0 is 8.0s into a 4.0s hold — off the card, no fallback
        entry = dict(ENTRY, outStart=4.0, outEnd=8.0)
        self.assertIsNone(gcopy.fill_module_lands(entry, [2], WORDS_OUT))

    def test_stacked_picks_return_none(self) -> None:
        # 12.0 → 12.1 is 0.1s apart — under the 0.25s lint floor
        self.assertIsNone(gcopy.fill_module_lands(ENTRY, [2, 3], WORDS_OUT))
        # non-increasing picks likewise
        self.assertIsNone(gcopy.fill_module_lands(ENTRY, [1, 0], WORDS_OUT))

    def test_empty_picks_and_bad_entry_return_none(self) -> None:
        self.assertIsNone(gcopy.fill_module_lands(ENTRY, [], WORDS_OUT))
        self.assertIsNone(gcopy.fill_module_lands({"outStart": 5.0}, [0], WORDS_OUT))

    def test_fill_output_passes_its_own_lint(self) -> None:
        out = gcopy.fill_module_lands(ENTRY, [0, 1, 2], WORDS_OUT)
        rep = pl.Report()
        plm._check_module_lands("t", out, 6.0, rep)
        self.assertEqual(rep.errors, [], rep.errors)


class ModuleLandsLintTests(unittest.TestCase):
    """plan_lint end-to-end: the moduleLands rules fire through lint()."""

    def _plan(self, lands) -> dict:
        plan = good_plan()
        plan["graphicsTrack"] = [
            {"outStart": 5.0, "outEnd": 9.0,
             "kind": "module-bullet-bars",
             "anchor": "free-band", "reason": "x",
             "spec": {**MODULE_SPEC, "moduleLands": lands}}]
        return plan

    def _errors(self, plan) -> list[str]:
        return [e for e in pl.lint(plan, MANIFEST).errors if "moduleLands" in e]

    def test_valid_lands_pass(self) -> None:
        self.assertEqual(self._errors(self._plan([0.0, 0.8, 2.0, 3.9])), [])

    def test_declared_string_schedules_keep_all_lint_constraints(self) -> None:
        for lands in ("0|0.8|2|3.9", "0, .8, 2e0, 3.9"):
            self.assertEqual(self._errors(self._plan(lands)), [])
        for lands in ("0|5", "0|0.1", "2|1", "0|NaN", "0|1tail", "0|1|", "0|1_0"):
            with self.subTest(lands=lands):
                self.assertTrue(self._errors(self._plan(lands)))

    def test_string_schedule_cannot_hide_empty_chrome(self) -> None:
        for lands in ([2, 3], "2|3", "2,3"):
            plan = self._plan(lands)
            plan["graphicsTrack"][0]["anchor"] = "own-screen"
            report = pl.Report()
            check_first_land(plan, report)
            self.assertTrue(any("empty chrome" in error for error in report.errors))

    def test_array_transport_is_lossless_and_does_not_mutate_authored_input(self) -> None:
        spec = {"moduleLands": [0, 0.8, 2.441234567890123], "label": "Unchanged"}
        variables = module_land_variables(spec, {"moduleLands": {"type": "string"}})
        self.assertEqual([float(value) for value in variables["moduleLands"].split("|")],
                         spec["moduleLands"])
        self.assertEqual(variables["label"], spec["label"])
        self.assertIsInstance(spec["moduleLands"], list)
        with self.assertRaises(ValueError):
            module_land_variables({"moduleLands": [False, 1]}, {"moduleLands": {"type": "string"}})

    def test_absent_key_is_additive_no_checks(self) -> None:
        plan = self._plan([0.0])
        del plan["graphicsTrack"][0]["spec"]["moduleLands"]
        self.assertEqual(self._errors(plan), [])

    def test_land_outside_hold_fires(self) -> None:
        errs = self._errors(self._plan([0.0, 5.0]))       # hold is 4.0s
        self.assertTrue(any("outside the hold" in e for e in errs), errs)

    def test_spacing_floor_fires(self) -> None:
        gap = MOTION["module_lands"]["min_spacing_s"]
        errs = self._errors(self._plan([1.0, 1.0 + gap / 2]))
        self.assertTrue(any("apart" in e for e in errs), errs)

    def test_non_increasing_fires(self) -> None:
        errs = self._errors(self._plan([2.0, 1.0]))
        self.assertTrue(any("strictly increasing" in e for e in errs), errs)

    def test_non_finite_and_non_list_fire(self) -> None:
        self.assertTrue(self._errors(self._plan(["x"])))
        self.assertTrue(self._errors(self._plan([float("nan")])))
        self.assertTrue(self._errors(self._plan("nope")))
        self.assertTrue(self._errors(self._plan([])))
        self.assertTrue(self._errors(self._plan([0, 10 ** 1000])))


if __name__ == "__main__":
    unittest.main(verbosity=2)
