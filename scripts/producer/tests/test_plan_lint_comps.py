#!/usr/bin/env python3
"""plan_lint_comps tests — the measured comp-capability matrix lint.

One focused class per verdict path, all against SYNTHETIC matrix fixtures
(the real ``templates/motion/comp_capabilities.json`` is repo state and is
never read: ``_common`` points the default at a guaranteed-missing path):

* (a) overlay-anchor aspect mismatch FAILs naming the real canvas + the
  aspect-legal same-family siblings;
* (b) own-screen aspect mismatch FAILs at plan time (comp_measure's
  render-side predicate, answered from the matrix);
* (c) hold-to-cut comps must end on a cutTrack seam / the output end / carry
  ``exitOnCut``;
* (d) partial-fade WARNs with the measured terminal alpha;
* artifact availability/integrity paths live in
  ``test_comp_capability_artifact.py``;
* the plan_lint.lint() dispatch routes FAILs into errors.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403  (shared fixtures + sys.path setup)
from _common import MANIFEST, good_plan

import plan_lint as pl
import plan_lint_comps as plc
from graphics.comp_capability_artifact import (
    build_artifact,
    composition_kinds,
)

# Synthetic capability matrix: every fade class + both aspects + the
# degenerate rows (static-only, renderError, canvasNote ambiguity).
_COMPS = {
    "line-swap": {"canvas": [1080, 1920], "fadeClass": "fades-clean"},
    "count-up": {"canvas": [1080, 1920], "fadeClass": "hold-to-cut",
                  "terminalAlpha": {"maxAlpha8": 255, "meanAlpha8": 211.5}},
    "chart-story": {"canvas": [1920, 1080],
                           "fadeClass": "fades-clean"},
    "hw-callout-circle": {"canvas": [1080, 1920], "fadeClass": "partial-fade",
                   "terminalAlpha": {"maxAlpha8": 180, "meanAlpha8": 12.4}},
    "marker-highlight": {"canvas": [1080, 1920]},          # probe mid-run
    "ui-focus-zoom": {"canvas": [1080, 1920],
                  "renderError": "hyperframes died"},
    "hw-scribble-transition": {"canvas": [1080, 1920],
                         "canvasNote": "css root (1080, 1920) != declared "
                                       "data-width/height (1920, 1080)"},
}


def _write_matrix(dirpath: str, comps: dict = None) -> str:
    """Write a synthetic comp_capabilities.json; returns its path."""
    path = os.path.join(dirpath, "comp_capabilities.json")
    rows = {
        kind: {"canvas": [1080, 1920], "aspect": "9:16",
               "fadeClass": "fades-clean",
               "terminalAlpha": {"maxAlpha8": 0, "meanAlpha8": 0.0},
               "contentBBox": [0, 0, 1079, 1919]}
        for kind in composition_kinds()}
    for kind, override in (comps or _COMPS).items():
        row = dict(rows[kind])
        canvas = list(override.get("canvas", row["canvas"]))
        row.update(override)
        row["aspect"] = "9:16" if canvas[1] > canvas[0] else "16:9"
        if "fadeClass" not in override:
            row.pop("fadeClass", None)
            row.pop("terminalAlpha", None)
            row.pop("contentBBox", None)
        else:
            row.setdefault("terminalAlpha",
                           {"maxAlpha8": 0, "meanAlpha8": 0.0})
            row["contentBBox"] = [0, 0, canvas[0] - 1, canvas[1] - 1]
        rows[kind] = row
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(build_artifact(rows), handle)
    return path


def _plan(entries: list, mode: str = "short") -> dict:
    """Two-segment cutTrack (seam at output 10.0s, end 18.0s) + graphics."""
    return {
        "target": {"mode": mode},
        "cutTrack": [
            {"sourceId": "raw-1", "start": 0.0, "end": 10.0, "speed": 1.0},
            {"sourceId": "raw-1", "start": 12.0, "end": 20.0, "speed": 1.0},
        ],
        "graphicsTrack": entries,
    }


def _entry(**overrides) -> dict:
    entry = {"kind": "line-swap", "anchor": "free-band", "outStart": 8.0,
             "outEnd": 9.5, "spec": {}, "reason": "r"}
    entry.update(overrides)
    return entry


class _MatrixCase(unittest.TestCase):
    """Shared fixture: a temp matrix file + a verdict helper."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.matrix = _write_matrix(self._dir.name)

    def verdicts(self, plan: dict) -> list:
        return plc.matrix_verdicts(plan, matrix_path=self.matrix)


class OverlayAspectTests(_MatrixCase):
    """(a) overlay anchors: comp canvas aspect must match delivery aspect."""

    def test_wide_comp_under_free_band_in_short_fails(self) -> None:
        (v,) = self.verdicts(_plan([_entry(kind="chart-story")]))
        self.assertEqual((v.gate, v.severity), ("comp_capabilities", "FAIL"))
        self.assertIn("1920x1080", v.evidence)          # the real canvas
        self.assertIn("16:9", v.evidence)
        self.assertIn("no aspect-legal same-family comp", v.evidence)

    def test_same_family_aspect_suggestion_uses_measured_synthetic_rows(self) -> None:
        comps = {"test": {"canvas": [1080, 1920]},
                 "test-wide": {"canvas": [1920, 1080]},
                 "unrelated": {"canvas": [1080, 1920]}}
        self.assertEqual(plc._aspect_siblings("test-wide", comps, "9:16"), ["test"])

    def test_headroom_and_beside_face_also_fire(self) -> None:
        for anchor in ("headroom", "beside-face"):
            verdicts = self.verdicts(
                _plan([_entry(kind="chart-story", anchor=anchor)]))
            self.assertEqual([v.severity for v in verdicts], ["FAIL"], anchor)

    def test_matching_aspect_is_clean(self) -> None:
        self.assertEqual(self.verdicts(_plan([_entry()])), [])
        wide = _plan([_entry(kind="chart-story")], mode="longform")
        self.assertEqual(self.verdicts(wide), [])

    def test_no_registered_sibling_named_honestly(self) -> None:
        (v,) = self.verdicts(_plan([_entry(kind="chart-story")]))
        self.assertIn("no aspect-legal same-family comp is registered",
                      v.evidence)

    def test_own_screen_anchor_uses_rule_b_not_rule_a(self) -> None:
        plan = _plan([_entry(kind="chart-story", anchor="own-screen")])
        (v,) = self.verdicts(plan)      # exactly one — no (a)+(b) double fire
        self.assertIn("own-screen comp's measured canvas", v.evidence)


class OwnScreenAspectTests(_MatrixCase):
    """(b) own-screen: the render-side aspect predicate, at plan time."""

    def test_mismatch_fails_before_any_render(self) -> None:
        plan = _plan([_entry(anchor="own-screen")], mode="longform")
        (v,) = self.verdicts(plan)
        self.assertEqual(v.severity, "FAIL")
        self.assertIn("1080x1920", v.evidence)
        self.assertIn("does not match", v.evidence)

    def test_match_is_clean(self) -> None:
        self.assertEqual(
            self.verdicts(_plan([_entry(anchor="own-screen")])), [])

    def test_canvas_note_defers_to_the_render_measure(self) -> None:
        # An ambiguous static measurement (css root != declared dims) must
        # not fail fast — the render-side check stays authoritative. The
        # row is also static-only, so the fade rules SKIP with evidence.
        plan = _plan([_entry(kind="hw-scribble-transition", anchor="own-screen")],
                     mode="longform")
        (v,) = self.verdicts(plan)
        self.assertEqual(v.severity, "FAIL")
        self.assertIn("fadeClass is missing", v.evidence)


class HoldToCutTests(_MatrixCase):
    """(c) hold-to-cut comps must exit on a cut."""

    def test_off_seam_end_fails(self) -> None:
        (v,) = self.verdicts(_plan([_entry(kind="count-up", outStart=4.0,
                                           outEnd=6.0)]))
        self.assertEqual(v.severity, "FAIL")
        self.assertIn("hold-to-cut comp must exit on a cut", v.evidence)
        self.assertIn("outEnd 6", v.evidence)

    def test_end_on_seam_is_clean(self) -> None:
        plan = _plan([_entry(kind="count-up", outStart=8.0, outEnd=10.0)])
        self.assertEqual(self.verdicts(plan), [])

    def test_end_within_tolerance_is_clean(self) -> None:
        plan = _plan([_entry(kind="count-up", outStart=8.0, outEnd=10.04)])
        self.assertEqual(self.verdicts(plan), [])

    def test_end_at_output_end_is_clean(self) -> None:
        plan = _plan([_entry(kind="count-up", outStart=15.0, outEnd=18.0)])
        self.assertEqual(self.verdicts(plan), [])

    def test_exit_on_cut_flag_satisfies_the_law(self) -> None:
        plan = _plan([_entry(kind="count-up", outStart=4.0, outEnd=6.0,
                             exitOnCut=True)])
        self.assertEqual(self.verdicts(plan), [])

    def test_unbuildable_seam_map_skips_with_evidence(self) -> None:
        plan = _plan([_entry(kind="count-up", outStart=4.0, outEnd=6.0)])
        plan["cutTrack"] = []
        (v,) = self.verdicts(plan)
        self.assertEqual(v.severity, "SKIP")
        self.assertIn("seam map is unavailable", v.evidence)


class PartialFadeTests(_MatrixCase):
    """(d) partial-fade WARNs with the measured terminal alpha."""

    def test_partial_fade_warns_with_measured_alpha(self) -> None:
        (v,) = self.verdicts(_plan([_entry(kind="hw-callout-circle")]))
        self.assertEqual(v.severity, "WARN")
        self.assertIn("max=180", v.evidence)
        self.assertIn("mean=12.4", v.evidence)


class LintDispatchTests(unittest.TestCase):
    """plan_lint.lint() routes matrix verdicts through the policy table."""

    def _mg_plan(self) -> dict:
        plan = copy.deepcopy(good_plan())
        plan["treatmentMap"] = [
            {"outStart": 0, "outEnd": 30, "treatment": "kinetic",
             "budget": "high", "visualState": "talking-head"},
        ]
        plan["graphicsTrack"] = [
            {"outStart": 4.0, "outEnd": 6.0, "kind": "count-up",
             "spec": {"from": 0, "to": 10, "suffix": " years", "label": "Experience"},
             "anchor": "free-band",
             "reason": "restates 'ten years' — number trigger"},
        ]
        return plan

    def test_hold_to_cut_fail_lands_in_lint_errors(self) -> None:
        # count-up is hold-to-cut in the fixture; the single-segment
        # cutTrack has no seams and the window ends mid-take at 6.0s.
        with tempfile.TemporaryDirectory() as tmp:
            matrix = _write_matrix(tmp)
            with mock.patch.object(plc, "DEFAULT_MATRIX_PATH", matrix):
                rep = pl.lint(self._mg_plan(), MANIFEST)
        hits = [e for e in rep.errors
                if "hold-to-cut comp must exit on a cut" in e]
        self.assertEqual(len(hits), 1, rep.errors)
        self.assertTrue(hits[0].startswith("comp_capabilities:"), hits[0])

    def test_missing_matrix_is_a_lint_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
                plc, "DEFAULT_MATRIX_PATH",
                os.path.join(tmp, "comp_capabilities.json")):
            rep = pl.lint(self._mg_plan(), MANIFEST)
        errors = [e for e in rep.errors
                  if e.startswith("comp_capabilities:")]
        self.assertEqual(len(errors), 1, rep.errors)
        self.assertIn("matrix file missing", errors[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
