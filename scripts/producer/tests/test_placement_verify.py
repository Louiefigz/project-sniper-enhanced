"""verify_placement default-on (contract v3 item #5).

The SNIPER_VERIFY_PLACEMENT env gate is gone: run_graphics_stage verifies
anchor-resolved face placements by default. WARN mode (uncalibrated) NEVER
raises on a hit — log + continue (the wedge-after-wall class stays dead);
the allow-vocabulary SKIPs pip_hole comps, brollTrack overlaps, and
hook-card overlays with evidence; operator-explicit pins WARN and never
FAIL; environment failures SKIP in every mode; calibrated FAIL mode blocks.
"""
import inspect
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403

import gate_policy
from graphics import graphics_stage as gstage
from graphics import placement_verify as pv


def _clip(**over) -> dict:
    base = {"path": "c.mov", "outStart": 4.0, "outEnd": 6.0,
            "anchor": "headroom", "x": 10, "y": 20,
            "placedBBox": [100, 100, 300, 200]}
    base.update(over)
    return base


class _Emit:
    """Recording emitter standing in for graphics_stage.emit."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def __call__(self, **fields) -> None:
        self.rows.append(fields)

    def by_status(self, status: str) -> list[dict]:
        return [r for r in self.rows if r.get("status") == status]


def _ctx(severity: str = "WARN", occlusions: dict | None = None,
         note: str | None = None) -> tuple[pv.VerifyContext, _Emit]:
    rec = _Emit()
    return pv.VerifyContext(severity=severity, occlusions=occlusions,
                            emit=rec, note=note), rec


_MISS = (False, {"ok": False, "intersection": 120.0, "gapPx": -12.0,
                 "hairMeasured": True, "expandedFace": [90, 90, 400, 400],
                 "placedBBox": [100, 100, 300, 200]})


class DefaultOnTests(unittest.TestCase):
    """The env gate is dead; run_graphics_stage always verifies."""

    def test_env_gate_is_gone_from_the_stage_source(self) -> None:
        self.assertNotIn("SNIPER_VERIFY_PLACEMENT",
                         inspect.getsource(gstage))

    def test_run_graphics_stage_invokes_verify_by_default(self) -> None:
        clip = _clip()
        job = gstage.GraphicsJob(video_in="in.mp4", video_out="out.mp4",
                                 track=[{"outStart": 4.0, "outEnd": 6.0,
                                         "kind": "chip-row"}])
        with mock.patch.object(gstage, "_render_all",
                               return_value=([clip], [])), \
             mock.patch.object(gstage, "_probe_frames", return_value=100), \
             mock.patch.object(gstage, "composite", return_value=1), \
             mock.patch.object(gstage, "run_verify") as verify, \
             mock.patch.object(gstage, "emit"):
            gstage.run_graphics_stage(job)
        verify.assert_called_once()
        clips, out, ctx = verify.call_args.args
        self.assertEqual(clips, [clip])
        self.assertEqual(out, "out.mp4")
        self.assertEqual(ctx.severity, "WARN")   # no ledger → uncalibrated


class WarnModeTests(unittest.TestCase):
    """Uncalibrated hits advise loudly and NEVER raise."""

    def test_warn_mode_hit_logs_and_continues(self) -> None:
        ctx, rec = _ctx("WARN")
        with mock.patch.object(pv, "verify_placement", return_value=_MISS):
            checked = pv.run_verify([_clip()], "final.mp4", ctx)
        self.assertEqual(checked, 1)
        hits = rec.by_status("placement_verify_hit")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["severity"], "WARN")
        self.assertEqual(hits[0]["gate"], pv.VERIFY_GATE)
        self.assertIn("intersects", hits[0]["evidence"])
        verdict = gate_policy.Verdict(pv.VERIFY_GATE, "WARN",
                                      hits[0]["evidence"], lane="graphics")
        self.assertEqual(gate_policy.resolve(verdict, {"mode": "short"}),
                         "advise")

    def test_calibrated_fail_mode_raises(self) -> None:
        ctx, rec = _ctx("FAIL")
        with mock.patch.object(pv, "verify_placement", return_value=_MISS):
            with self.assertRaisesRegex(RuntimeError, "placement verify"):
                pv.run_verify([_clip()], "final.mp4", ctx)
        self.assertEqual(rec.by_status("placement_verify_hit")[0]["severity"],
                         "FAIL")

    def test_environment_failure_skips_in_every_mode(self) -> None:
        for severity in ("WARN", "FAIL"):
            ctx, rec = _ctx(severity)
            with mock.patch.object(pv, "verify_placement",
                                   side_effect=ImportError("No module cv2")):
                pv.run_verify([_clip()], "final.mp4", ctx)   # must not raise
            skip = rec.by_status("placement_verify_skip")[0]
            self.assertEqual(skip["severity"], "SKIP")
            self.assertIn("verify unavailable", skip["evidence"])

    def test_clean_pass_emits_placement_verified(self) -> None:
        ctx, rec = _ctx("FAIL")
        with mock.patch.object(pv, "verify_placement",
                               return_value=(True, {"ok": True, "gapPx": 40.0})):
            pv.run_verify([_clip()], "final.mp4", ctx)
        self.assertEqual(len(rec.by_status("placement_verified")), 1)

    def test_ledger_note_is_declared_before_checking(self) -> None:
        ctx, rec = _ctx("WARN", note="calibration ledger unreadable — x")
        pv.run_verify([], "final.mp4", ctx)
        note = rec.by_status("placement_verify_note")[0]
        self.assertEqual(note["severity"], "WARN")
        self.assertIn("unreadable", note["evidence"])


class SkipVocabularyTests(unittest.TestCase):
    """The A2 allow-vocabulary: SKIP-with-evidence, never a false FAIL."""

    def _skip_row(self, clip: dict, occlusions: dict | None) -> dict:
        ctx, rec = _ctx("FAIL", occlusions=occlusions)
        with mock.patch.object(pv, "verify_placement",
                               side_effect=AssertionError("must not verify")):
            pv.run_verify([clip], "final.mp4", ctx)
        rows = rec.by_status("placement_verify_skip")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["severity"], "SKIP")
        return rows[0]

    def test_pip_hole_comp_skips_with_evidence(self) -> None:
        row = self._skip_row(_clip(pipHole={"crop": [0, 0, 1, 1]}), None)
        self.assertIn("pip_hole", row["evidence"])

    def test_broll_overlap_skips_with_evidence(self) -> None:
        row = self._skip_row(_clip(), {"broll": [[5.0, 6.5]], "cards": []})
        self.assertIn("brollTrack", row["evidence"])

    def test_hook_card_overlap_skips_with_evidence(self) -> None:
        row = self._skip_row(_clip(), {"broll": [], "cards": [[3.0, 4.5]]})
        self.assertIn("hook-card", row["evidence"])

    def test_non_overlapping_occlusions_still_verify(self) -> None:
        ctx, rec = _ctx("WARN", occlusions={"broll": [[8.0, 9.0]],
                                            "cards": [[0.0, 1.0]]})
        with mock.patch.object(pv, "verify_placement",
                               return_value=(True, {"ok": True})) as vp:
            pv.run_verify([_clip()], "final.mp4", ctx)
        vp.assert_called_once()

    def test_non_face_anchors_are_not_checked(self) -> None:
        ctx, _rec = _ctx("FAIL")
        with mock.patch.object(pv, "verify_placement",
                               side_effect=AssertionError("must not verify")):
            checked = pv.run_verify(
                [_clip(anchor="free-band"), _clip(anchor="own-screen")],
                "final.mp4", ctx)
        self.assertEqual(checked, 0)


class ExplicitPinTests(unittest.TestCase):
    """Operator pins are verified but WARN-with-evidence, never FAIL."""

    def test_explicit_pin_hit_warns_even_when_calibrated(self) -> None:
        ctx, rec = _ctx("FAIL")
        with mock.patch.object(pv, "verify_placement", return_value=_MISS):
            pv.run_verify([_clip(placed=True)], "final.mp4", ctx)   # no raise
        hit = rec.by_status("placement_verify_hit")[0]
        self.assertEqual(hit["severity"], "WARN")
        self.assertIn("operator-explicit", hit["evidence"])


class PlacedBBoxTests(unittest.TestCase):
    """A clip without a recorded placedBBox re-probes content + offset."""

    def test_missing_placed_bbox_probes_and_offsets(self) -> None:
        clip = _clip()
        del clip["placedBBox"]
        ctx, _rec = _ctx("WARN")
        with mock.patch.object(pv, "_content_bbox",
                               return_value=(10, 10, 50, 50)), \
             mock.patch.object(pv, "verify_placement",
                               return_value=(True, {"ok": True})) as vp:
            pv.run_verify([clip], "final.mp4", ctx)
        placed = vp.call_args.args[3]
        self.assertEqual(placed, (20, 30, 60, 70))


class SeverityAndOcclusionTests(unittest.TestCase):
    """resolve_severity honors the A3 flag; occlusion_windows shapes plan data."""

    def test_no_producer_dir_is_uncalibrated(self) -> None:
        self.assertEqual(pv.resolve_severity(None), ("WARN", None))

    def test_calibrated_ledger_flips_to_fail(self) -> None:
        with mock.patch.object(pv.geometry_calibration, "calibrated_margin",
                               return_value={"x0": 8.0}):
            self.assertEqual(pv.resolve_severity("/p"), ("FAIL", None))

    def test_uncalibrated_ledger_stays_warn(self) -> None:
        with mock.patch.object(pv.geometry_calibration, "calibrated_margin",
                               return_value=None):
            self.assertEqual(pv.resolve_severity("/p"), ("WARN", None))

    def test_unreadable_ledger_warns_with_a_note(self) -> None:
        with mock.patch.object(pv.geometry_calibration, "calibrated_margin",
                               side_effect=ValueError("bad line")):
            severity, note = pv.resolve_severity("/p")
        self.assertEqual(severity, "WARN")
        self.assertIn("unreadable", note)

    def test_occlusion_windows_collects_broll_and_cards(self) -> None:
        plan = {"brollTrack": [{"outStart": 9.0, "outEnd": 10.5}],
                "titleCards": [{"outStart": 0.0, "outEnd": 2.5, "text": "x"}]}
        self.assertEqual(pv.occlusion_windows(plan),
                         {"broll": [[9.0, 10.5]], "cards": [[0.0, 2.5]]})
        self.assertEqual(pv.occlusion_windows({}),
                         {"broll": [], "cards": []})


if __name__ == "__main__":
    unittest.main(verbosity=2)
