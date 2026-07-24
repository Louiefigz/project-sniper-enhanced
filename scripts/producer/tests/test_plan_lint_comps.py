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
* missing/malformed matrix = SKIP-with-evidence (never crash/silent-pass),
  unknown kind = WARN, unmeasured fade = SKIP;
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

import gate_policy as gpol
import plan_lint as pl
import plan_lint_comps as plc

# Synthetic capability matrix: every fade class + both aspects + the
# degenerate rows (static-only, renderError, canvasNote ambiguity).
_COMPS = {
    "chip-row": {"canvas": [1080, 1920], "fadeClass": "fades-clean"},
    "stat-card": {"canvas": [1080, 1920], "fadeClass": "hold-to-cut",
                  "terminalAlpha": {"maxAlpha8": 255, "meanAlpha8": 211.5}},
    "kinetic-quote": {"canvas": [1080, 1920], "fadeClass": "fades-clean"},
    "kinetic-quote-wide": {"canvas": [1920, 1080],
                           "fadeClass": "fades-clean"},
    "solo-wide": {"canvas": [1920, 1080], "fadeClass": "fades-clean"},
    "glass-rail": {"canvas": [1080, 1920], "fadeClass": "partial-fade",
                   "terminalAlpha": {"maxAlpha8": 180, "meanAlpha8": 12.4}},
    "statement-card": {"canvas": [1080, 1920]},          # probe mid-run
    "logo-card": {"canvas": [1080, 1920],
                  "renderError": "hyperframes died"},
    "section-takeover": {"canvas": [1080, 1920],
                         "canvasNote": "css root (1080, 1920) != declared "
                                       "data-width/height (1920, 1080)"},
}


def _write_matrix(dirpath: str, comps: dict = None) -> str:
    """Write a synthetic comp_capabilities.json; returns its path."""
    path = os.path.join(dirpath, "comp_capabilities.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"schemaVersion": 1, "comps": comps or _COMPS,
                   "digest": "synthetic"}, handle)
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
    entry = {"kind": "chip-row", "anchor": "free-band", "outStart": 8.0,
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
        (v,) = self.verdicts(_plan([_entry(kind="kinetic-quote-wide")]))
        self.assertEqual((v.gate, v.severity), ("comp_capabilities", "FAIL"))
        self.assertIn("1920x1080", v.evidence)          # the real canvas
        self.assertIn("16:9", v.evidence)
        self.assertIn("kinetic-quote", v.evidence)      # the legal sibling

    def test_headroom_and_beside_face_also_fire(self) -> None:
        for anchor in ("headroom", "beside-face"):
            verdicts = self.verdicts(
                _plan([_entry(kind="kinetic-quote-wide", anchor=anchor)]))
            self.assertEqual([v.severity for v in verdicts], ["FAIL"], anchor)

    def test_matching_aspect_is_clean(self) -> None:
        self.assertEqual(self.verdicts(_plan([_entry()])), [])
        wide = _plan([_entry(kind="kinetic-quote-wide")], mode="longform")
        self.assertEqual(self.verdicts(wide), [])

    def test_no_registered_sibling_named_honestly(self) -> None:
        (v,) = self.verdicts(_plan([_entry(kind="solo-wide")]))
        self.assertIn("no aspect-legal same-family comp is registered",
                      v.evidence)

    def test_own_screen_anchor_uses_rule_b_not_rule_a(self) -> None:
        plan = _plan([_entry(kind="kinetic-quote-wide", anchor="own-screen")])
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
        plan = _plan([_entry(kind="section-takeover", anchor="own-screen")],
                     mode="longform")
        (v,) = self.verdicts(plan)
        self.assertEqual(v.severity, "SKIP")
        self.assertIn("no measured fadeClass", v.evidence)


class HoldToCutTests(_MatrixCase):
    """(c) hold-to-cut comps must exit on a cut."""

    def test_off_seam_end_fails(self) -> None:
        (v,) = self.verdicts(_plan([_entry(kind="stat-card", outStart=4.0,
                                           outEnd=6.0)]))
        self.assertEqual(v.severity, "FAIL")
        self.assertIn("hold-to-cut comp must exit on a cut", v.evidence)
        self.assertIn("outEnd 6", v.evidence)

    def test_end_on_seam_is_clean(self) -> None:
        plan = _plan([_entry(kind="stat-card", outStart=8.0, outEnd=10.0)])
        self.assertEqual(self.verdicts(plan), [])

    def test_end_within_tolerance_is_clean(self) -> None:
        plan = _plan([_entry(kind="stat-card", outStart=8.0, outEnd=10.04)])
        self.assertEqual(self.verdicts(plan), [])

    def test_end_at_output_end_is_clean(self) -> None:
        plan = _plan([_entry(kind="stat-card", outStart=15.0, outEnd=18.0)])
        self.assertEqual(self.verdicts(plan), [])

    def test_exit_on_cut_flag_satisfies_the_law(self) -> None:
        plan = _plan([_entry(kind="stat-card", outStart=4.0, outEnd=6.0,
                             exitOnCut=True)])
        self.assertEqual(self.verdicts(plan), [])

    def test_unbuildable_seam_map_skips_with_evidence(self) -> None:
        plan = _plan([_entry(kind="stat-card", outStart=4.0, outEnd=6.0)])
        plan["cutTrack"] = []
        (v,) = self.verdicts(plan)
        self.assertEqual(v.severity, "SKIP")
        self.assertIn("seam map is unavailable", v.evidence)


class PartialFadeTests(_MatrixCase):
    """(d) partial-fade WARNs with the measured terminal alpha."""

    def test_partial_fade_warns_with_measured_alpha(self) -> None:
        (v,) = self.verdicts(_plan([_entry(kind="glass-rail")]))
        self.assertEqual(v.severity, "WARN")
        self.assertIn("max=180", v.evidence)
        self.assertIn("mean=12.4", v.evidence)


class MatrixAvailabilityTests(unittest.TestCase):
    """Missing/partial matrix: SKIP-with-evidence, WARN unmeasured, no crash."""

    def test_missing_matrix_is_one_skip_with_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "comp_capabilities.json")
            verdicts = plc.matrix_verdicts(_plan([_entry(), _entry()]),
                                           matrix_path=missing)
        self.assertEqual([v.severity for v in verdicts], ["SKIP"])
        self.assertIn("matrix file missing", verdicts[0].evidence)
        self.assertIn("2 graphicsTrack entries unchecked",
                      verdicts[0].evidence)
        out = gpol.to_gate_json(verdicts, {"mode": "short"})
        self.assertTrue(out["ok"])                       # skip never blocks…
        self.assertIn("SKIP", out["warnings"][0])        # …never silent

    def test_malformed_matrix_is_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "comp_capabilities.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            (v,) = plc.matrix_verdicts(_plan([_entry()]), matrix_path=path)
            self.assertEqual(v.severity, "SKIP")
            self.assertIn("matrix unreadable", v.evidence)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"comps": {}}, handle)
            (v,) = plc.matrix_verdicts(_plan([_entry()]), matrix_path=path)
            self.assertIn("no comps map", v.evidence)

    def test_empty_track_emits_nothing(self) -> None:
        self.assertEqual(plc.matrix_verdicts(_plan([]), matrix_path="/nope"),
                         [])

    def test_unknown_kind_warns_unmeasured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matrix = _write_matrix(tmp)
            (v,) = plc.matrix_verdicts(
                _plan([_entry(kind="mystery-comp")]), matrix_path=matrix)
        self.assertEqual(v.severity, "WARN")
        self.assertIn("unmeasured comp", v.evidence)

    def test_static_only_and_render_error_rows_skip_fade_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matrix = _write_matrix(tmp)
            (static,) = plc.matrix_verdicts(
                _plan([_entry(kind="statement-card")]), matrix_path=matrix)
            (errored,) = plc.matrix_verdicts(
                _plan([_entry(kind="logo-card")]), matrix_path=matrix)
        self.assertEqual(static.severity, "SKIP")
        self.assertIn("has not measured it yet", static.evidence)
        self.assertEqual(errored.severity, "SKIP")
        self.assertIn("hyperframes died", errored.evidence)


class LintDispatchTests(unittest.TestCase):
    """plan_lint.lint() routes matrix verdicts through the policy table."""

    def _mg_plan(self) -> dict:
        plan = copy.deepcopy(good_plan())
        plan["treatmentMap"] = [
            {"outStart": 0, "outEnd": 30, "treatment": "kinetic",
             "budget": "high", "visualState": "talking-head"},
        ]
        plan["graphicsTrack"] = [
            {"outStart": 4.0, "outEnd": 6.0, "kind": "stat-card",
             "spec": {"value": "10+ years", "label": ""},
             "anchor": "free-band",
             "reason": "restates 'ten years' — number trigger"},
        ]
        return plan

    def test_hold_to_cut_fail_lands_in_lint_errors(self) -> None:
        # stat-card is hold-to-cut in the fixture; the single-segment
        # cutTrack has no seams and the window ends mid-take at 6.0s.
        with tempfile.TemporaryDirectory() as tmp:
            matrix = _write_matrix(tmp)
            with mock.patch.object(plc, "DEFAULT_MATRIX_PATH", matrix):
                rep = pl.lint(self._mg_plan(), MANIFEST)
        hits = [e for e in rep.errors
                if "hold-to-cut comp must exit on a cut" in e]
        self.assertEqual(len(hits), 1, rep.errors)
        self.assertTrue(hits[0].startswith("comp_capabilities:"), hits[0])

    def test_missing_matrix_is_a_lint_warning_not_an_error(self) -> None:
        # _common points the default at a guaranteed-missing path.
        rep = pl.lint(self._mg_plan(), MANIFEST)
        self.assertEqual(
            [e for e in rep.errors if "comp_capabilities" in e], [])
        skips = [w for w in rep.warnings
                 if w.startswith("comp_capabilities: SKIP")]
        self.assertEqual(len(skips), 1, rep.warnings)


if __name__ == "__main__":
    unittest.main(verbosity=2)
