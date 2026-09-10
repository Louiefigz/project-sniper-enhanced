"""Actual template schedule parity and short-beat visible-completeness tests."""
from __future__ import annotations

import copy
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from graphics import template_visual_contract as visual
from graphics.comp_catalog_probe import probe_duration, probe_spec
from graphics.template_contract import declared_variables, entry_errors

ROOT = Path(__file__).resolve().parents[3]
SCOREBOARD = ROOT / "templates/motion/compositions/nateherk-scoreboard.html"
SPEC = {"eyebrow": "Every hour", "contextChips": "footage|viewer|guardrails",
        "heroValue": "1,000", "heroLabel": "hours of footage",
        "tiles": "survive~the tricks|lose~a viewer|guardrails~matter",
        "stripChips": "", "limitLabel": "LIMIT",
        "limitText": "Every hour of that can lose a viewer", "moduleLands": "", "exit": "hold"}


def entry(spec: dict, duration: float) -> dict:
    """One TEST-only card, not a creator plan or editorial approval."""
    return {"kind": "nateherk-scoreboard", "outStart": 0, "outEnd": duration, "spec": spec}


def actual_ramps(cases: list[dict]) -> list[float]:
    """Execute the actual template's module-build block with recording GSAP stubs."""
    script = r"""
const fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync(process.argv[1],'utf8');
const tokens=fs.readFileSync(process.argv[2],'utf8');
const cases=JSON.parse(fs.readFileSync(0,'utf8'));
const block=html.split('// ---- Narration-paced lands')[1].split('// exit:')[0];
const build=block.slice(block.indexOf('const modules'));
const constants=html.slice(html.indexOf('const CHIP_SWEEP_S'),html.indexOf('const STATES'));
const result=cases.map(vars=>{
 const ramps=[],context={window:{}};vm.runInNewContext(tokens,context);
 const M=context.window.__motionTokens;
 const parts=k=>String(vars[k]||'').split('|').filter(x=>x.trim()).map(()=>({}));
 const tl={fromTo(a,b,c,at){ramps.push(at+c.duration);}};
 Object.assign(context,{vars,M,ebText:vars.eyebrow||'',heroValue:vars.heroValue||'',
  limitText:vars.limitText||'',ctxEls:parts('contextChips'),tileEls:parts('tiles'),stripEls:parts('stripChips'),
  ebEl:{},ctxEl:{},heroRowEl:{},tilesEl:{},stripEl:{},limitEl:{},document:{getElementById:()=>({})},
  gsap:{timeline:()=>tl}});
 vm.runInNewContext(constants+build,context);return Math.max(...ramps);
});process.stdout.write(JSON.stringify(result));
"""
    result = subprocess.run(["node", "-e", script, str(SCOREBOARD), str(ROOT / "templates/motion/motion-tokens.js")],
                            input=json.dumps(cases), text=True, capture_output=True, check=True, timeout=10)
    return json.loads(result.stdout)


class ScoreboardTimingTests(unittest.TestCase):
    def test_actual_failed_ui_card_rejects_missing_late_modules(self) -> None:
        issues = visual.visual_entry_errors(entry(SPEC, 1.8018))
        self.assertTrue(any("4.35s" in issue and "last reveal 2.90s" in issue for issue in issues), issues)
        self.assertTrue(entry_errors(entry(SPEC, 1.8018)))
        self.assertEqual(visual.visual_entry_errors(entry(SPEC, 4.35)), [])

    def test_simple_number_keeps_a_fast_short_beat_without_dropping_copy(self) -> None:
        spec = {"heroValue": "1,000", "heroLabel": "hours", "moduleLands": "", "limitLabel": "LIMIT"}
        self.assertEqual(visual.visual_entry_errors(entry(spec, 1.8)), [])
        self.assertTrue(visual.visual_entry_errors(entry(spec, 1.6)))

    def test_actual_javascript_build_matches_defaults_custom_lands_and_fanout(self) -> None:
        cases = [SPEC, {"heroValue": "100"}, {"contextChips": "a|b|c|d"},
                 {**SPEC, "moduleLands": "0|0.5|1.2|3.5"},
                 {"tiles": "one~first|two~second|three~third"},
                 {"eyebrow": "TEST", "stripChips": "|".join(f"{i}~win" for i in range(13))},
                 {"limitText": "Only caveat"}]
        for spec, actual in zip(cases, actual_ramps(cases), strict=True):
            with self.subTest(spec=spec):
                reveal, settle, _ = visual.scoreboard_timing(spec)
                self.assertAlmostEqual(reveal + settle, actual)

    def test_exit_has_its_own_runway_after_readable_dwell(self) -> None:
        spec = {**SPEC, "exit": "blur-recede"}
        self.assertTrue(visual.visual_entry_errors(entry(spec, 4.35)))
        self.assertEqual(visual.visual_entry_errors(entry(spec, 4.5)), [])

    def test_bad_or_incomplete_schedules_fail_closed(self) -> None:
        for lands in ([0], [0, 1, 1, 2], [0, 1, 2, float("inf")], [False, 1, 2, 3],
                      "0|1|2|bad", "0|1|2|3tail", "-1|0|1|2", "3|2|1|0", "0|1|2|3_0e-3", "0|1|2|3e-٣"):
            with self.subTest(lands=lands):
                self.assertTrue(visual.visual_entry_errors(entry({**SPEC, "moduleLands": lands}, 10)))

    def test_missing_or_changed_source_timing_is_not_assumed_safe(self) -> None:
        with mock.patch.object(visual, "_scoreboard_tokens", side_effect=ValueError("changed source")):
            self.assertTrue(visual.visual_entry_errors(entry(SPEC, 10)))
        self.assertTrue(visual.visual_entry_errors(entry({}, 10)))

    def test_probe_and_test_authoring_use_the_same_required_hold(self) -> None:
        from _guided_longform_treatment import minimum_hold_s
        beat = {"shape": "scale", "trigger": "number", "minimumGraphicHoldS": 1.8}
        self.assertAlmostEqual(minimum_hold_s("nateherk-scoreboard", beat), 4.35)
        declared = declared_variables(SCOREBOARD.read_text())
        spec = probe_spec("nateherk-scoreboard", declared)
        self.assertEqual(visual.visual_entry_errors(entry(spec, probe_duration("nateherk-scoreboard", spec))), [])

    def test_validation_does_not_retime_or_remove_content(self) -> None:
        before = copy.deepcopy(SPEC)
        visual.visual_entry_errors(entry(SPEC, 1.8018))
        self.assertEqual(SPEC, before)


if __name__ == "__main__":
    unittest.main()
