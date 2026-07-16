"""Pure Palmier parity inventory tests; no app, media, or filesystem required."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palmier.parity import analyze_parity  # noqa: E402


def _cut(source: str = "raw-1", start: float = 0.0, end: float = 10.0) -> dict:
    return {"sourceId": source, "start": start, "end": end, "speed": 1.0}


def _ids(report: dict) -> set[str]:
    return {finding["id"] for finding in report["findings"]}


def _status(report: dict, ident: str) -> str:
    return next(row["status"] for row in report["findings"] if row["id"] == ident)


class ExactParityTests(unittest.TestCase):
    def test_single_source_cuts_and_baseline_transform_are_fully_editable(self) -> None:
        plan = {
            "cutTrack": [_cut(), _cut(start=12.0, end=18.0)],
            "baselineLook": {"zoom": 1.1, "centerX": 0.5, "centerY": 0.4,
                             "grade": "none"},
            "target": {"mode": "longform"},
        }
        report = analyze_parity(plan)
        self.assertTrue(report["fullyEditable"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["summary"]["byStatus"]["exact"]["entries"], 3)
        self.assertEqual(_ids(report), {"cuts:0", "cuts:1", "baseline:transform"})

    def test_absent_disabled_and_empty_lanes_create_no_findings(self) -> None:
        report = analyze_parity({
            "cutTrack": [_cut()], "graphicsTrack": [], "punchIns": [],
            "transitions": [], "brollTrack": [], "titleCards": [],
            "audioGain": [], "music": {"enabled": False},
            "reframe": {"strategy": "none"}, "baselineLook": {"grade": "none"},
        })
        self.assertTrue(report["fullyEditable"])
        self.assertEqual(_ids(report), {"cuts:0"})

    def test_native_palmier_color_is_exact_and_not_an_unknown_baseline(self) -> None:
        report = analyze_parity({
            "cutTrack": [_cut()],
            "baselineLook": {"grade": "none", "palmierColor": {
                "exposure": 0.03, "contrast": 0.08, "saturation": 0.04,
                "temperature": 0.01, "shadows": 0.03}},
        })
        self.assertEqual(_status(report, "baseline:palmier-color"), "exact")
        self.assertNotIn("baseline:unknown", _ids(report))

    def test_native_palmier_color_reset_is_exact(self) -> None:
        report = analyze_parity({
            "cutTrack": [_cut()],
            "baselineLook": {"grade": "none", "palmierColor": {"reset": True}},
        })
        self.assertEqual(_status(report, "baseline:palmier-color"), "exact")


class FidelityInventoryTests(unittest.TestCase):
    def test_every_supported_and_unsupported_lane_is_classified(self) -> None:
        plan = {
            "cutTrack": [_cut()],
            "baselineLook": {"zoom": 1.05, "grade": "warm"},
            "graphicsTrack": [{"id": "g-stable", "kind": "stat-card",
                                "outStart": 1.0, "outEnd": 3.0,
                                "placement": {"x": 10, "y": 20}}],
            "punchIns": [
                {"outStart": 2.0, "outEnd": 4.0, "zoom": 1.2},
                {"outStart": 5.0, "outEnd": 8.0,
                 "ease": "smooth",
                 "ramp": {"direction": "in", "ratePctPerS": 0.5}},
            ],
            "reframe": {"strategy": "face", "layout": "fill"},
            "titleCards": [{"text": "Hook", "outStart": 0.0, "outEnd": 2.0}],
            "captions": {"burn": False, "style": "line"},
            "transitions": [{"outTime": 4.0, "kind": "white-flash", "sfx": True}],
            "brollTrack": [{"outStart": 8.0, "outEnd": 10.0, "assetId": "b-1"}],
            "music": {"enabled": True, "assetId": "music-1"},
            "audioEnhance": {"preset": "voice-rnn"},
            "audioGain": [{"outStart": 1.0, "outEnd": 2.0, "dB": 2.0}],
            "treatmentMap": [{"outStart": 0.0, "outEnd": 1.0, "kind": "clean"}],
            "chapters": [{"outStart": 0.0, "title": "Intro"}],
        }
        report = analyze_parity(plan)
        self.assertFalse(report["fullyEditable"])
        self.assertTrue(report["mirrorReady"])
        self.assertEqual(report["mirrorMode"], "visual-master")
        self.assertEqual(report, analyze_parity(plan))
        self.assertEqual(_status(report, "cuts:0"), "exact")
        self.assertEqual(_status(report, "baseline:transform"), "exact")
        self.assertEqual(_status(report, "baseline:grade"), "unsupported")
        self.assertEqual(_status(report, "graphics:g-stable"), "baked")
        self.assertEqual(_status(report, "punch:0"), "unsupported")
        self.assertEqual(_status(report, "punch:1"), "approximate")
        self.assertEqual(_status(report, "transition:0"), "baked")
        self.assertEqual(_status(report, "sfx:transition:0"), "unsupported")
        expected = {"reframe", "titleCards:0", "captions", "transition:0",
                    "sfx:transition:0", "broll:0", "music", "audio:enhance",
                    "audioGain:0", "chapters"}
        self.assertTrue(expected.issubset(_ids(report)))
        self.assertNotIn("treatmentMap", _ids(report))
        self.assertEqual(report["mirrorBlockers"], [])
        self.assertEqual(report["syncBlockers"], [])
        graphic = next(row for row in report["findings"]
                       if row["id"] == "graphics:g-stable")
        self.assertIn("manual placement/scale", graphic["message"])

    def test_transition_preview_fidelity_is_kind_specific(self) -> None:
        report = analyze_parity({"cutTrack": [_cut()], "transitions": [
            {"outTime": 2.0, "kind": "white-flash"},
            {"outTime": 4.0, "kind": "light-leak"},
            {"outTime": 6.0, "kind": "zoom-pull"},
        ]})
        self.assertEqual(_status(report, "transition:0"), "baked")
        self.assertEqual(_status(report, "transition:1"), "approximate")
        self.assertEqual(_status(report, "transition:2"), "unsupported")

    def test_current_project_shape_reports_all_ramps_and_baked_graphics(self) -> None:
        plan = {
            "cutTrack": [_cut(start=float(i * 12), end=float(i * 12 + 8))
                         for i in range(10)],
            "graphicsTrack": [{"id": f"g-{i}", "kind": "card",
                                "outStart": float(i), "outEnd": float(i + 1)}
                               for i in range(14)],
            "punchIns": ([{"outStart": float(i), "outEnd": float(i + 0.5),
                            "zoom": 1.1} for i in range(3)] +
                          [{"outStart": float(i + 4), "outEnd": float(i + 4.5),
                            "ease": "smooth",
                            "ramp": {"direction": "in"}} for i in range(12)]),
            "captions": {"burn": False, "style": "line"},
            "audioEnhance": {"preset": "voice-rnn"},
            "music": {"enabled": False}, "reframe": {"strategy": "none"},
        }
        report = analyze_parity(plan)
        counts = report["summary"]["byStatus"]
        self.assertEqual(counts["exact"]["entries"], 10)
        self.assertEqual(counts["baked"]["entries"], 14)
        self.assertEqual(counts["approximate"]["entries"], 12)
        self.assertEqual(counts["unsupported"]["entries"], 5)
        self.assertTrue(report["mirrorReady"])
        self.assertEqual(report["mirrorBlockers"], [])


class FailClosedTests(unittest.TestCase):
    def test_malformed_plan_and_declared_lanes_are_unsupported(self) -> None:
        top = analyze_parity([])
        self.assertEqual(_status(top, "plan:malformed"), "unsupported")
        report = analyze_parity({
            "cutTrack": [], "graphicsTrack": {}, "reframe": [],
            "titleCards": [{"outStart": 0.0, "outEnd": 1.0}],
            "captions": "yes", "audioGain": "loud", "newVisualLane": {"x": 1},
        })
        expected = {"cuts:malformed", "graphics:malformed", "titleCards:0",
                    "captions:malformed", "audioGain:malformed",
                    "reframe", "unknown:newVisualLane"}
        self.assertEqual(_ids(report), expected)
        self.assertFalse(report["fullyEditable"])
        self.assertFalse(report["mirrorReady"])
        self.assertTrue(all(row["status"] == "unsupported"
                            for row in report["findings"]))

    def test_multi_source_cuts_mirror_but_are_not_fully_editable(self) -> None:
        report = analyze_parity({"cutTrack": [_cut("a"), _cut("b")]})
        self.assertEqual({row["status"] for row in report["findings"]},
                         {"unsupported"})
        self.assertFalse(report["fullyEditable"])
        self.assertTrue(report["mirrorReady"])
        self.assertEqual(report["mirrorBlockers"], [])


if __name__ == "__main__":
    unittest.main()
