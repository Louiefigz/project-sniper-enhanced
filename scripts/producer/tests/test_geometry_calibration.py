"""A3 margin-calibration ledger (contract v3 item #4).

Residual append against ``geometry_predictions.json``, the per-axis p95
margin math with its calibration floors (min windows / min runs / every
axis), the uncalibrated ``None`` state, the WARN→FAIL severity flip on the
feasibility lint, and the graphics-stage journaling wire (loud WARN on
failure, never a raise after a succeeded composite).
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403  (exports gs = graphics.graphics_stage)

import gate_policy
from graphics import graphics_stage as gstage
from planner import geometry_calibration as gc
from planner import geometry_feasibility as gf
from planner import geometry_proxy as gproxy

_PRED = {"tag": "graphicsTrack[0] chip-row", "kind": "chip-row",
         "anchor": "headroom", "window": [4.0, 8.0],
         "expandedFace": [100.0, 200.0, 700.0, 900.0]}
_ACTUAL = {"outStart": 4.0, "outEnd": 8.0, "anchor": "headroom",
           "kind": "chip-row",
           "expandedFace": [110.0, 190.0, 705.0, 905.0]}


def _write_predictions(producer_dir: str, windows: list) -> None:
    path = os.path.join(producer_dir, gc.PREDICTIONS_FILENAME)
    with open(path, "w") as f:
        json.dump({"gate": "geometry_feasibility", "proxyScale": 0.5,
                   "windows": windows}, f)


def _rows(n_windows: int, n_runs: int, x0_residuals=None) -> list:
    """Synthetic ledger rows: n distinct windows spread across n runs."""
    rows = []
    for i in range(n_windows):
        for axis in gc.AXES:
            residual = 5.0
            if axis == "x0" and x0_residuals is not None:
                residual = float(x0_residuals[i])
            rows.append({"window": [float(i), float(i + 1)], "axis": axis,
                         "predicted": 100.0, "actual": 100.0 + residual,
                         "residual_px": residual, "ts": "2026-07-23T00:00:00",
                         "run": f"r{i % n_runs}"})
    return rows


class ResidualAppendTests(unittest.TestCase):
    """append_residuals: match windows, journal per axis, JSONL on disk."""

    def test_append_journals_one_row_per_axis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_predictions(tmp, [_PRED])
            appended = gc.append_residuals(tmp, [_ACTUAL], run_id="run-1")
            self.assertEqual(appended, 4)
            rows = gc.read_ledger(tmp)
        self.assertEqual([r["axis"] for r in rows], list(gc.AXES))
        by_axis = {r["axis"]: r for r in rows}
        self.assertAlmostEqual(by_axis["x0"]["residual_px"], 10.0)
        self.assertAlmostEqual(by_axis["y0"]["residual_px"], -10.0)
        self.assertAlmostEqual(by_axis["x1"]["residual_px"], 5.0)
        self.assertAlmostEqual(by_axis["y1"]["residual_px"], 5.0)
        for row in rows:
            self.assertEqual(row["window"], [4.0, 8.0])
            self.assertEqual(row["run"], "run-1")
            self.assertEqual(sorted(row), sorted(gc._ROW_KEYS))

    def test_append_without_predictions_is_a_zero_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(gc.append_residuals(tmp, [_ACTUAL]), 0)
            self.assertFalse(os.path.exists(gc.ledger_path(tmp)))

    def test_unmatched_window_or_anchor_journals_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_predictions(tmp, [_PRED])
            off_window = dict(_ACTUAL, outStart=9.0, outEnd=11.0)
            off_anchor = dict(_ACTUAL, anchor="chest")
            no_measure = dict(_ACTUAL, expandedFace=None)
            self.assertEqual(gc.append_residuals(
                tmp, [off_window, off_anchor, no_measure]), 0)

    def test_read_ledger_raises_on_a_malformed_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = gc.ledger_path(tmp)
            os.makedirs(os.path.dirname(path))
            with open(path, "w") as f:
                f.write("not json\n")
            with self.assertRaisesRegex(ValueError, "malformed"):
                gc.read_ledger(tmp)

    def test_read_ledger_raises_on_a_missing_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = gc.ledger_path(tmp)
            os.makedirs(os.path.dirname(path))
            with open(path, "w") as f:
                f.write(json.dumps({"axis": "x0"}) + "\n")
            with self.assertRaisesRegex(ValueError, "missing"):
                gc.read_ledger(tmp)


class MarginMathTests(unittest.TestCase):
    """margin_from_residuals: p95 per axis; None below the floors."""

    def test_per_axis_p95_once_calibrated(self) -> None:
        margin = gc.margin_from_residuals(
            _rows(20, 5, x0_residuals=list(range(20))))
        self.assertIsNotNone(margin)
        # Nearest-rank p95 of 0..19 → sorted[ceil(.95*20)-1] = 18.
        self.assertEqual(margin["x0"], 18.0)
        for axis in ("y0", "x1", "y1"):
            self.assertEqual(margin[axis], 5.0)

    def test_below_window_floor_is_uncalibrated(self) -> None:
        self.assertIsNone(gc.margin_from_residuals(_rows(19, 5)))

    def test_below_run_floor_is_uncalibrated(self) -> None:
        self.assertIsNone(gc.margin_from_residuals(_rows(20, 4)))

    def test_missing_axis_is_uncalibrated(self) -> None:
        rows = [r for r in _rows(20, 5) if r["axis"] != "y1"]
        self.assertIsNone(gc.margin_from_residuals(rows))

    def test_empty_ledger_is_uncalibrated(self) -> None:
        self.assertIsNone(gc.margin_from_residuals([]))

    def test_residual_sign_is_ignored_for_the_margin(self) -> None:
        rows = _rows(20, 5, x0_residuals=[-40.0] * 20)
        self.assertEqual(gc.margin_from_residuals(rows)["x0"], 40.0)

    def test_calibrated_margin_reads_the_ledger_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(gc.calibrated_margin(tmp))     # no ledger yet
            path = gc.ledger_path(tmp)
            os.makedirs(os.path.dirname(path))
            with open(path, "w") as f:
                for row in _rows(20, 5):
                    f.write(json.dumps(row) + "\n")
            margin = gc.calibrated_margin(tmp)
        self.assertEqual(set(margin), set(gc.AXES))


class SeverityFlipTests(unittest.TestCase):
    """Item #4's WARN→FAIL flip through gate_policy's calibration flag."""

    def test_severity_for_honors_the_calibration_flag(self) -> None:
        self.assertEqual(
            gate_policy.severity_for(gf.GATE, "FAIL", calibrated=False), "WARN")
        self.assertEqual(
            gate_policy.severity_for(gf.GATE, "FAIL", calibrated=True), "FAIL")

    def test_run_severity_flips_on_a_calibrated_ledger(self) -> None:
        with mock.patch.object(gc, "calibrated_margin", return_value=None):
            self.assertEqual(gf.run_severity("/p"), "WARN")
        with mock.patch.object(gc, "calibrated_margin",
                               return_value={a: 8.0 for a in gc.AXES}):
            self.assertEqual(gf.run_severity("/p"), "FAIL")

    def test_calibrated_lint_verdict_blocks(self) -> None:
        plan = {"target": {"mode": "short"},
                "captions": {"burn": True},
                "graphicsTrack": [{"outStart": 4.0, "outEnd": 8.0,
                                   "kind": "chip-row", "anchor": "headroom",
                                   "spec": {"items": ["a"]}}]}
        run = gf.LintRun(plan, {"sources": []}, "cache", (1080, 1920),
                         mode="short", severity="FAIL")
        tight = gproxy.DeliveryGeom(face_px=(150.0, 500.0, 650.0, 700.0),
                                    hair_top=400.0, punch_scale=1.12,
                                    crop_strategy="face")
        entry = plan["graphicsTrack"][0]
        with mock.patch.object(gf, "render_entry",
                               return_value={"path": "c.mov", "fmt": "mov",
                                             "kind": "chip-row",
                                             "cached": True, "key": "k"}), \
             mock.patch.object(gf, "_content_bbox",
                               return_value=(60, 300, 960, 900)):
            gf.check_window(run, "graphicsTrack[0] chip-row", entry, tight)
        self.assertEqual(len(run.verdicts), 1)
        self.assertEqual(run.verdicts[0].severity, "FAIL")
        self.assertEqual(gate_policy.resolve(run.verdicts[0],
                                             plan["target"]), "block")


class JournalWireTests(unittest.TestCase):
    """geometry_calibration.journal_actuals: append on success, WARN on failure.

    graphics_stage wires this exact seam (``journal_actuals(producer_dir,
    rows, emit)``) after every composite when ``--producer-dir`` is known.
    """

    _ROW = {"kind": "chip-row", "anchor": "headroom", "outStart": 4.0,
            "outEnd": 8.0, "expandedFace": [110.0, 190.0, 705.0, 905.0],
            "hairMeasured": True}

    def test_journal_appends_against_predictions(self) -> None:
        emitted = mock.Mock()
        with tempfile.TemporaryDirectory() as tmp:
            _write_predictions(tmp, [_PRED])
            gc.journal_actuals(tmp, [self._ROW, {"anchor": "x"}], emitted)
            self.assertEqual(len(gc.read_ledger(tmp)), 4)
        statuses = [c.kwargs.get("status") for c in emitted.call_args_list]
        self.assertIn("geometry_residuals", statuses)

    def test_journal_failure_warns_and_never_raises(self) -> None:
        emitted = mock.Mock()
        with mock.patch.object(gc, "append_residuals",
                               side_effect=OSError("disk full")):
            gc.journal_actuals("/nowhere", [self._ROW], emitted)
        rows = [c.kwargs for c in emitted.call_args_list]
        self.assertEqual(rows[0]["status"], "geometry_residuals_failed")
        self.assertEqual(rows[0]["severity"], "WARN")
        self.assertEqual(rows[0]["gate"], gc.CALIBRATION_GATE)
        self.assertIn("disk full", rows[0]["evidence"])

    def test_no_measured_rows_is_a_silent_noop(self) -> None:
        with mock.patch.object(gc, "append_residuals",
                               side_effect=AssertionError("must not run")):
            gc.journal_actuals("/p", [{"anchor": "headroom",
                                       "expandedFace": None}], mock.Mock())


if __name__ == "__main__":
    unittest.main(verbosity=2)
