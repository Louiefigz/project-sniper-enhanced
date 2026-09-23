"""Actual pipeline timeline parity; not native pixels or subjective reading approval."""
from __future__ import annotations

import copy
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from graphics import template_visual_contract as visual

ROOT = Path(__file__).resolve().parents[3]
SPEC = {"eyebrow": "THIS STAGE", "headlineLines": "The content system|is a folder",
        "explainer": "Ideas go in and nothing comes back", "nodes": "1~ideas|2~folder|3~silence",
        "footChip": "Nothing comes back", "exit": "hold"}


def entry(spec: dict, duration: float) -> dict:
    """One TEST card; never a creator plan or approval."""
    return {"kind": "module-pipeline", "outStart": 0, "outEnd": duration, "spec": spec}


def actual_ramp_ends(cases: list[dict]) -> list[float]:
    """Run the actual authored JS and actual motion tokens using a recording DOM."""
    script = """
import {readFileSync} from 'node:fs';
import {runPipelineScript} from './scripts/producer/tests/_pipeline_dom_fixture.mjs';
const source=readFileSync('./templates/motion/module-pipeline.js','utf8');
const cases=JSON.parse(readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(cases.map(spec=>Math.max(...runPipelineScript(source,spec)
  .trace.filter(row=>row[0]==='textRamp').map(row=>row[2]+row[3])))));
"""
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT,
                            input=json.dumps(cases), text=True, capture_output=True, check=True, timeout=10)
    return json.loads(result.stdout)


class PipelineTimingTests(unittest.TestCase):
    def test_actual_head_chain_foot_timelines_match_without_invented_staggers(self) -> None:
        """Compare actual ramp ends, not a duplicate assumed JS schedule."""
        cases = [SPEC, {"eyebrow": "Only eyebrow"}, {"headlineLines": "Only headline"},
                 {"explainer": "Only explainer"}, {"eyebrow": "Context", "explainer": "Explanation"},
                 {"footChip": "Only foot"}, {"headlineLines": "First|second"},
                 {"nodes": "1~one|2~two"}, {"nodes": "|".join(f"{i}~node" for i in range(8))},
                 {**SPEC, "moduleLands": "0|0.4|3.5"}, {**SPEC, "moduleLands": [1, 3, 5]},
                 {"footChip": "Decimal", "moduleLands": " +.1e+1 "}]
        for spec, actual in zip(cases, actual_ramp_ends(cases), strict=True):
            with self.subTest(spec=spec):
                reveal, settle, _ = visual.pipeline_timing(spec)
                self.assertAlmostEqual(reveal + settle, actual)

    def test_last_foot_must_land_and_remain_readable_before_cut(self) -> None:
        """The last requested module needs a real post-reveal dwell."""
        issues = visual.visual_entry_errors(entry(SPEC, 1.5))
        self.assertTrue(any("3.45s" in issue and "last reveal 2.00s" in issue for issue in issues), issues)
        self.assertEqual(visual.visual_entry_errors(entry(SPEC, 3.45)), [])
        self.assertTrue(visual.visual_entry_errors(entry(SPEC, 3.44)))

    def test_sparse_card_can_stay_fast_and_exit_needs_separate_runway(self) -> None:
        """Sparse fast beats need not inherit a dense card's minimum hold."""
        self.assertEqual(visual.visual_entry_errors(entry({"footChip": "One point"}, 1.65)), [])
        self.assertTrue(visual.visual_entry_errors(entry({**SPEC, "exit": "blur-recede"}, 3.45)))
        self.assertEqual(visual.visual_entry_errors(entry({**SPEC, "exit": "blur-recede"}, 3.6)), [])

    def test_malformed_or_ambiguous_module_times_never_get_a_default(self) -> None:
        """Reject partial, duplicate, nonfinite and host-only number syntax."""
        for lands in ([], [1], [0, 1, 1], [0, 1, float("inf")], [False, 1, 2],
                      "0|1|2tail", "-1|0|1", "3|2|1", "0|NaN|2", "0|1|",
                      "0|1|2_0e-3", "0|1|2e-٣"):
            with self.subTest(lands=lands):
                self.assertTrue(visual.visual_entry_errors(entry({**SPEC, "moduleLands": lands}, 20)))

    def test_missing_source_no_copy_or_blank_rows_cannot_undercount(self) -> None:
        """No guessed source timing, preview sample or silently omitted row."""
        for spec in ({}, {"nodes": "1~one||2~two"}, {"nodes": "1~one|2~"},
                     {"headlineLines": "one||two"}, {"headlineLines": "one|"}, {"nodes": "only"}):
            with self.subTest(spec=spec):
                self.assertTrue(visual.visual_entry_errors(entry(spec, 20)))
        with mock.patch.object(visual, "_timing_tokens", side_effect=ValueError("changed source")):
            self.assertTrue(visual.visual_entry_errors(entry(SPEC, 20)))

    def test_validator_neither_retimes_nor_trims_requested_content(self) -> None:
        """Validation reports defects without rewriting editorial intent."""
        before = copy.deepcopy(SPEC)
        visual.visual_entry_errors(entry(SPEC, 1.5))
        self.assertEqual(SPEC, before)

    def test_host_number_extensions_cannot_claim_earlier_than_actual_ramp(self) -> None:
        """Regression: Python accepts underscores/Unicode that JS parses only partly."""
        cases = [{"footChip": "TEST final fact", "moduleLands": value, "exit": "hold"}
                 for value in ("1_0e-3", "1e-٣")]
        for spec, actual in zip(cases, actual_ramp_ends(cases), strict=True):
            with self.subTest(spec=spec):
                self.assertAlmostEqual(actual, 1.2)
                self.assertTrue(visual.visual_entry_errors(entry(spec, 1.5)))


if __name__ == "__main__":
    unittest.main()
