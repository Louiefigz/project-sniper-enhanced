"""comp_measure tests — plan-time comp-size gate (geometry contract v3 #2).

Pins the three contract surfaces the build item demands:

* Duration parity with assemble — the gate renders the SAME entries assemble's
  composite will render (post exitOnCut clamp, unpadded; padding only on the
  explicit Palmier-lane fps), so the content-hash cache hit is guaranteed.
* FAIL on an oversized measured bbox (render mocked) with the numbers in the
  evidence, adapted to the exact {ok, errors, warnings} gate contract.
* SKIP-with-evidence when the node/browser/cv2 toolchain is missing — never a
  crash, never a silent pass — plus the cache-aware budget early exit.
"""
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403  (shared fixtures + sys.path setup)
import gate_policy as gpol
from graphics import comp_measure as cmz
from graphics import exit_on_cut as eoc
from graphics import graphics_render as grr
from producer_config import CANVAS_BY_ASPECT, SAFE_BOX

_NINE16 = (CANVAS_BY_ASPECT["9:16"]["width"], CANVAS_BY_ASPECT["9:16"]["height"])
_LEGAL_W = _NINE16[0] - SAFE_BOX["left"] - SAFE_BOX["right"]


def _plan(entries: list) -> dict:
    """Two-segment cutTrack (seam at output 10.0s) + the given graphics."""
    return {
        "target": {"mode": "short"},
        "cutTrack": [
            {"sourceId": "raw-1", "start": 0.0, "end": 10.0, "speed": 1.0},
            {"sourceId": "raw-1", "start": 12.0, "end": 20.0, "speed": 1.0},
        ],
        "graphicsTrack": entries,
    }


def _entry(**overrides) -> dict:
    entry = {"kind": "chip-row", "anchor": "free-band", "outStart": 8.0,
             "outEnd": 11.5, "exitOnCut": True, "spec": {}}
    entry.update(overrides)
    return entry


def _rendered(fmt: str = "mov") -> dict:
    return {"path": "/fake/render.mov", "cached": True, "key": "k",
            "kind": "chip-row", "fmt": fmt, "proof": {}}


class DurationParityTests(unittest.TestCase):
    """The gate's effective entries ARE assemble's composite entries."""

    def test_effective_entries_match_assemble_clamp(self) -> None:
        plan = _plan([_entry()])
        expected, clamped = eoc.apply_exit_on_cut(plan)
        self.assertEqual(clamped, 1)
        self.assertEqual(cmz.effective_entries(plan), expected)
        # The exitOnCut window dies exactly on the 10.0s seam — the duration
        # render_entry hashes is outEnd - outStart of THIS entry.
        self.assertEqual(cmz.effective_entries(plan)[0]["outEnd"], 10.0)

    def test_no_padding_by_default(self) -> None:
        # render.py/assemble never pad; the default lane must not either.
        plan = _plan([_entry(outStart=0.98, outEnd=2.02, exitOnCut=False)])
        (entry,) = cmz.effective_entries(plan)
        self.assertEqual(entry["outEnd"], 2.02)

    def test_fps_routes_through_timeline_padded_entry(self) -> None:
        plan = _plan([_entry(outStart=0.98, outEnd=2.02, exitOnCut=False)])
        clamped, _ = eoc.apply_exit_on_cut(plan)
        expected = [grr.timeline_padded_entry(e, 30.0) for e in clamped]
        self.assertEqual(cmz.effective_entries(plan, fps=30.0), expected)

    def test_render_entry_receives_the_clamped_entry(self) -> None:
        """The cache key inputs are assemble's: the CLAMPED entry, verbatim."""
        plan = _plan([_entry()])
        seen: list = []

        def fake_render(entry: dict, cache_dir: str) -> dict:
            seen.append((entry, cache_dir))
            return _rendered()

        with mock.patch.object(cmz, "environment_issue", return_value=None), \
                mock.patch.object(cmz, "cache_probe", return_value="/hit.mov"), \
                mock.patch.object(cmz, "render_entry", side_effect=fake_render), \
                mock.patch.object(cmz, "_content_bbox",
                                  return_value=(200, 900, 800, 1000)):
            verdicts, metrics = cmz.measure_plan(plan, "/cache", 15.0)
        self.assertEqual(verdicts, [])
        self.assertEqual(metrics["measured"], 1)
        (entry, cache_dir), = seen
        self.assertEqual(cache_dir, "/cache")
        self.assertEqual(entry["outEnd"], 10.0)   # the clamped window
        self.assertEqual(entry, eoc.apply_exit_on_cut(plan)[0][0])


class OversizedBboxTests(unittest.TestCase):
    """FAIL with measured numbers when the content cannot be placed legally."""

    def _measure(self, entries: list, bbox: tuple,
                 fmt: str = "mov") -> tuple:
        plan = _plan(entries)
        with mock.patch.object(cmz, "environment_issue", return_value=None), \
                mock.patch.object(cmz, "cache_probe", return_value="/hit.mov"), \
                mock.patch.object(cmz, "render_entry",
                                  return_value=_rendered(fmt)), \
                mock.patch.object(cmz, "_content_bbox", return_value=bbox):
            return cmz.measure_plan(plan, "/cache", 15.0)

    def test_edge_to_edge_row_fails_with_numbers(self) -> None:
        # The LL-035 signature: full-width single row (1080 x ~185).
        verdicts, _ = self._measure([_entry()], (0, 855, 1079, 1039))
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].severity, "FAIL")
        self.assertIn("1080x185", verdicts[0].evidence)
        self.assertIn(str(_LEGAL_W), verdicts[0].evidence)
        gate_json = gpol.to_gate_json(verdicts, {"mode": "short"})
        self.assertFalse(gate_json["ok"])
        self.assertIn("comp_size", gate_json["errors"][0])

    def test_fitting_bbox_passes_clean(self) -> None:
        verdicts, _ = self._measure([_entry()], (200, 855, 800, 1000))
        self.assertEqual(verdicts, [])

    def test_full_bleed_treatment_is_exempt(self) -> None:
        verdicts, _ = self._measure([_entry()], (0, 0, 1079, 1919))
        self.assertEqual(verdicts, [])

    def test_registered_rail_geometry_is_exempt(self) -> None:
        with mock.patch.object(cmz, "_content_bbox") as bbox_probe:
            verdicts, _ = self._measure([_entry(kind="glass-rail")],
                                        (0, 0, 1079, 1919))
        self.assertEqual(verdicts, [])
        bbox_probe.assert_not_called()

    def test_placed_pin_exceeding_canvas_fails(self) -> None:
        entry = _entry(exitOnCut=False, placement={"x": 900.0, "y": 1800.0})
        verdicts, _ = self._measure([entry], (0, 0, 399, 299))
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].severity, "FAIL")
        self.assertIn("exceeds the 1080x1920 delivery canvas",
                      verdicts[0].evidence)

    def test_ownscreen_aspect_mismatch_fails(self) -> None:
        # chip-row's authored canvas is 1080x1920; a longform (16:9) delivery
        # mismatches → the composite would refuse it — caught at lint.
        plan = _plan([_entry(anchor="own-screen", exitOnCut=False)])
        plan["target"]["mode"] = "longform"
        with mock.patch.object(cmz, "environment_issue", return_value=None), \
                mock.patch.object(cmz, "cache_probe", return_value="/hit.mp4"), \
                mock.patch.object(cmz, "render_entry",
                                  return_value=_rendered("mp4")):
            verdicts, _ = cmz.measure_plan(plan, "/cache", 15.0)
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].severity, "FAIL")
        self.assertIn("does not match", verdicts[0].evidence)


class SkipAndBudgetTests(unittest.TestCase):
    """SKIP-with-evidence: missing toolchain and the cache-aware budget."""

    def test_missing_tools_skip_with_evidence(self) -> None:
        plan = _plan([_entry()])
        with mock.patch.object(cmz, "environment_issue",
                               return_value="render tools unavailable: no node"):
            verdicts, metrics = cmz.measure_plan(plan, "/cache", 15.0)
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].severity, "SKIP")
        self.assertIn("no node", verdicts[0].evidence)
        self.assertEqual(metrics["skipped"], 1)
        gate_json = gpol.to_gate_json(verdicts, {"mode": "short"})
        self.assertTrue(gate_json["ok"])            # skip never blocks…
        self.assertIn("SKIP", gate_json["warnings"][0])   # …never silent

    def test_environment_issue_reports_missing_hyperframes(self) -> None:
        with mock.patch.object(grr, "HYPERFRAMES_BIN", "/nonexistent/cli.js"):
            issue = cmz.environment_issue()
        self.assertIsNotNone(issue)
        self.assertIn("HyperFrames", issue)

    def test_cold_entries_skip_when_budget_exhausted(self) -> None:
        plan = _plan([_entry(), _entry(outStart=2.0, outEnd=4.0,
                                       exitOnCut=False)])
        with mock.patch.object(cmz, "environment_issue", return_value=None), \
                mock.patch.object(cmz, "cache_probe", return_value=None), \
                mock.patch.object(cmz, "render_entry") as render:
            verdicts, metrics = cmz.measure_plan(plan, "/cache", 0.0)
        render.assert_not_called()
        self.assertEqual([v.severity for v in verdicts], ["SKIP", "SKIP"])
        self.assertIn("budget", verdicts[0].evidence)
        self.assertEqual(metrics["skipped"], 2)

    def test_cached_entries_measured_despite_exhausted_budget(self) -> None:
        plan = _plan([_entry()])
        with mock.patch.object(cmz, "environment_issue", return_value=None), \
                mock.patch.object(cmz, "cache_probe", return_value="/hit.mov"), \
                mock.patch.object(cmz, "render_entry",
                                  return_value=_rendered()), \
                mock.patch.object(cmz, "_content_bbox",
                                  return_value=(200, 900, 800, 1000)):
            verdicts, metrics = cmz.measure_plan(plan, "/cache", 0.0)
        self.assertEqual(verdicts, [])
        self.assertEqual(metrics["measured"], 1)
        self.assertEqual(metrics["cachedHits"], 1)

    def test_render_failure_is_a_fail_verdict_not_a_crash(self) -> None:
        plan = _plan([_entry()])
        with mock.patch.object(cmz, "environment_issue", return_value=None), \
                mock.patch.object(cmz, "cache_probe", return_value="/hit.mov"), \
                mock.patch.object(cmz, "render_entry",
                                  side_effect=RuntimeError("hyperframes died")):
            verdicts, _ = cmz.measure_plan(plan, "/cache", 15.0)
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].severity, "FAIL")
        self.assertIn("hyperframes died", verdicts[0].evidence)

    def test_empty_track_is_clean(self) -> None:
        verdicts, metrics = cmz.measure_plan(_plan([]), "/cache", 15.0)
        self.assertEqual(verdicts, [])
        self.assertEqual(metrics["entries"], 0)


class MatrixFailFastTests(unittest.TestCase):
    """Pre-render fail-fast from the comp-capability matrix (aspect only)."""

    _COMPS = {"chip-row": {"canvas": [1080, 1920],
                           "fadeClass": "fades-clean"}}

    def test_known_aspect_mismatch_fails_without_rendering(self) -> None:
        plan = _plan([_entry(anchor="own-screen", exitOnCut=False)])
        plan["target"]["mode"] = "longform"
        with mock.patch.object(cmz, "environment_issue", return_value=None), \
                mock.patch.object(cmz.plan_lint_comps, "load_matrix",
                                  return_value=(self._COMPS, "")), \
                mock.patch.object(cmz, "render_entry") as render, \
                mock.patch.object(cmz, "cache_probe") as probe:
            verdicts, metrics = cmz.measure_plan(plan, "/cache", 15.0)
        render.assert_not_called()      # the render was saved
        probe.assert_not_called()
        self.assertEqual(len(verdicts), 1)
        self.assertEqual((verdicts[0].gate, verdicts[0].severity),
                         ("comp_size", "FAIL"))   # re-tagged onto THIS gate
        self.assertIn("does not match", verdicts[0].evidence)
        self.assertEqual(metrics["matrixFailFast"], 1)

    def test_matching_aspect_falls_through_to_the_render_measure(self) -> None:
        plan = _plan([_entry(anchor="own-screen", exitOnCut=False)])
        with mock.patch.object(cmz, "environment_issue", return_value=None), \
                mock.patch.object(cmz.plan_lint_comps, "load_matrix",
                                  return_value=(self._COMPS, "")), \
                mock.patch.object(cmz, "cache_probe",
                                  return_value="/hit.mp4"), \
                mock.patch.object(cmz, "render_entry",
                                  return_value=_rendered("mp4")) as render:
            verdicts, metrics = cmz.measure_plan(plan, "/cache", 15.0)
        render.assert_called_once()     # authoritative confirmation ran
        self.assertEqual(verdicts, [])
        self.assertEqual(metrics["matrixFailFast"], 0)
        self.assertEqual(metrics["measured"], 1)

    def test_missing_matrix_keeps_the_render_path(self) -> None:
        plan = _plan([_entry(anchor="own-screen", exitOnCut=False)])
        plan["target"]["mode"] = "longform"
        with mock.patch.object(cmz, "environment_issue", return_value=None), \
                mock.patch.object(cmz.plan_lint_comps, "load_matrix",
                                  return_value=(None, "matrix file missing")), \
                mock.patch.object(cmz, "cache_probe",
                                  return_value="/hit.mp4"), \
                mock.patch.object(cmz, "render_entry",
                                  return_value=_rendered("mp4")) as render:
            verdicts, metrics = cmz.measure_plan(plan, "/cache", 15.0)
        render.assert_called_once()     # no fast path — same answer, rendered
        self.assertEqual([v.severity for v in verdicts], ["FAIL"])
        self.assertEqual(metrics["matrixFailFast"], 0)

    def test_hole_entries_are_exempt_from_the_fast_path(self) -> None:
        # Hole comps render with alpha and never hit the own-screen mp4
        # check — the pre-check must mirror that exemption exactly.
        plan = _plan([_entry(anchor="own-screen", exitOnCut=False)])
        plan["target"]["mode"] = "longform"
        with mock.patch.object(cmz, "environment_issue", return_value=None), \
                mock.patch.object(cmz, "entry_has_hole", return_value=True), \
                mock.patch.object(cmz.plan_lint_comps, "load_matrix",
                                  return_value=(self._COMPS, "")), \
                mock.patch.object(cmz, "cache_probe",
                                  return_value="/hit.mov"), \
                mock.patch.object(cmz, "render_entry",
                                  return_value=_rendered()) as render:
            verdicts, metrics = cmz.measure_plan(plan, "/cache", 15.0)
        render.assert_called_once()
        self.assertEqual(verdicts, [])          # registered hole anatomy
        self.assertEqual(metrics["matrixFailFast"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
