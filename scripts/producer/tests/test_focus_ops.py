"""Image-focus operators (LIAM-4-MOVES move 3, measured 2026-07-11 EC2 R2).

Pins: the op vocabulary + region/window validation (executor's own parser),
the filter grammar per op (highlight wipe / darken+blur surround / signed
hue shift per hue_shift_semantics), the broll_insert threading, the lint
treatment gate, and an ffmpeg render probe showing darken-surround really
dims OUTSIDE the region while the focus tile stays bright.
"""
import json
import os
import re
import subprocess
import tempfile
import unittest

from _common import *  # noqa: F401,F403

REGION = [0.25, 0.25, 0.5, 0.5]


def _op(op="darken-surround", **extra) -> dict:
    d = {"op": op, "atS": 0.5, "holdS": 1.5}
    if op != "hue-shift-signed":
        d["region"] = REGION
    else:
        d["sign"] = "negative"
    d.update(extra)
    return d


class FocusOpsParseTests(unittest.TestCase):
    """focus_ops.parse_ops — the single validator (lint + executor)."""

    def test_absent_is_empty(self) -> None:
        self.assertEqual(focp.parse_ops(None, 5.0), ())

    def test_full_vocabulary_parses(self) -> None:
        ops = focp.parse_ops(
            [_op("highlight"), _op("darken-surround", atS=2.2),
             _op("blur-surround", atS=3.9, holdS=1.0),
             _op("hue-shift-signed", atS=0.0, holdS=2.0)], 5.0)
        self.assertEqual([o.op for o in ops],
                         ["highlight", "darken-surround", "blur-surround",
                          "hue-shift-signed"])
        self.assertAlmostEqual(ops[0].wipe_s,
                               plm.MOTION["focus_ops"]["highlight"]["wipe_s"])
        self.assertAlmostEqual(ops[3].ramp_s,
                               plm.MOTION["focus_ops"]["hue_shift"]["ramp_s"])

    def test_unknown_op_and_bad_sign_rejected(self) -> None:
        with self.assertRaises(ValueError):
            focp.parse_ops([_op("sparkle")], 5.0)
        with self.assertRaises(ValueError):
            focp.parse_ops([_op("hue-shift-signed", sign="sideways")], 5.0)

    def test_region_required_and_bounded(self) -> None:
        bad = _op("darken-surround")
        del bad["region"]
        with self.assertRaises(ValueError):
            focp.parse_ops([bad], 5.0)
        with self.assertRaises(ValueError):
            focp.parse_ops([_op(region=[0.8, 0.8, 0.5, 0.5])], 5.0)
        with self.assertRaises(ValueError):
            focp.parse_ops([_op(region=[0.1, 0.1, 0.01, 0.5])], 5.0)

    def test_window_must_fit_the_insert(self) -> None:
        with self.assertRaises(ValueError):
            focp.parse_ops([_op(atS=4.0, holdS=1.5)], 5.0)

    def test_same_op_overlap_rejected_stacking_allowed(self) -> None:
        with self.assertRaises(ValueError):                 # two highlights
            focp.parse_ops([_op("highlight", atS=0.5, holdS=2.0),
                            _op("highlight", atS=1.0, holdS=1.0)], 5.0)
        ops = focp.parse_ops([_op("highlight", atS=0.5, holdS=1.0),
                              _op("darken-surround", atS=0.5, holdS=1.5)], 5.0)
        self.assertEqual(len(ops), 2)                       # stacking legal


class FocusOpsFilterTests(unittest.TestCase):
    """branch_parts — the measured filter grammar per op."""

    def _parts(self, raw: dict) -> str:
        ops = focp.parse_ops([raw], 5.0)
        return ";".join(focp.branch_parts(ops, (640, 360, 10.0), "f0", "b0"))

    def test_highlight_is_a_left_to_right_wipe(self) -> None:
        # drawbox has NO time variable (its 't' is THICKNESS — LL-017): the
        # wipe must be a ladder of static widths, one per step, first slice
        # gated at the attack and the full-width box holding to the end.
        fc = self._parts(_op("highlight"))
        widths = [int(m.split("=")[1]) for m in
                  re.findall(r"w=\d+", fc)]
        self.assertEqual(len(widths), 12)                     # 0.4s @ 30/s
        self.assertEqual(widths, sorted(widths))              # grows L→R
        self.assertLess(widths[0], 40)                        # starts thin
        self.assertEqual(widths[-1], 320)                     # full region
        self.assertIn("between(t,10.500000,", fc)             # attack slice
        self.assertIn(",12.000000)", fc)                      # holds to end
        self.assertNotIn("clip((t", fc)                       # the LL-017 trap
        self.assertIn(plm.MOTION["focus_ops"]["highlight"]["color"], fc)

    def test_darken_surround_dims_everything_but_the_tile(self) -> None:
        fc = self._parts(_op("darken-surround"))
        self.assertIn("lutyuv=y='val*0.75'", fc)                # −25% luma
        self.assertIn("crop=320:180:160:90", fc)                # focus tile
        self.assertIn("overlay=x=160:y=90", fc)                 # tile restored

    def test_blur_surround_swaps_dim_for_gaussian(self) -> None:
        fc = self._parts(_op("blur-surround"))
        self.assertIn("gblur", fc)
        self.assertNotIn("lutyuv", fc)

    def test_hue_shift_signed_semantics(self) -> None:
        neg = self._parts(_op("hue-shift-signed"))
        uv = plm.MOTION["focus_ops"]["hue_shift"]["uv"]
        self.assertIn(f"{uv['red'][0]:.1f}", neg)               # red chroma
        # geq's time variable is UPPERCASE T — lowercase t only lives in the
        # enable= timeline gate (ffmpeg 8 rejects t inside geq; c0679 verify).
        self.assertIn("clip((T-10.500000)/0.233000,0,1)", neg)  # real-use ramp
        self.assertNotIn("(t-", neg)      # the exact shape ffmpeg 8 rejected
        pos = self._parts(_op("hue-shift-signed", sign="positive", rampS=0))
        self.assertIn(f"{uv['yellow'][0]:.1f}", pos)            # yellow first
        self.assertIn(f"{uv['green'][0] - uv['yellow'][0]:.1f}", pos)

    def test_ops_chain_sequentially(self) -> None:
        ops = focp.parse_ops([_op("highlight", atS=0.5, holdS=1.0),
                              _op("darken-surround", atS=2.0, holdS=1.0)], 5.0)
        parts = focp.branch_parts(ops, (640, 360, 0.0), "f0", "b0")
        self.assertIn("[f0]", parts[0])
        self.assertTrue(parts[-1].endswith("[b0]"), parts[-1])


class FocusOpsInsertTests(unittest.TestCase):
    """broll_insert threading + plan lint treatment gate."""

    def test_insert_parse_threads_focus_ops(self) -> None:
        inserts = bi.parse_inserts(
            [{"assetId": "a", "outStart": 2.0, "outEnd": 5.0,
              "focusOps": [_op()]}], 30.0, 8.0)
        self.assertEqual(len(inserts[0].focus_ops), 1)
        self.assertEqual(inserts[0].focus_ops[0].op, "darken-surround")
        with self.assertRaises(ValueError):                 # bad ops surface
            bi.parse_inserts(
                [{"assetId": "a", "outStart": 2.0, "outEnd": 5.0,
                  "focusOps": [_op("sparkle")]}], 30.0, 8.0)

    def _lint(self, mutate) -> "pl.Report":
        plan = good_plan()
        plan["brollTrack"][0]["outEnd"] = 13.0   # room for a 1.5s hold
        plan["brollTrack"][0]["focusOps"] = [_op()]
        mutate(plan)
        return pl.lint(plan, MANIFEST)

    def test_produced_plan_with_ops_lints_clean(self) -> None:
        rep = self._lint(lambda p: None)
        self.assertEqual([e for e in rep.errors if "focus" in e.lower()], [],
                         rep.errors)

    def test_clean_cut_treatment_gate(self) -> None:
        rep = self._lint(lambda p: p["target"].update(treatment="clean-cut"))
        self.assertTrue(any("clean cut" in e for e in rep.errors), rep.errors)

    def test_off_band_hold_warns(self) -> None:
        rep = self._lint(lambda p: p["brollTrack"][0]["focusOps"].__setitem__(
            0, _op(holdS=3.4)))
        self.assertTrue(any("measured band" in w for w in rep.warnings),
                        rep.warnings)

    def test_bad_ops_are_lint_errors(self) -> None:
        rep = self._lint(lambda p: p["brollTrack"][0]["focusOps"].__setitem__(
            0, _op(region=[2, 2, 3, 3])))
        self.assertTrue(any("region" in e for e in rep.errors), rep.errors)


@unittest.skipUnless(_HAVE_FFMPEG, "ffmpeg not on PATH")
class FocusOpsRenderTests(unittest.TestCase):
    """darken-surround measurably dims outside the region, not inside."""

    def _yavg(self, path: str, t: float, crop: str) -> float:
        out = tr.run_ff(
            ["ffprobe", "-v", "error", "-f", "lavfi",
             f"movie={path},trim=start={t}:end={t + 0.05},{crop},signalstats",
             "-show_entries", "frame_tags=lavfi.signalstats.YAVG",
             "-of", "default=noprint_wrappers=1:nokey=1"])
        return float(out.strip().splitlines()[0])

    def test_darken_surround_render(self) -> None:
        with tempfile.TemporaryDirectory(prefix="focusops-") as tmp:
            base = os.path.join(tmp, "base.mp4")
            asset = os.path.join(tmp, "asset.mp4")
            out = os.path.join(tmp, "out.mp4")
            for path, color in ((base, "gray"), (asset, "white")):
                subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                     "-i", f"color=c={color}:s=640x360:d=8:r=30",
                     "-c:v", "libx264", "-crf", "12", "-pix_fmt",
                     "yuv420p", path], check=True)
            manifest = {"_path": os.path.join(tmp, "m.json"),
                        "broll": [{"id": "shot", "path": asset}]}
            inserts = bi.parse_inserts(
                [{"assetId": "shot", "outStart": 2.0, "outEnd": 6.0,
                  "focusOps": [{"op": "darken-surround", "region": REGION,
                                "atS": 1.0, "holdS": 2.0}]}], 8.0, 8.0)
            inserts = bi.resolve_assets(inserts, manifest)
            result = bi.apply_broll_inserts(base, inserts, out)
            self.assertEqual(result["focusOps"], 1)
            self.assertEqual(result["inFrames"], result["outFrames"])
            # during the hold (t=4): tile bright, surround dimmed ~25%
            tile = self._yavg(out, 4.0, "crop=320:180:160:90")
            edge = self._yavg(out, 4.0, "crop=160:90:0:0")
            self.assertGreater(tile, 220.0, tile)
            self.assertLess(edge, 200.0, edge)
            self.assertAlmostEqual(edge / tile, 0.75, delta=0.06)
            # outside the hold (t=2.5): no dim anywhere
            edge_before = self._yavg(out, 2.5, "crop=160:90:0:0")
            self.assertGreater(edge_before, 220.0, edge_before)

    def _cavg(self, path: str, t: float, key: str) -> float:
        out = tr.run_ff(
            ["ffprobe", "-v", "error", "-f", "lavfi",
             f"movie={path},trim=start={t}:end={t + 0.05},signalstats",
             "-show_entries", f"frame_tags=lavfi.signalstats.{key}",
             "-of", "default=noprint_wrappers=1:nokey=1"])
        return float(out.strip().splitlines()[0])

    def test_hue_shift_negative_renders_red(self) -> None:
        """The geq chroma fill must build AND pull toward the red target —
        the render-side guard for the geq T-vs-t trap (c0679 verify)."""
        cfg = plm.MOTION["focus_ops"]["hue_shift"]
        with tempfile.TemporaryDirectory(prefix="focusops-") as tmp:
            base = os.path.join(tmp, "base.mp4")
            asset = os.path.join(tmp, "asset.mp4")
            out = os.path.join(tmp, "out.mp4")
            for path, color in ((base, "gray"), (asset, "white")):
                subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                     "-i", f"color=c={color}:s=640x360:d=8:r=30",
                     "-c:v", "libx264", "-crf", "12", "-pix_fmt",
                     "yuv420p", path], check=True)
            manifest = {"_path": os.path.join(tmp, "m.json"),
                        "broll": [{"id": "shot", "path": asset}]}
            inserts = bi.resolve_assets(bi.parse_inserts(
                [{"assetId": "shot", "outStart": 2.0, "outEnd": 6.0,
                  "focusOps": [{"op": "hue-shift-signed", "sign": "negative",
                                "atS": 1.0, "holdS": 2.0}]}], 8.0, 8.0),
                manifest)
            bi.apply_broll_inserts(base, inserts, out)
            # during the hold (t=4): chroma pulled ``mix`` toward red uv.
            mix, (tu, tv) = cfg["mix"], cfg["uv"]["red"]
            self.assertAlmostEqual(self._cavg(out, 4.0, "UAVG"),
                                   128 + mix * (tu - 128), delta=6.0)
            self.assertAlmostEqual(self._cavg(out, 4.0, "VAVG"),
                                   128 + mix * (tv - 128), delta=6.0)
            # before the op (t=2.5): the white still is chroma-neutral.
            self.assertAlmostEqual(self._cavg(out, 2.5, "UAVG"), 128, delta=3)
            self.assertAlmostEqual(self._cavg(out, 2.5, "VAVG"), 128, delta=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
