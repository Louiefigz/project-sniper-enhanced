"""audio-only base swap crash safety — the intent/commit protocol.

SERIOUS window (fixed 2026-07-21): `_audio_only_rebuild` replaced
base_final.mp4 BEFORE the records update. A worker killed between the two
left NEW audio bytes with OLD records; on resume, eligibility passed again
and the audio effect (e.g. a gain window) was applied a SECOND time onto the
already-processed base — a silently double-processed approved final.

The fix (audio/base_audio.commit_audio_base + recover_audio_intent): stage a
fsynced intent sidecar carrying the new base's content hash BEFORE the
replace; on load/resume compare the current base hash — matches-new →
finalize records (idempotent), anything else → discard intent and redo.
These tests kill the commit at EVERY cut point and prove that resume yields
exactly ONE application of the audio effect and no lost records update.
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from _common import *  # noqa: F401,F403 — asm + producer path setup

import fingerprints as fpr
from audio import base_audio as ba


def _plan(**overrides) -> dict:
    plan = {
        "cutTrack": [{"sourceId": "raw-1", "start": 1.0, "end": 20.0}],
        "captions": {"burn": False},
        "target": {"mode": "longform"},
        "planVersion": 3,
    }
    plan.update(overrides)
    return plan


def _fake_rebuild(base: str, plan: dict, work: str) -> tuple:
    """Stand-in for rebuild_audio_bus: 'process' = append +GAIN to the bytes.

    Reads the CURRENT base, so a double-dispatch would produce RAW+GAIN+GAIN —
    exactly the silent double-processing these tests must rule out.
    """
    os.makedirs(work, exist_ok=True)
    out = os.path.join(work, "bus_mastered.mp4")
    with open(base, "rb") as f:
        data = f.read()
    with open(out, "wb") as f:
        f.write(data + b"+GAIN")
    return out, {"gain_windows": 1}


class AudioCommitCrashTests(unittest.TestCase):
    """Kill commit_audio_base at each cut point; resume must stay single-shot."""

    CUTS = ("after_rebuild_before_intent", "after_intent_before_replace",
            "after_replace_before_records", "after_records_before_clear")

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.base = os.path.join(d, "base_final.mp4")
        with open(self.base, "wb") as f:
            f.write(b"RAW")
        self.old_plan = _plan()
        self.new_plan = _plan(
            audioGain=[{"outStart": 1.0, "outEnd": 2.0, "dB": 3.0}])
        self.fp = os.path.join(d, "base.fingerprint.json")
        with open(self.fp, "w") as f:   # what render.py's base bookkeeping writes
            json.dump({**fpr.fingerprint_record(self.old_plan),
                       "outputDuration": 19.0, "manifestPath": "/m.json"}, f)
        with open(os.path.join(d, "base_plan.json"), "w") as f:
            json.dump(self.old_plan, f)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _crashed_commit(self, cut: str):
        """Context manager set that dies inside commit at the given cut point."""
        boom = RuntimeError(f"simulated crash: {cut}")
        real_write = ba.write_json_atomic

        def write_then_die(path, payload, indent=None):
            real_write(path, payload, indent)
            raise boom

        if cut == "after_rebuild_before_intent":
            return mock.patch.object(ba, "write_json_atomic", side_effect=boom)
        if cut == "after_intent_before_replace":
            return mock.patch.object(ba, "write_json_atomic",
                                     side_effect=write_then_die)
        if cut == "after_replace_before_records":
            return mock.patch.object(ba, "update_base_records",
                                     side_effect=boom)
        if cut == "after_records_before_clear":
            return mock.patch.object(ba, "clear_audio_intent",
                                     side_effect=boom)
        raise AssertionError(f"unknown cut point {cut}")

    def _run_crashing_dispatch(self, cut: str) -> None:
        with mock.patch.object(ba, "rebuild_audio_bus", _fake_rebuild), \
                self._crashed_commit(cut), \
                redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                asm._audio_only_rebuild(self.base, self.new_plan, self.fp)

    def _resume(self) -> str:
        """The real resume path: ensure_base settles the intent, then dispatches."""
        with mock.patch.object(ba, "rebuild_audio_bus", _fake_rebuild), \
                redirect_stdout(io.StringIO()):
            _plan_out, state = asm.ensure_base(
                self.base, os.path.join(self.tmp.name, "edit_plan.json"),
                self.new_plan, self.fp, None)
        return state

    def _assert_single_processing_and_current_records(self) -> None:
        with open(self.base, "rb") as f:
            data = f.read()
        self.assertEqual(data, b"RAW+GAIN")            # applied exactly ONCE
        self.assertEqual(data.count(b"+GAIN"), 1)      # never double-processed
        rec = fpr.recorded_fingerprints(self.fp)       # no lost update
        self.assertEqual(rec["videoFingerprint"],
                         fpr.video_fingerprint(self.new_plan))
        self.assertEqual(rec["audioFingerprint"],
                         fpr.audio_fingerprint(self.new_plan))
        self.assertEqual(rec["manifestPath"], "/m.json")   # extras preserved
        self.assertEqual(rec["outputDuration"], 19.0)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(asm._base_state(self.base, self.new_plan, self.fp),
                             "current")
        self.assertFalse(os.path.exists(ba.audio_intent_path(self.fp)))

    def test_crash_at_every_cut_point_then_resume_is_single_shot(self) -> None:
        for index, cut in enumerate(self.CUTS):
            with self.subTest(cut=cut):
                if index:              # fresh fixture per cut point
                    self.tearDown()
                    self.setUp()
                self._run_crashing_dispatch(cut)
                state = self._resume()
                # Pre-replace crashes redo the bus (audio_only); post-replace
                # crashes finalize records and find the base current.
                self.assertIn(state, ("audio_only", "current"))
                self._assert_single_processing_and_current_records()

    def test_post_replace_crash_resume_never_redispatches(self) -> None:
        # THE regression: kill between os.replace(base) and the records
        # update. Resume must FINALIZE from the intent — a second dispatch
        # would gain the already-gained base (+GAIN+GAIN).
        self._run_crashing_dispatch("after_replace_before_records")
        redo = mock.Mock(side_effect=AssertionError(
            "audio bus rebuilt a SECOND time onto processed base"))
        with mock.patch.object(ba, "rebuild_audio_bus", redo), \
                redirect_stdout(io.StringIO()):
            _plan_out, state = asm.ensure_base(
                self.base, os.path.join(self.tmp.name, "edit_plan.json"),
                self.new_plan, self.fp, None)
        self.assertEqual(state, "current")
        redo.assert_not_called()
        self._assert_single_processing_and_current_records()

    def test_clean_commit_leaves_no_intent(self) -> None:
        with mock.patch.object(ba, "rebuild_audio_bus", _fake_rebuild), \
                redirect_stdout(io.StringIO()):
            self.assertTrue(
                asm._audio_only_rebuild(self.base, self.new_plan, self.fp))
        self._assert_single_processing_and_current_records()

    def test_stale_intent_after_unrelated_rebuild_is_discarded(self) -> None:
        # Crash pre-replace, then a FULL rebuild replaced the base out-of-band:
        # the hash matches neither old nor new → discard, records untouched.
        self._run_crashing_dispatch("after_intent_before_replace")
        with open(self.base, "wb") as f:
            f.write(b"FULL-REBUILD-BYTES")
        self.assertEqual(ba.recover_audio_intent(self.base, self.fp),
                         "discarded")
        self.assertFalse(os.path.exists(ba.audio_intent_path(self.fp)))
        rec = fpr.recorded_fingerprints(self.fp)
        self.assertEqual(rec["audioFingerprint"],
                         fpr.audio_fingerprint(self.old_plan))

    def test_unreadable_intent_is_discarded(self) -> None:
        # The intent is fsynced BEFORE the replace, so an unreadable sidecar
        # proves the replace never happened — discard and redo honestly.
        with open(ba.audio_intent_path(self.fp), "w") as f:
            f.write("{truncated")
        self.assertEqual(ba.recover_audio_intent(self.base, self.fp),
                         "discarded")
        with open(self.base, "rb") as f:
            self.assertEqual(f.read(), b"RAW")

    def test_recovery_is_idempotent(self) -> None:
        self._run_crashing_dispatch("after_replace_before_records")
        self.assertEqual(ba.recover_audio_intent(self.base, self.fp),
                         "finalized")
        self.assertIsNone(ba.recover_audio_intent(self.base, self.fp))
        self._assert_single_processing_and_current_records()


if __name__ == "__main__":
    unittest.main(verbosity=2)
