"""Exact joined mezzanine clock: many NTSC parts, one CFR timeline, one AAC.

Regression for the 2026-09-06 long-form preview failure: 82 stream-copied
parts joined by the concat demuxer probed avg_frame_rate 280380000/9354877
instead of 30000/1001 because MP4 container durations are millisecond
quantized. The mezzanine must now be exact regardless of part count.
"""
from __future__ import annotations

import array
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from fractions import Fraction

from _common import *  # noqa: F401,F403

import cut_speed as cs

FPS = Fraction(30000, 1001)
SOURCE_S = 14.0


def _probe(path: str, *entries: str, count: bool = False, streams: str = "") -> dict:
    cmd = ["ffprobe", "-v", "error", *(["-count_frames"] if count else []),
           *(["-select_streams", streams] if streams else []),
           "-show_entries", ",".join(entries), "-of", "json", path]
    return json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout)


def _video_packets(path: str) -> list[tuple[int, int, int]]:
    rows = _probe(path, "packet=pts,dts,duration", streams="v:0")["packets"]
    return [(int(r["pts"]), int(r["dts"]), int(r["duration"])) for r in rows]


def _decoded(path: str) -> bytes:
    return subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", path, "-map", "0:a:0",
                           "-c:a", "pcm_s16le", "-f", "s16le", "-"], check=True, capture_output=True).stdout


def _decoded_samples(path: str) -> int:
    return len(_decoded(path)) // 4


class ProfileClockTests(unittest.TestCase):
    """Whole-tick frame clocks and nearest-sample audio windows per profile."""

    def test_timescales_carry_every_common_rate_exactly(self) -> None:
        cases = {Fraction(30000, 1001): (30000, 1001), Fraction(24000, 1001): (24000, 1001),
                 Fraction(24): (24000, 1000), Fraction(25): (25000, 1000),
                 Fraction(60000, 1001): (60000, 1001), Fraction(30): (30000, 1000)}
        for fps, expected in cases.items():
            profile = cs.Profile(320, 180, fps, "yuv420p")
            self.assertEqual((profile.video_timescale, profile.frame_ticks), expected, fps)
            self.assertEqual(Fraction(profile.video_timescale, profile.frame_ticks), fps)

    def test_audio_samples_follow_the_cumulative_clock(self) -> None:
        profile = cs.Profile(320, 180, FPS, "yuv420p")
        self.assertEqual(profile.audio_samples(0), 0)
        self.assertEqual(profile.audio_samples(5), 8008)          # 5 * 1601.6
        self.assertEqual(profile.audio_samples(3), 4805)          # 4804.8 rounds up
        self.assertEqual(profile.audio_samples(7) - profile.audio_samples(3), 6406)


class ConcatExactnessTests(unittest.TestCase):
    """Render a 12-part NTSC cut through the real stage and probe its clocks."""

    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            raise unittest.SkipTest("ffmpeg unavailable")
        cls.root = tempfile.mkdtemp(prefix="cut-exact-o'brien ")   # concat list quoting
        cls.source = os.path.join(cls.root, "source.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"testsrc2=s=320x180:r={FPS.numerator}/{FPS.denominator}:d={SOURCE_S}",
                        "-f", "lavfi", "-t", str(SOURCE_S), "-i", "sine=f=440:r=48000",
                        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-ar", "48000", "-ac", "2", cls.source], check=True)
        # 12 windows whose lengths are never a whole number of ms-aligned frames.
        cut = [{"sourceId": "s", "start": round(0.137 + i * 1.1, 3), "end": round(0.137 + i * 1.1 + 0.7 + (i % 5) * 0.061, 3)}
               for i in range(12)]
        cls.plan, cls.manifest = {"cutTrack": cut}, {"sources": [{"id": "s", "path": cls.source}]}
        cls.out, cls.work = os.path.join(cls.root, "mezz.mp4"), os.path.join(cls.root, "work")
        os.makedirs(cls.work)
        cls.result = cs.render_cut_speed(cls.plan, cls.manifest, cls.out, cls.work)
        cls.profile = cs.Profile(320, 180, FPS, "yuv420p")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_video_clock_is_exact_cfr_from_zero(self) -> None:
        video = _probe(self.out, "stream=codec_type,start_pts,time_base,avg_frame_rate,r_frame_rate,"
                       "has_b_frames,duration_ts,nb_read_frames", count=True)["streams"][0]
        self.assertEqual(video["codec_type"], "video")
        frames = int(video["nb_read_frames"])
        self.assertEqual(frames, self.result["videoFrames"])
        self.assertEqual(int(video["start_pts"]), 0)
        self.assertEqual(video["time_base"], "1/30000")
        self.assertEqual(Fraction(video["avg_frame_rate"]), FPS)
        self.assertEqual(Fraction(video["r_frame_rate"]), FPS)
        self.assertEqual(int(video["has_b_frames"]), 0)
        self.assertEqual(int(video["duration_ts"]), frames * 1001)
        packets = _video_packets(self.out)
        self.assertEqual(len(packets), frames)
        self.assertEqual({p - q for (p, _, _), (q, _, _) in zip(packets[1:], packets)}, {1001})
        self.assertTrue(all(pts == dts and dur == 1001 for pts, dts, dur in packets))
        self.assertLessEqual(self.result["driftFrames"], self.result["toleranceFrames"])

    def test_guarded_transport_preserves_all_decoded_picture_and_audio_bytes(self) -> None:
        """Real tiny media equivalence, not qualification of an actual source-color owner."""
        started = time.monotonic()
        deadline, checks = started + 30.0, []

        def guard() -> None:
            """A TEST timing-only callback grants no source, grade or presenter authority."""
            checks.append(time.monotonic())
            if checks[-1] >= deadline:
                raise RuntimeError("TEST original guarded native allowance expired")

        work, output = os.path.join(self.root, "guarded-parts"), os.path.join(self.root, "guarded.mp4")
        os.mkdir(work)
        result = cs.render_cut_speed_opts(self.plan, self.manifest, output, cs.CutSpeedOptions(work, before_encode=guard))
        generation_seconds = time.monotonic() - started
        self.assertEqual(len(checks), 26)
        self.assertEqual(result["videoFrames"], self.result["videoFrames"])
        self.assertEqual(_decoded(output), _decoded(self.out))
        picture_hashes = []
        for media in (self.out, output):
            pixels = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", media, "-map", "0:v:0",
                                     "-an", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                                    check=True, capture_output=True, timeout=30).stdout
            self.assertEqual(len(pixels), result["videoFrames"] * 320 * 180 * 3)
            picture_hashes.append(hashlib.sha256(pixels).hexdigest())
        self.assertEqual(picture_hashes[0], picture_hashes[1])
        print(json.dumps({"TEST": "guarded-transport-not-source-color-qualification", "frames": result["videoFrames"],
                          "pictureRgbSha256": picture_hashes[0], "decodedAudioBytesEqual": True,
                          "originalGuardChecks": len(checks), "guardedGenerationSeconds": generation_seconds,
                          "testGenerationAndComparisonSeconds": time.monotonic() - started}), flush=True)

    def test_audio_is_one_sample_exact_aac_generation(self) -> None:
        streams = _probe(self.out, "stream=codec_type,codec_name,sample_rate,channels,start_pts,"
                         "time_base,duration_ts")["streams"]
        audio = next(s for s in streams if s["codec_type"] == "audio")
        self.assertEqual((audio["codec_name"], audio["sample_rate"], audio["channels"]), ("aac", "48000", 2))
        self.assertEqual(int(audio["start_pts"]), 0)
        self.assertEqual(audio["time_base"], "1/48000")
        presented = int(audio["duration_ts"])
        self.assertEqual(presented, self.profile.audio_samples(self.result["videoFrames"]))
        decoded = _decoded_samples(self.out)
        self.assertTrue(0 <= decoded - presented <= 2048, (decoded, presented))

    def test_every_part_and_seam_ends_in_the_declick_fade(self) -> None:
        """The exact window can end before the nominal fade; the clamp re-applies it (review 2026-09-06)."""
        parts = sorted(p for p in os.listdir(self.work) if p.startswith("part_") and p.endswith(".mp4"))
        seams, offset = [], 0
        for name in parts:
            pcm = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", os.path.join(self.work, name), "-map", "0:a:0",
                                  "-f", "f32le", "-c:a", "pcm_f32le", "-"], check=True, capture_output=True).stdout
            samples = array.array("f", pcm)
            left = samples[0::2]
            peak = max(abs(v) for v in left[len(left) // 4: 3 * len(left) // 4])
            tail = max(abs(v) for v in left[-24:])          # last 0.5 ms
            self.assertLess(tail, 0.06 * peak, (name, tail, peak))
            offset += len(left); seams.append(offset)
        joined = array.array("h", _decoded(self.out))[0::2]
        peak = max(abs(v) for v in joined)
        for seam in seams[:-1]:
            before = max(abs(v) for v in joined[seam - 24:seam])
            self.assertLess(before, 0.15 * peak, (seam, before, peak))   # AAC smears, but no full-amplitude step

    def test_parts_are_bframe_free_pcm_on_the_cumulative_sample_clock(self) -> None:
        parts = sorted(p for p in os.listdir(self.work) if p.startswith("part_") and p.endswith(".mp4"))
        self.assertEqual(len(parts), 12)
        frames = samples = 0
        for name in parts:
            streams = _probe(os.path.join(self.work, name), "stream=codec_type,codec_name,has_b_frames,"
                             "duration_ts,time_base,nb_read_frames", count=True)["streams"]
            video = next(s for s in streams if s["codec_type"] == "video")
            audio = next(s for s in streams if s["codec_type"] == "audio")
            self.assertEqual(int(video["has_b_frames"]), 0, name)
            self.assertEqual(audio["codec_name"], "pcm_f32le", name)
            self.assertEqual(audio["time_base"], "1/48000", name)
            frames += int(video["nb_read_frames"])
            samples += int(audio["duration_ts"])
            self.assertEqual(samples, self.profile.audio_samples(frames), name)
        self.assertEqual(frames, self.result["videoFrames"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
