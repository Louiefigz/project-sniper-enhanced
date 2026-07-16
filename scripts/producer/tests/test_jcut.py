"""J-cut leads (LIAM-4-MOVES move 2, measured 2026-07-11, n=176 seams).

``cutTrack[i].audioLeadMs`` = the incoming segment's audio PRE-ROLL starts
this early — baked into the OUTGOING part's audio tail by cut_speed so every
part keeps audio == video length exactly (the concat demuxer offsets whole
files; unequal lengths would desync — probed empirically). These tests pin:
the compile-time validator (single source for lint + renderer), the additive
default (absent = today's joins), the lint bounds + measured-band WARN, the
tail-chain window math, and an ffmpeg end-to-end RMS probe showing the
incoming audio really arrives before the picture cut.
"""
import json
import os
import re
import subprocess
import tempfile
import unittest

from _common import *  # noqa: F401,F403


def _plan(lead_ms=None, speed=1.0):
    cut = [{"sourceId": "raw-1", "start": 1.0, "end": 4.0},
           {"sourceId": "raw-1", "start": 6.0, "end": 9.0, "speed": speed}]
    if lead_ms is not None:
        cut[1]["audioLeadMs"] = lead_ms
    return {"cutTrack": cut}


class JCutCompileTests(unittest.TestCase):
    """compile_timeline.parse_audio_lead — the single validator."""

    def test_absent_lead_is_zero_everywhere(self) -> None:
        tmap = ct.compile_plan(_plan())
        self.assertEqual([s.audio_lead_s for s in tmap.segments], [0.0, 0.0])

    def test_lead_lands_on_the_segment(self) -> None:
        tmap = ct.compile_plan(_plan(lead_ms=80))
        self.assertAlmostEqual(tmap.segments[1].audio_lead_s, 0.08)
        self.assertEqual(tmap.segments[0].audio_lead_s, 0.0)
        # picture map untouched (audio-only move)
        self.assertEqual(tmap.segments[1].out_start,
                         ct.compile_plan(_plan()).segments[1].out_start)

    def test_first_segment_lead_rejected(self) -> None:
        plan = _plan()
        plan["cutTrack"][0]["audioLeadMs"] = 80
        with self.assertRaises(ValueError):
            ct.compile_plan(plan)

    def test_bounds_rejected(self) -> None:
        for bad in (0, -10, 301, True, "80"):
            with self.assertRaises(ValueError):
                ct.compile_plan(_plan(lead_ms=bad))

    def test_lead_needs_source_audio_before_the_in_point(self) -> None:
        plan = _plan(lead_ms=200)
        plan["cutTrack"][1]["start"] = 0.1        # 0.1s < 0.2s lead
        plan["cutTrack"][1]["end"] = 3.0
        with self.assertRaises(ValueError):
            ct.compile_plan(plan)

    def test_lead_scales_with_speed(self) -> None:
        # 2x speed: 0.2s output lead consumes 0.4s of source before start
        plan = _plan(lead_ms=200, speed=2.0)
        plan["cutTrack"][1]["start"] = 0.3        # 0.3 < 0.4 → reject
        plan["cutTrack"][1]["end"] = 3.0
        with self.assertRaises(ValueError):
            ct.compile_plan(plan)

    def test_previous_part_must_keep_own_audio(self) -> None:
        plan = _plan(lead_ms=250)
        plan["cutTrack"][0]["end"] = 1.3          # prev part only 0.3s long
        with self.assertRaises(ValueError):
            ct.compile_plan(plan)
        plan["cutTrack"][0]["end"] = 1.2          # 0.2 - 0.25 < residual
        with self.assertRaises(ValueError):
            ct.compile_plan(plan)

    def test_round_trip_and_legacy_maps(self) -> None:
        tmap = ct.compile_plan(_plan(lead_ms=80))
        again = ct.TimelineMap.from_dict(tmap.to_dict())
        self.assertAlmostEqual(again.segments[1].audio_lead_s, 0.08)
        legacy = tmap.to_dict()
        for s in legacy["segments"]:              # pre-J-cut serialized map
            s.pop("audio_lead_s")
        self.assertEqual(
            ct.TimelineMap.from_dict(legacy).segments[1].audio_lead_s, 0.0)


class JCutChainTests(unittest.TestCase):
    """cut_speed window math: own audio gives up the tail, lead fills it."""

    def test_own_chain_trims_short_by_the_lead(self) -> None:
        seg = ct.Segment(0, "raw-1", 1.0, 4.0, 1.0, 0.0, 3.0)
        full = cs._audio_chain(seg, 0.0, 3.0, True)
        self.assertIn("atrim=start=1.000000:end=4.000000", full)
        self.assertIn("[own]", full)
        own = cs._audio_chain(seg, 0.0, 2.8, True)   # 0.2s J-cut tail follows
        self.assertIn("atrim=start=1.000000:end=3.800000", own)
        self.assertIn("afade=t=out:st=2.785000", own)   # declick on own tail

    def test_tail_chain_pulls_pre_in_point_audio(self) -> None:
        tail = cs.TailLead(0.2, "src.mp4", 6.0, 1.0)
        chain = cs._tail_chain(tail, 1, True)
        self.assertIn("atrim=start=5.800000:end=6.000000", chain)
        self.assertIn("[tail]", chain)
        # speed 2.0: 0.2s output tail consumes 0.4s of source
        fast = cs._tail_chain(cs.TailLead(0.2, "src.mp4", 6.0, 2.0), 1, True)
        self.assertIn("atrim=start=5.600000:end=6.000000", fast)
        self.assertIn("atempo=2.0", fast)
        silent = cs._tail_chain(tail, 2, False)
        self.assertIn("atrim=0:0.200000", silent)


class JCutLintTests(unittest.TestCase):
    """plan_lint bounds: hard errors via the shared validator + band WARN."""

    def _lint(self, mutate) -> "pl.Report":
        plan = good_plan()
        plan["cutTrack"] = [
            {"sourceId": "raw-1", "start": 1.0, "end": 16.0, "speed": 1.0},
            {"sourceId": "raw-1", "start": 20.0, "end": 35.0, "speed": 1.0}]
        mutate(plan)
        return pl.lint(plan, MANIFEST)

    def test_in_band_lead_is_clean(self) -> None:
        rep = self._lint(lambda p: p["cutTrack"][1].update(audioLeadMs=80))
        self.assertEqual([e for e in rep.errors if "audioLead" in e], [])
        self.assertEqual([w for w in rep.warnings if "audioLead" in w], [])

    def test_first_segment_and_out_of_bounds_error(self) -> None:
        rep = self._lint(lambda p: p["cutTrack"][0].update(audioLeadMs=80))
        self.assertTrue(any("first segment" in e for e in rep.errors),
                        rep.errors)
        rep = self._lint(lambda p: p["cutTrack"][1].update(audioLeadMs=400))
        self.assertTrue(any("audioLeadMs 400" in e for e in rep.errors),
                        rep.errors)

    def test_off_band_lead_warns(self) -> None:
        rep = self._lint(lambda p: p["cutTrack"][1].update(audioLeadMs=200))
        self.assertEqual([e for e in rep.errors if "audioLead" in e], [])
        self.assertTrue(any("true-J-lead" in w for w in rep.warnings),
                        rep.warnings)


@unittest.skipUnless(_HAVE_FFMPEG, "ffmpeg not on PATH")
class JCutRenderTests(unittest.TestCase):
    """End-to-end: the incoming audio is audible BEFORE the picture cut."""

    _RMS_RE = re.compile(r"RMS level dB:\s*(-?[\d.]+|-inf)")

    def _rms_db(self, path: str, t0: float, t1: float) -> float:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path,
             "-af", f"atrim={t0}:{t1},asetpts=PTS-STARTPTS,"
                    "aformat=channel_layouts=mono,astats=metadata=0",
             "-f", "null", "-"], capture_output=True, text=True)
        hits = self._RMS_RE.findall(proc.stderr)
        if not hits:
            raise AssertionError(f"astats RMS not found:\n{proc.stderr[-400:]}")
        val = hits[0]
        return -120.0 if val == "-inf" else float(val)

    def test_incoming_audio_leads_the_picture_cut(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jcut-") as tmp:
            src = os.path.join(tmp, "src.mp4")
            # 10s clip: audio SILENT for t<5, 880Hz tone for t>=5.
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error",
                 "-f", "lavfi", "-i", "color=c=gray:s=320x180:d=10:r=30",
                 "-f", "lavfi", "-i",
                 "sine=frequency=880:duration=10:sample_rate=48000",
                 "-af", "volume='if(gte(t,5),1,0)':eval=frame",
                 "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-ar", "48000", "-ac", "2", src],
                check=True)
            # cut [1,3] (silence) + [6,9] (tone), 250ms lead on the 2nd:
            # picture seam at out 2.0; tone source exists from 5.0 so the
            # 6.0-in-point pre-roll [5.75,6.0] is REAL tone → audible 1.75s.
            plan = {"cutTrack": [
                {"sourceId": "s", "start": 1.0, "end": 3.0},
                {"sourceId": "s", "start": 6.0, "end": 9.0,
                 "audioLeadMs": 250}]}
            manifest = {"sources": [{"id": "s", "path": src}]}
            out = os.path.join(tmp, "mezz.mp4")
            work = os.path.join(tmp, "work")
            os.makedirs(work)
            result = cs.render_cut_speed(plan, manifest, out, work)
            self.assertLessEqual(result["driftFrames"],
                                 result["toleranceFrames"])
            before_lead = self._rms_db(out, 1.55, 1.70)   # own (silent) audio
            in_lead = self._rms_db(out, 1.82, 1.97)       # J-cut tail zone
            after_cut = self._rms_db(out, 2.10, 2.30)     # incoming segment
            self.assertLess(before_lead, -60.0, before_lead)
            self.assertGreater(in_lead, -30.0, in_lead)   # tone BEFORE seam
            self.assertGreater(after_cut, -30.0, after_cut)

    def test_no_lead_keeps_todays_joins(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jcut0-") as tmp:
            src = os.path.join(tmp, "src.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error",
                 "-f", "lavfi", "-i", "color=c=gray:s=320x180:d=10:r=30",
                 "-f", "lavfi", "-i",
                 "sine=frequency=880:duration=10:sample_rate=48000",
                 "-af", "volume='if(gte(t,5),1,0)':eval=frame",
                 "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-ar", "48000", "-ac", "2", src],
                check=True)
            plan = {"cutTrack": [
                {"sourceId": "s", "start": 1.0, "end": 3.0},
                {"sourceId": "s", "start": 6.0, "end": 9.0}]}
            manifest = {"sources": [{"id": "s", "path": src}]}
            out = os.path.join(tmp, "mezz.mp4")
            work = os.path.join(tmp, "work")
            os.makedirs(work)
            cs.render_cut_speed(plan, manifest, out, work)
            # without a lead the pre-seam zone stays silent
            self.assertLess(self._rms_db(out, 1.82, 1.97), -60.0)
            self.assertGreater(self._rms_db(out, 2.10, 2.30), -30.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
