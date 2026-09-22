"""audio fast path tests — split fingerprints, dispatch matrix, sfx fallback, proxy.

Fix set 2026-07-09: an audioGain/audioEnhance edit must NOT cost a full ~98s
base rebuild (of which ~88s re-encodes identical video). The fingerprint is
split (fingerprints.py: video vs audio prints), --auto-base dispatches a
video-match/audio-mismatch to the AUDIO-ONLY bus rebuild (audio/base_audio.py)
— with honest, loud fallbacks (baked-in audio, enhance over sfx whooshes) —
and the preview proxy (preview_proxy.py) rides the end of every assemble.
"""
import json
import os
import tempfile
import unittest

from _common import *  # noqa: F401,F403 — asm + producer path setup

import fingerprints as fpr
import preview_proxy as pxy
from audio import base_audio as ba


def _plan(**overrides) -> dict:
    plan = {
        "cutTrack": [{"sourceId": "raw-1", "start": 1.0, "end": 20.0}],
        "punchIns": [{"outStart": 1.0, "outEnd": 2.0, "zoom": 1.1}],
        "transitions": [{"outTime": 5.0, "kind": "white-flash", "sfx": True}],
        "captions": {"burn": False},
        "graphicsTrack": [{"kind": "stat-card", "outStart": 1.0, "outEnd": 2.0}],
        "target": {"mode": "longform"},
        "planVersion": 3,
    }
    plan.update(overrides)
    return plan


def _js_roundtrip(plan: dict) -> dict:
    """Simulate the editor's save-plan write: JS JSON.stringify has ONE number
    type, so an integral float loses its decimal point (30.0 → 30)."""
    return json.loads(
        json.dumps(plan),
        parse_float=lambda s: int(float(s)) if float(s).is_integer() else float(s))


class FingerprintSplitTests(unittest.TestCase):
    """Audio-only edits flip ONLY the audio print; cut edits flip the video print."""

    def test_audio_gain_edit_flips_only_audio_fingerprint(self) -> None:
        p = _plan()
        v0, a0, f0 = (fpr.video_fingerprint(p), fpr.audio_fingerprint(p),
                      fpr.base_fingerprint(p))
        p["audioGain"] = [{"outStart": 2.0, "outEnd": 4.0, "dB": -3.0}]
        self.assertEqual(fpr.video_fingerprint(p), v0)      # video print stable
        self.assertNotEqual(fpr.audio_fingerprint(p), a0)   # audio print flips
        self.assertNotEqual(fpr.base_fingerprint(p), f0)    # legacy still flips

    def test_audio_enhance_edit_flips_only_audio_fingerprint(self) -> None:
        p = _plan()
        v0, a0 = fpr.video_fingerprint(p), fpr.audio_fingerprint(p)
        p["audioEnhance"] = {"preset": "voice"}
        self.assertEqual(fpr.video_fingerprint(p), v0)
        self.assertNotEqual(fpr.audio_fingerprint(p), a0)

    def test_cut_edit_flips_video_not_audio(self) -> None:
        p = _plan()
        v0, a0 = fpr.video_fingerprint(p), fpr.audio_fingerprint(p)
        p["cutTrack"][0]["end"] = 25.0
        self.assertNotEqual(fpr.video_fingerprint(p), v0)
        self.assertEqual(fpr.audio_fingerprint(p), a0)

    def test_transitions_stay_video_side(self) -> None:
        # Transition flash frames are baked into the picture — a transition
        # edit must flip the VIDEO print (full rebuild), never ride audio-only.
        p = _plan()
        v0 = fpr.video_fingerprint(p)
        p["transitions"][0]["outTime"] = 6.0
        self.assertNotEqual(fpr.video_fingerprint(p), v0)

    def test_graphics_and_music_flip_neither(self) -> None:
        p = _plan()
        v0, a0 = fpr.video_fingerprint(p), fpr.audio_fingerprint(p)
        p["graphicsTrack"].append({"kind": "chip-row", "outStart": 3, "outEnd": 4})
        p["music"] = {"enabled": True, "path": "/x/bed.mp3"}
        self.assertEqual(fpr.video_fingerprint(p), v0)
        self.assertEqual(fpr.audio_fingerprint(p), a0)

    def test_record_carries_all_three_prints(self) -> None:
        rec = fpr.fingerprint_record(_plan())
        self.assertEqual(set(rec),
                         {"fingerprint", "videoFingerprint", "audioFingerprint",
                          "masteringPolicyVersion", "audioClockPolicy"})


class SerializationCanonTests(unittest.TestCase):
    """A JS save-plan round-trip (JSON.stringify collapses 30.0 → 30) must not
    flip any fingerprint — the save-plan → assemble spurious-rebuild bug."""

    def test_js_roundtrip_keeps_every_print(self) -> None:
        p = _plan(audioGain=[{"outStart": 30.0, "outEnd": 39.999, "dB": -2.0}])
        js = _js_roundtrip(p)
        self.assertIsInstance(js["audioGain"][0]["outStart"], int)  # collapse happened
        self.assertEqual(fpr.base_fingerprint(js), fpr.base_fingerprint(p))
        self.assertEqual(fpr.video_fingerprint(js), fpr.video_fingerprint(p))
        self.assertEqual(fpr.audio_fingerprint(js), fpr.audio_fingerprint(p))
        self.assertEqual(fpr.graphics_fingerprint(js), fpr.graphics_fingerprint(p))

    def test_real_edits_still_flip(self) -> None:
        p = _plan()
        f0 = fpr.base_fingerprint(p)
        p["cutTrack"][0]["end"] = 20.5          # non-integral float = a real edit
        self.assertNotEqual(fpr.base_fingerprint(p), f0)

    def test_bools_stay_distinct_from_ints(self) -> None:
        # bool is an int subclass in python — canon must not fold True into 1.
        self.assertNotEqual(fpr.base_fingerprint({"captions": {"burn": True}}),
                            fpr.base_fingerprint({"captions": {"burn": 1}}))

    def test_recorded_prints_recomputed_from_snapshot(self) -> None:
        # Stored prints hashed by an OLD hash function must not force a rebuild
        # when the base_plan.json snapshot proves the base matches the plan.
        old = _plan()
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "base.fingerprint.json")
            with open(fp, "w") as f:
                json.dump({"fingerprint": "0" * 16, "videoFingerprint": "0" * 16,
                           "audioFingerprint": "0" * 16,
                           "manifestPath": "/m.json"}, f)
            with open(os.path.join(d, "base_plan.json"), "w") as f:
                json.dump(old, f)
            rec = fpr.recorded_fingerprints(fp)
        self.assertEqual(rec["fingerprint"], fpr.base_fingerprint(old))
        self.assertEqual(rec["videoFingerprint"], fpr.video_fingerprint(old))
        self.assertEqual(rec["audioFingerprint"], fpr.audio_fingerprint(old))
        self.assertEqual(rec["manifestPath"], "/m.json")   # extras preserved

    def test_graphics_cache_key_survives_js_roundtrip(self) -> None:
        from graphics.graphics_render import content_hash
        spec = {"at1": 1.0, "at2": 0.55, "x": 421}
        js = _js_roundtrip({"spec": spec})["spec"]
        html = ("<div data-composition-variables='["
                '{"id":"at1"},{"id":"at2"},{"id":"x"}'
                "]'></div>")
        self.assertEqual(content_hash("chip-row", spec, 4.0, html),
                         content_hash("chip-row", js, 4.0, html))
        self.assertNotEqual(
            content_hash("chip-row", spec, 4.0, html),
            content_hash("chip-row", {**spec, "at2": 0.6}, 4.0, html))


class DispatchMatrixTests(unittest.TestCase):
    """_base_state: current / audio_stale / stale (+ legacy-file derivation)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.join(self.tmp.name, "base_final.mp4")
        with open(self.base, "wb") as f:
            f.write(b"x")
        self.fp = os.path.join(self.tmp.name, "base.fingerprint.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_fp(self, plan: dict, legacy: bool = False) -> None:
        from test_base_reuse import bound_record
        rec = bound_record(self.base, plan)
        if legacy:
            rec = {"fingerprint": rec["fingerprint"]}
        with open(self.fp, "w") as f:
            json.dump(rec, f)

    def test_audio_only_edit_reports_audio_stale(self) -> None:
        old = _plan()
        self._write_fp(old)
        new = _plan(audioGain=[{"outStart": 1.0, "outEnd": 2.0, "dB": -2.0}])
        self.assertEqual(asm._base_state(self.base, new, self.fp), "audio_stale")

    def test_cut_edit_reports_stale_even_with_audio_change(self) -> None:
        self._write_fp(_plan())
        new = _plan(audioGain=[{"outStart": 1.0, "outEnd": 2.0, "dB": -2.0}])
        new["cutTrack"][0]["end"] = 25.0
        self.assertEqual(asm._base_state(self.base, new, self.fp), "stale")

    def test_unchanged_plan_reports_current(self) -> None:
        self._write_fp(_plan())
        self.assertEqual(asm._base_state(self.base, _plan(), self.fp), "current")

    def test_legacy_fingerprint_with_snapshot_requires_full_rebuild(self) -> None:
        # A plan snapshot proves old intent, not the executed mastering policy.
        old = _plan()
        self._write_fp(old, legacy=True)
        with open(os.path.join(self.tmp.name, "base_plan.json"), "w") as f:
            json.dump(old, f)
        new = _plan(audioGain=[{"outStart": 1.0, "outEnd": 2.0, "dB": -2.0}])
        self.assertEqual(asm._base_state(self.base, new, self.fp), "stale")

    def test_legacy_fingerprint_without_snapshot_is_stale(self) -> None:
        self._write_fp(_plan(), legacy=True)
        new = _plan(audioGain=[{"outStart": 1.0, "outEnd": 2.0, "dB": -2.0}])
        self.assertEqual(asm._base_state(self.base, new, self.fp), "stale")

    def test_js_saved_plan_stays_current(self) -> None:
        # THE save-plan → assemble regression: base rendered from a python-
        # written plan (30.0), operator hits Save in the editor (JS collapses
        # it to 30) with zero semantic change — the base must stay current.
        old = _plan(audioGain=[{"outStart": 30.0, "outEnd": 39.999, "dB": -2.0}])
        self._write_fp(old)
        self.assertEqual(
            asm._base_state(self.base, _js_roundtrip(old), self.fp), "current")


class AudioFastPathEligibilityTests(unittest.TestCase):
    """audio_fast_path_block — the honest fallback matrix (pure function)."""

    def test_gain_only_on_pristine_base_is_eligible(self) -> None:
        old, new = _plan(), _plan(audioGain=[{"outStart": 1, "outEnd": 2, "dB": -2}])
        self.assertIsNone(ba.audio_fast_path_block(old, new))

    def test_gain_only_with_sfx_transitions_is_eligible(self) -> None:
        # Pipeline order: enhance → whoosh amix → GAIN → master. Gain runs
        # AFTER the amix, and the base audio already carries the whooshes at
        # the amix point — gain on the mastered bus reproduces the order.
        old = _plan()
        new = _plan(audioGain=[{"outStart": 1, "outEnd": 2, "dB": -2}])
        self.assertTrue(any(e.get("sfx", True) for e in new["transitions"]))
        self.assertIsNone(ba.audio_fast_path_block(old, new))

    def test_enhance_with_sfx_transitions_falls_back(self) -> None:
        # Enhance runs BEFORE the amix — on the base bus it would process the
        # baked-in whooshes (denoise can eat authored SFX) → loud full rebuild.
        old, new = _plan(), _plan(audioEnhance={"preset": "voice"})
        reason = ba.audio_fast_path_block(old, new)
        self.assertIsNotNone(reason)
        self.assertIn("sfx", reason)

    def test_enhance_without_sfx_transitions_is_eligible(self) -> None:
        old = _plan(transitions=[{"outTime": 5.0, "kind": "white-flash",
                                  "sfx": False}])
        new = _plan(transitions=old["transitions"],
                    audioEnhance={"preset": "voice"})
        self.assertIsNone(ba.audio_fast_path_block(old, new))

    def test_enhance_with_implicit_silent_transition_is_eligible(self) -> None:
        transitions = [{"outTime": 5.0, "kind": "white-flash"}]
        old = _plan(transitions=transitions)
        new = _plan(transitions=transitions,
                    audioEnhance={"preset": "voice"})
        self.assertIsNone(ba.audio_fast_path_block(old, new))

    def test_enhance_with_no_transitions_is_eligible(self) -> None:
        old = _plan(transitions=None)
        new = _plan(transitions=None, audioEnhance={"preset": "voice"})
        self.assertIsNone(ba.audio_fast_path_block(old, new))

    def test_baked_in_audio_falls_back(self) -> None:
        # Editing an audio field that is already baked into the base cannot
        # be un-baked — re-applying would stack old×new processing.
        old = _plan(audioGain=[{"outStart": 1, "outEnd": 2, "dB": -3}])
        new = _plan(audioGain=[{"outStart": 1, "outEnd": 2, "dB": -6}])
        reason = ba.audio_fast_path_block(old, new)
        self.assertIsNotNone(reason)
        self.assertIn("baked-in", reason)

    def test_missing_snapshot_falls_back(self) -> None:
        new = _plan(audioGain=[{"outStart": 1, "outEnd": 2, "dB": -2}])
        self.assertIsNotNone(ba.audio_fast_path_block(None, new))

    def test_removed_audio_fields_fall_back(self) -> None:
        self.assertIsNotNone(ba.audio_fast_path_block(_plan(), _plan()))


class ProxyCmdTests(unittest.TestCase):
    """build_proxy_cmd — dims + keyframe flags (the scrub contract)."""

    def _cmd(self) -> list[str]:
        return pxy.build_proxy_cmd("/x/final.mp4", "/x/final.proxy.mp4")

    def test_short_side_480_even_dims(self) -> None:
        cmd = self._cmd()
        vf = cmd[cmd.index("-vf") + 1]
        # Aspect-agnostic: the SHORT side lands at 480; -2 keeps dims even.
        self.assertIn("if(gt(iw,ih),-2,480)", vf)
        self.assertIn("if(gt(iw,ih),480,-2)", vf)

    def test_dense_keyframes_for_scrubbing(self) -> None:
        cmd = self._cmd()
        self.assertEqual(cmd[cmd.index("-g") + 1], "24")
        self.assertEqual(cmd[cmd.index("-keyint_min") + 1], "24")

    def test_encode_profile(self) -> None:
        cmd = self._cmd()
        self.assertEqual(cmd[cmd.index("-crf") + 1], "28")
        self.assertEqual(cmd[cmd.index("-preset") + 1], "veryfast")
        self.assertEqual(cmd[cmd.index("-b:a") + 1], "96k")
        self.assertIn("+faststart", cmd)

    def test_proxy_path_lands_beside_final(self) -> None:
        self.assertEqual(pxy.proxy_path("/a/b/final.mp4"), "/a/b/final.proxy.mp4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
