#!/usr/bin/env python3
"""auto_base_guard contract: quarantine ONLY a stale base, never a live dir."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edit.auto_base_guard import guard
from fingerprints import fingerprint_record

PLAN = {"planVersion": 1,
        "target": {"mode": "longform", "scope": "trim"},
        "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 5.0, "speed": 1.0}],
        "graphicsTrack": []}


class AutoBaseGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name: str, obj) -> str:
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            if isinstance(obj, (dict, list)):
                json.dump(obj, f)
            else:
                f.write(obj)
        return path

    def test_no_base_is_a_noop(self):
        self._write("edit_plan.json", PLAN)
        self.assertEqual(guard(self.dir)["action"], "none")

    def test_no_fingerprint_quarantines_the_unproven_base(self):
        # An auto-authored plan must never assemble onto a base it can't prove
        # current — that would silently ship the OLD timeline.
        self._write("edit_plan.json", PLAN)
        self._write("base_final.mp4", "fake-bytes")
        record = guard(self.dir)
        self.assertEqual(record["action"], "quarantined")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "base_final.mp4")))

    def test_matching_video_fingerprint_keeps_the_base(self):
        self._write("edit_plan.json", PLAN)
        self._write("base_final.mp4", "fake-bytes")
        self._write("base.fingerprint.json", fingerprint_record(PLAN))
        # audio-only change must ALSO keep the base (fast path stays valid)
        audio_plan = dict(PLAN, audioGain=[{"outStart": 0, "outEnd": 1, "dB": 2}])
        self._write("edit_plan.json", audio_plan)
        record = guard(self.dir)
        self.assertEqual(record["action"], "none")
        self.assertTrue(os.path.exists(os.path.join(self.dir, "base_final.mp4")))

    def test_stale_base_is_quarantined(self):
        stale = dict(PLAN, cutTrack=[{"sourceId": "raw-1", "start": 1.0,
                                      "end": 4.0, "speed": 1.0}])
        self._write("edit_plan.json", PLAN)
        self._write("base_final.mp4", "fake-bytes")
        self._write("base.fingerprint.json", fingerprint_record(stale))
        record = guard(self.dir)
        self.assertEqual(record["action"], "quarantined")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "base_final.mp4")))
        self.assertTrue(os.path.exists(os.path.join(self.dir, "base_final.prev.mp4")))

    def test_snapshot_recompute_wins_over_stored_prints(self):
        # base_plan.json beside the fingerprint = the recorded prints are
        # RECOMPUTED from it; stored (stale) prints must not cause a quarantine.
        self._write("edit_plan.json", PLAN)
        self._write("base_final.mp4", "fake-bytes")
        self._write("base.fingerprint.json", {"videoFingerprint": "bogus"})
        self._write("base_plan.json", PLAN)
        self.assertEqual(guard(self.dir)["action"], "none")

    def test_live_lock_refuses(self):
        self._write("edit_plan.json", PLAN)
        self._write(".assemble.lock", {"pid": os.getpid()})
        with self.assertRaises(RuntimeError):
            guard(self.dir)

    def test_stale_lock_is_ignored(self):
        self._write("edit_plan.json", PLAN)
        self._write(".assemble.lock", {"pid": 99999999})
        self.assertEqual(guard(self.dir)["action"], "none")


if __name__ == "__main__":
    unittest.main()
