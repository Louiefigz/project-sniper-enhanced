"""assemble tests — the incremental-graphics base fingerprint + composite guards.

Covers the CHEAP, deterministic surface (no ffmpeg): the base fingerprint that
decides base reuse vs re-render, the staleness check, and the eof_action=pass
graph injection that guards the duplicate-frame stutter. The ffmpeg composite +
YDIF ratio are exercised by the e2e render, not here.
"""
import ast
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403
from edit.refit_authority import RECEIPT_NAME, commit_pending


class BaseFingerprintTests(unittest.TestCase):
    """A graphics-only edit must reuse the base; anything else re-renders it."""

    def _plan(self) -> dict:
        return {
            "cutTrack": [{"sourceId": "raw-1", "start": 1.0, "end": 2.0}],
            "punchIns": [{"outStart": 1.0, "outEnd": 2.0, "zoom": 1.1}],
            "transitions": [{"outTime": 1.5, "kind": "light-leak"}],
            "captions": {"burn": False},
            "graphicsTrack": [{"kind": "stat-card", "outStart": 1.0, "outEnd": 2.0}],
            "target": {"mode": "longform"},
            "planVersion": 3,
        }

    def test_graphics_only_edit_keeps_fingerprint(self) -> None:
        p = self._plan()
        f0 = asm.base_fingerprint(p)
        p["graphicsTrack"].append({"kind": "chip-row", "outStart": 3.0, "outEnd": 4.0})
        p["planVersion"] = 9                      # a re-plan bump must NOT invalidate the base
        self.assertEqual(asm.base_fingerprint(p), f0)

    def test_longform_rail_edit_invalidates_cross_lane_base(self) -> None:
        p = self._plan()
        p["graphicsTrack"] = [{
            "kind": "glass-rail", "anchor": "free-band",
            "outStart": 1.0, "outEnd": 4.0, "spec": {"side": "left"},
        }]
        f0 = asm.base_fingerprint(p)
        p["graphicsTrack"][0]["spec"]["side"] = "right"
        self.assertNotEqual(asm.base_fingerprint(p), f0)

    def test_caption_suppression_window_invalidates_base(self) -> None:
        p = self._plan()
        p["graphicsTrack"][0].update({
            "anchor": "own-screen", "outStart": 1.0, "outEnd": 2.0,
        })
        f0 = asm.base_fingerprint(p)
        p["graphicsTrack"][0]["outEnd"] = 2.5
        self.assertNotEqual(asm.base_fingerprint(p), f0)

    def test_regular_scene_payload_still_reuses_base(self) -> None:
        p = self._plan()
        p["graphicsTrack"][0]["spec"] = {"text": "Before"}
        f0 = asm.base_fingerprint(p)
        p["graphicsTrack"][0]["spec"]["text"] = "After"
        self.assertEqual(asm.base_fingerprint(p), f0)

    def test_cut_change_flips_fingerprint(self) -> None:
        p = self._plan()
        f0 = asm.base_fingerprint(p)
        p["cutTrack"][0]["end"] = 5.0
        self.assertNotEqual(asm.base_fingerprint(p), f0)

    def test_zoom_and_transition_changes_flip_fingerprint(self) -> None:
        p = self._plan()
        f0 = asm.base_fingerprint(p)
        p["punchIns"][0]["zoom"] = 1.2
        self.assertNotEqual(asm.base_fingerprint(p), f0)
        p = self._plan()
        p["transitions"][0]["outTime"] = 1.6
        self.assertNotEqual(asm.base_fingerprint(p), f0)

    def test_underscore_keys_excluded(self) -> None:
        # Derived/scratch keys (e.g. injected `_path`) must not affect the base.
        p = self._plan()
        f0 = asm.base_fingerprint(p)
        p["_scratch"] = {"anything": 1}
        self.assertEqual(asm.base_fingerprint(p), f0)

    def test_music_only_edit_keeps_fingerprint(self) -> None:
        # music is applied at ASSEMBLE time (audio-only, post-master) — adding,
        # editing, or removing it must never trigger a base rebuild.
        p = self._plan()
        f0 = asm.base_fingerprint(p)
        p["music"] = {"enabled": True, "path": "/x/bed.mp3", "duck": False,
                      "gapDb": 12}
        self.assertEqual(asm.base_fingerprint(p), f0)
        p["music"]["gapDb"] = 8
        self.assertEqual(asm.base_fingerprint(p), f0)

    def test_base_side_audio_fields_flip_fingerprint(self) -> None:
        # audioEnhance/audioGain run pre-master (BASE side) — unlike music,
        # editing them must flip the fingerprint and force a base rebuild.
        p = self._plan()
        f0 = asm.base_fingerprint(p)
        p["audioEnhance"] = {"preset": "voice"}
        self.assertNotEqual(asm.base_fingerprint(p), f0)
        p = self._plan()
        p["audioGain"] = [{"outStart": 1.0, "outEnd": 2.0, "dB": -3}]
        self.assertNotEqual(asm.base_fingerprint(p), f0)


class MusicResolveTests(unittest.TestCase):
    """music_stage.resolve_music_track: path route, manifest route, loud failures."""

    def test_absolute_existing_path_resolves(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp3") as fh:
            self.assertEqual(amus.resolve_music_track({"path": fh.name}, None),
                             fh.name)

    def test_relative_path_fails_loudly(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "absolute"):
            amus.resolve_music_track({"path": "tracks/bed.mp3"}, None)

    def test_asset_id_without_fingerprint_fails_loudly(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "fingerprint"):
            amus.resolve_music_track({"assetId": "music-1"}, None)

    def test_asset_id_resolves_via_fingerprint_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            track = os.path.join(d, "bed.mp3")
            with open(track, "wb") as f:
                f.write(b"x")
            manifest = os.path.join(d, "manifest.json")
            with open(manifest, "w") as f:
                json.dump({"music": [{"id": "music-1", "path": track}]}, f)
            fp = os.path.join(d, "base.fingerprint.json")
            with open(fp, "w") as f:
                json.dump({"fingerprint": "abc", "manifestPath": manifest}, f)
            self.assertEqual(
                amus.resolve_music_track({"assetId": "music-1"}, fp), track)
            with self.assertRaisesRegex(RuntimeError, "does not resolve"):
                amus.resolve_music_track({"assetId": "music-9"}, fp)

    def _manifest_with_track(self, d: str) -> tuple[str, str]:
        track = os.path.join(d, "bed.mp3")
        with open(track, "wb") as f:
            f.write(b"x")
        manifest = os.path.join(d, "manifest.json")
        with open(manifest, "w") as f:
            json.dump({"music": [{"id": "music-1", "path": track}]}, f)
        return manifest, track

    def test_asset_id_resolves_via_explicit_manifest_no_fingerprint(self) -> None:
        # F8 regression: a --manifest in hand must resolve music.assetId with
        # NO fingerprint file — never burn the composite then die on
        # "needs --fingerprint".
        with tempfile.TemporaryDirectory() as d:
            manifest, track = self._manifest_with_track(d)
            self.assertEqual(
                amus.resolve_music_track({"assetId": "music-1"}, None, manifest),
                track)

    def test_explicit_manifest_wins_over_fingerprint_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            manifest, track = self._manifest_with_track(d)
            fp = os.path.join(d, "base.fingerprint.json")
            with open(fp, "w") as f:      # recorded manifest is GONE — arg wins
                json.dump({"fingerprint": "abc",
                           "manifestPath": os.path.join(d, "gone.json")}, f)
            self.assertEqual(
                amus.resolve_music_track({"assetId": "music-1"}, fp, manifest),
                track)

    def test_missing_explicit_manifest_fails_loudly(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "does not exist"):
            amus.resolve_music_track({"assetId": "music-1"}, None,
                                     "/nope/never/manifest.json")


class StalenessTests(unittest.TestCase):
    """Missing and stale fingerprints stop the direct assembly route."""

    def _emit_capture(self, plan: dict, recorded: str | None):
        import io
        import contextlib
        with tempfile.TemporaryDirectory() as d:
            fp = None
            if recorded is not None:
                fp = os.path.join(d, "base.fingerprint.json")
                with open(fp, "w") as f:
                    json.dump({"fingerprint": recorded}, f)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                asm._check_staleness(plan, fp)
            return buf.getvalue()

    def test_matching_fingerprint_is_silent(self) -> None:
        p = BaseFingerprintTests()._plan()
        out = self._emit_capture(p, asm.base_fingerprint(p))
        self.assertNotIn("base_stale", out)

    def test_drifted_fingerprint_refuses(self) -> None:
        p = BaseFingerprintTests()._plan()
        with self.assertRaisesRegex(RuntimeError, "base is stale"):
            self._emit_capture(p, "deadbeefdeadbeef")

    def test_no_fingerprint_file_refuses(self) -> None:
        p = BaseFingerprintTests()._plan()
        with self.assertRaisesRegex(RuntimeError, "unverifiable"):
            self._emit_capture(p, None)


class EofGuardTests(unittest.TestCase):
    """eof_action=pass must be off by default (byte-stable) and on when asked."""

    def _clips(self) -> list[dict]:
        return [{"outStart": 2.0, "outEnd": 4.0, "anchor": "free-band", "x": 0, "y": 0},
                {"outStart": 5.0, "outEnd": 7.0, "anchor": "free-band", "x": 8, "y": 9}]

    def test_default_graph_has_no_eof_action(self) -> None:
        from graphics.graphics_stage import _build_graph
        graph, _ = _build_graph(self._clips(), False)
        self.assertNotIn("eof_action", graph)

    def test_eof_pass_injects_on_every_graphic_overlay(self) -> None:
        from graphics.graphics_stage import _build_graph
        graph, _ = _build_graph(self._clips(), True)
        self.assertEqual(graph.count("eof_action=pass"), 2)


class AutoBaseDispatchTests(unittest.TestCase):
    """--auto-base decides: current → reuse, stale/missing → rebuild, no fp → warn."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.plan = {"cutTrack": [{"sourceId": "r", "start": 0.0, "end": 2.0}],
                     "graphicsTrack": [], "target": {"mode": "longform"}}
        self.base = os.path.join(self.tmp.name, "base_final.mp4")
        self.fp = os.path.join(self.tmp.name, "base.fingerprint.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, base: bool, fingerprint: str | None) -> None:
        if base:
            with open(self.base, "wb") as f:
                f.write(b"x")
        if fingerprint is not None:
            from test_base_reuse import bound_record
            record = bound_record(self.base, self.plan) if base else {}
            with open(self.fp, "w") as f:
                from audio.master import MASTERING_POLICY_VERSION
                json.dump({**record, "fingerprint": fingerprint,
                           "masteringPolicyVersion": MASTERING_POLICY_VERSION}, f)

    def test_current_base_is_reused(self) -> None:
        self._write(base=True, fingerprint=asm.base_fingerprint(self.plan))
        self.assertEqual(asm._base_state(self.base, self.plan, self.fp), "current")

    def test_cut_edit_makes_base_stale(self) -> None:
        self._write(base=True, fingerprint=asm.base_fingerprint(self.plan))
        self.plan["cutTrack"][0]["end"] = 9.0
        self.assertEqual(asm._base_state(self.base, self.plan, self.fp), "stale")

    def test_missing_base_reports_missing(self) -> None:
        self._write(base=False, fingerprint=asm.base_fingerprint(self.plan))
        self.assertEqual(asm._base_state(self.base, self.plan, self.fp), "missing")

    def test_base_without_fingerprint_is_unverifiable(self) -> None:
        self._write(base=True, fingerprint=None)
        self.assertEqual(asm._base_state(self.base, self.plan, self.fp), "unverifiable")

    def test_rebuild_without_manifest_fails_loudly(self) -> None:
        self._write(base=True, fingerprint="deadbeefdeadbeef")
        with open(self.fp, "w") as handle:
            json.dump({"fingerprint": "deadbeefdeadbeef"}, handle)  # old, unbound receipt
        plan_path = os.path.join(self.tmp.name, "edit_plan.json")
        with open(plan_path, "w") as f:
            json.dump(self.plan, f)
        with self.assertRaisesRegex(RuntimeError, "no manifest"):
            asm.ensure_base(self.base, plan_path, self.plan, self.fp, manifest=None)

    def test_unverifiable_base_without_rebuild_manifest_fails_closed(self) -> None:
        self._write(base=True, fingerprint=None)
        plan_path = os.path.join(self.tmp.name, "edit_plan.json")
        with open(plan_path, "w") as f:
            json.dump(self.plan, f)
        with self.assertRaisesRegex(RuntimeError, "no manifest"):
            asm.ensure_base(self.base, plan_path, self.plan, self.fp, manifest=None)


class _StubProc:
    """Popen stand-in for ensure_base's render subprocess."""

    stdout: list = []

    def __init__(self, code: int) -> None:
        self._code = code

    def wait(self) -> int:
        return self._code


class TransactionalRefitTests(unittest.TestCase):
    """F2: the refit is staged, promoted only AFTER a successful rebuild.

    A failed rebuild must leave the operator's plan_path byte-identical so a
    retry re-runs the IDENTICAL refit from the same base_plan.json snapshot —
    the old write-before-rebuild flow double-refit every window on retry
    (silent drift).
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.base = os.path.join(d, "base_final.mp4")
        with open(self.base, "wb") as f:
            f.write(b"x")
        self.manifest = os.path.join(d, "asset_manifest.json")
        with open(self.manifest, "w") as f:
            json.dump({"sources": []}, f)
        old_plan = {"cutTrack": [{"sourceId": "raw", "start": 0.0, "end": 30.0}],
                    "audioGain": [{"outStart": 20.0, "outEnd": 25.0, "dB": -6.0}],
                    "graphicsTrack": [], "target": {"mode": "longform"}}
        self.fp = os.path.join(d, "base.fingerprint.json")
        with open(self.fp, "w") as f:
            json.dump({"fingerprint": asm.base_fingerprint(old_plan),
                       "manifestPath": self.manifest}, f)
        with open(os.path.join(d, "base_plan.json"), "w") as f:
            json.dump(old_plan, f)
        # The EDIT: cut source 8-13 out; windows still in the OLD timebase.
        self.plan = json.loads(json.dumps(old_plan))
        self.plan["cutTrack"] = [{"sourceId": "raw", "start": 0.0, "end": 8.0},
                                 {"sourceId": "raw", "start": 13.0, "end": 30.0}]
        self.plan_path = os.path.join(d, "edit_plan.json")
        with open(self.plan_path, "w") as f:
            json.dump(self.plan, f, indent=1)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _ensure_base(self, popen) -> str:
        buf = io.StringIO()
        with mock.patch.object(asm.subprocess, "Popen", new=popen), \
                contextlib.redirect_stdout(buf):
            asm.ensure_base(self.base, self.plan_path,
                            json.loads(json.dumps(self.plan)), self.fp,
                            manifest=None)
        return buf.getvalue()

    def _commit_first_refit(self) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            refitted, staged = asm._refit_for_rebuild(
                self.plan_path, json.loads(json.dumps(self.plan)), self.fp)
        self.assertIsNotNone(staged)
        os.replace(staged, self.plan_path)
        commit_pending(self.tmp.name, self.plan_path)
        self.plan = refitted
        return refitted

    def test_failed_rebuild_leaves_plan_untouched_and_refit_idempotent(self) -> None:
        with open(self.plan_path, "rb") as f:
            before = f.read()
        calls: list[list] = []

        def fail_popen(cmd, **_kw) -> _StubProc:
            calls.append(cmd)
            return _StubProc(1)

        with self.assertRaisesRegex(RuntimeError, "base rebuild failed"):
            self._ensure_base(fail_popen)
        with open(self.plan_path, "rb") as f:
            self.assertEqual(f.read(), before)     # operator's plan untouched
        with open(os.path.join(self.tmp.name, "base_plan.json")) as f:
            self.assertEqual(json.load(f)["cutTrack"][0]["end"], 30.0)
        # The rebuild subprocess got the STAGED refit, not the operator's plan.
        self.assertTrue(any(str(a).endswith(".refit.json") for a in calls[0]))
        # Retry: the refit from the same snapshot is identical (no double shift).
        with contextlib.redirect_stdout(io.StringIO()):
            r1, s1 = asm._refit_for_rebuild(
                self.plan_path, json.loads(json.dumps(self.plan)), self.fp)
            r2, s2 = asm._refit_for_rebuild(
                self.plan_path, json.loads(json.dumps(self.plan)), self.fp)
        self.assertEqual(r1["audioGain"], r2["audioGain"])
        self.assertEqual(r1["audioGain"][0]["outStart"], 15.0)  # ONE shift only
        self.assertTrue(s1 and s2 and s1 == s2)

    def test_surgical_receipt_skips_second_rebuild_refit(self) -> None:
        once = self._commit_first_refit()
        self.assertEqual(once["audioGain"][0]["outStart"], 15.0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            twice, staged = asm._refit_for_rebuild(
                self.plan_path, json.loads(json.dumps(once)), self.fp)
        self.assertIsNone(staged)
        self.assertEqual(twice["audioGain"][0]["outStart"], 15.0)
        self.assertIn("refit_already_applied", buf.getvalue())

    def test_non_cut_change_keeps_applied_timebase(self) -> None:
        current = self._commit_first_refit()
        current["graphicsTrack"].append({"kind": "quote-card",
                                         "outStart": 2.0, "outEnd": 4.0})
        with open(self.plan_path, "w") as f:
            json.dump(current, f)
        with contextlib.redirect_stdout(io.StringIO()):
            resolved, staged = asm._refit_for_rebuild(
                self.plan_path, current, self.fp)
        self.assertIsNone(staged)
        self.assertEqual(resolved["audioGain"][0]["outStart"], 15.0)

    def test_second_cut_refits_from_last_target_once(self) -> None:
        current = self._commit_first_refit()
        current["cutTrack"] = [
            {"sourceId": "raw", "start": 0.0, "end": 8.0},
            {"sourceId": "raw", "start": 13.0, "end": 15.0},
            {"sourceId": "raw", "start": 17.0, "end": 30.0},
        ]
        with open(self.plan_path, "w") as f:
            json.dump(current, f, indent=1)
        with contextlib.redirect_stdout(io.StringIO()):
            refitted, staged = asm._refit_for_rebuild(
                self.plan_path, current, self.fp)
        self.assertIsNotNone(staged)
        self.assertEqual(refitted["audioGain"][0]["outStart"], 13.0)

    def test_malformed_receipt_fails_closed(self) -> None:
        with open(os.path.join(self.tmp.name, RECEIPT_NAME), "w") as f:
            f.write("{broken")
        with self.assertRaisesRegex(RuntimeError, "not valid JSON"):
            asm._refit_for_rebuild(self.plan_path, self.plan, self.fp)

    def test_successful_rebuild_promotes_the_staged_refit(self) -> None:
        def ok_popen(cmd, **_kw) -> _StubProc:
            base_dir = cmd[4]          # [python, render.py, plan, manifest, dir, flag]
            with open(os.path.join(base_dir, "final.mp4"), "wb") as f:
                f.write(b"newbase")
            with open(os.path.join(base_dir, "timeline_map.json"), "w") as f:
                json.dump({"duration": 25.0}, f)
            with open(os.path.join(base_dir, "cover.png"), "wb") as f:
                f.write(b"png")
            with open(os.path.join(base_dir, "render_report.json"), "w") as f:
                json.dump({"status": "done"}, f)
            with open(os.path.join(base_dir, "captions.srt"), "w") as f:
                f.write("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
            with open(os.path.join(base_dir, "base.fingerprint.json"), "w") as f:
                json.dump({"fingerprint": "rebuilt"}, f)
            return _StubProc(0)

        out = self._ensure_base(ok_popen)
        self.assertIn("refit_written", out)        # emitted AFTER promotion
        with open(self.plan_path) as f:
            promoted = json.load(f)
        self.assertEqual(promoted["audioGain"][0]["outStart"], 15.0)
        self.assertFalse(os.path.exists(self.plan_path + ".refit.json"))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp.name, "timeline_map.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp.name, "cover.png")))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp.name, "render_report.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp.name, "captions.srt")))
        with open(os.path.join(self.tmp.name, "base_plan.json")) as f:
            self.assertEqual(json.load(f)["cutTrack"], promoted["cutTrack"])


@unittest.skipUnless(_HAVE_FFMPEG, "ffmpeg not installed")
class YdifProbeTests(unittest.TestCase):
    """F4: the smoothness probe must FAIL on unreadable output, never 0.0.

    Returning 0.0 (= "smooth, ok") when ffmpeg fails or emits no YDIF lines
    passes the guard exactly when the output can't be verified.
    """

    def test_nonexistent_path_raises(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "probe failed"):
            asm._ydif_dup_ratio("/nope/never/assembled.mp4")


class RenderStageOrderTests(unittest.TestCase):
    """F3/F5 source-level pins on render.py's render() (read, not imported —
    the module pulls renderer deps that the assemble tests don't need)."""

    def _render_body(self) -> str:
        render_py = os.path.join(os.path.dirname(os.path.abspath(asm.__file__)),
                                 "render.py")
        with open(render_py) as f:
            src = f.read()
        return src.split("\ndef render(")[1].split("\ndef ")[0]

    def test_enhance_runs_before_transitions(self) -> None:
        # F3: enhance must clean the PURE dialogue bus. After transitions,
        # 'separate' (Demucs residual -60dB) / voice-rnn would delete the
        # authored whoosh SFX amixed into the program.
        body = ast.parse("def render(" + self._render_body())
        calls = [node for node in ast.walk(body) if isinstance(node, ast.Call)]
        stages = {}
        for call in calls:
            name = call.func.id if isinstance(call.func, ast.Name) else None
            if name == "source_color_stage" and len(call.args) > 1:
                stage = call.args[1]
                name = stage.id if isinstance(stage, ast.Name) else None
            if name in {"enhance_stage", "transitions_stage"}:
                stages.setdefault(name, []).append(call.lineno)
        self.assertEqual(set(stages), {"enhance_stage", "transitions_stage"})
        self.assertEqual(len(stages["enhance_stage"]), 1)
        self.assertEqual(len(stages["transitions_stage"]), 1)
        self.assertLess(stages["enhance_stage"][0], stages["transitions_stage"][0])

    def test_monolithic_render_warns_music_not_applied(self) -> None:
        # F5: plan.music is assemble-time; the monolithic path must warn
        # loudly, never silently ship a music-less master.
        self.assertIn("music_not_applied", self._render_body())


if __name__ == "__main__":
    unittest.main(verbosity=2)
