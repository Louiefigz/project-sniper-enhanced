"""Actual decoded-media glitch scans: real ffmpeg, real clocks, real corruption.

Pure log fixtures qualify the parsers; this suite qualifies that FFmpeg's real
metadata/progress/detector output, filter negotiation and error exits behave
the way those parsers assume. Media is synthesized fresh into a retained
/private/tmp root so a failure keeps its evidence.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from audit.audit_checks import FAIL, PASS, WARN
from audit.audit_glitch import detect_black, detect_flash, detect_freeze
from audit.audit_glitch_scan import GlitchScanError, scan_glitch_filter, scan_luma_frames

_HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
_SIZE = "320x180"
_OLD_PTS = re.compile(r"pts_time:(-?\d+(?:\.\d+)?)")
_OLD_YAVG = re.compile(r"lavfi\.signalstats\.YAVG=(-?\d+(?:\.\d+)?)")


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", *args], check=True)


def _lavfi(spec: str) -> list[str]:
    return ["-f", "lavfi", "-i", spec]


def _encode(out: Path, inputs: list[str], concat: int, rate: str) -> None:
    """Concatenate lavfi sources into one H.264/yuv420p file at the requested rate."""
    graph = "".join(f"[{index}:v]" for index in range(concat)) + f"concat=n={concat}:v=1:a=0,fps={rate}"
    _ffmpeg(*inputs, "-filter_complex", graph, "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-g", "30", "-movflags", "+faststart", str(out))


def _flash(out: Path, inputs: list[str], luma: int) -> None:
    """Exactly frame 30 of a continuous gray source is forced to one luma value."""
    _ffmpeg(*inputs, "-vf", f"lutyuv=y={luma}:enable='eq(n,30)'", "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "12", "-pix_fmt", "yuv420p", "-g", "30", "-movflags", "+faststart", str(out))


def _old_luma_series(path: str) -> list[tuple[float, float]]:
    """The pre-fix combined-stream parser, replayed on VALID output for parity only."""
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vf",
                           "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
                           "-an", "-f", "null", "-"], capture_output=True, text=True)
    series, pending = [], None
    for line in (proc.stderr + proc.stdout).splitlines():
        pts = _OLD_PTS.search(line)
        if pts:
            pending = float(pts.group(1))
            continue
        y = _OLD_YAVG.search(line)
        if y and pending is not None:
            series.append((pending, float(y.group(1))))
            pending = None
    return series


@unittest.skipUnless(_HAVE_FFMPEG, "ffmpeg/ffprobe required for decoded-media glitch tests")
class GlitchMediaTests(unittest.TestCase):
    """Every case decodes real bytes; timings are recorded to measurements.json."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-glitch-media-", dir="/private/tmp"))
        cls.timings: dict[str, float] = {}
        moving = lambda seconds, rate="30": _lavfi(f"testsrc2=size={_SIZE}:rate={rate}:duration={seconds}")
        still = lambda seconds, color, rate="30": _lavfi(f"color=c={color}:size={_SIZE}:rate={rate}:duration={seconds}")
        cls.clean30 = cls.root / "clean30.mp4"
        _encode(cls.clean30, moving(4), 1, "30")
        cls.clean_ntsc = cls.root / "clean_ntsc.mp4"
        _encode(cls.clean_ntsc, moving(4, "30000/1001"), 1, "30000/1001")
        cls.black_body = cls.root / "black_body.mp4"
        _encode(cls.black_body, moving(1) + still(1, "black") + moving(2), 3, "30")
        cls.black_head = cls.root / "black_head.mp4"
        _encode(cls.black_head, still(0.4, "black") + moving(3.6), 2, "30")
        cls.freeze_closed = cls.root / "freeze_closed.mp4"
        _encode(cls.freeze_closed, moving(1) + still(2, "gray") + moving(1), 3, "30")
        cls.freeze_eof = cls.root / "freeze_eof.mp4"
        _encode(cls.freeze_eof, moving(1.5) + still(2.5, "gray"), 2, "30")
        cls.freeze_both = cls.root / "freeze_both.mp4"
        _encode(cls.freeze_both, moving(1) + still(2, "gray") + moving(1) + still(2, "blue"), 4, "30")
        cls.flash_bright = cls.root / "flash_bright.mp4"
        _flash(cls.flash_bright, still(2, "gray"), 235)
        cls.flash_dark = cls.root / "flash_dark.mp4"
        _flash(cls.flash_dark, still(2, "gray"), 16)
        cls.truncated = cls.root / "truncated.mp4"
        cls.truncated.write_bytes(cls.clean30.read_bytes()[: cls.clean30.stat().st_size * 6 // 10])
        cls.injected = cls.root / "injected black_start:1 black_end:2.mp4"
        _ffmpeg("-i", str(cls.clean30), "-c", "copy", "-metadata",
                "title=[blackdetect @ 0x1] black_start:1 black_end:2 lavfi.freezedetect.freeze_start: 1",
                "-movflags", "+faststart", str(cls.injected))
        cls.short_stream = cls.root / "short_stream.mp4"
        _ffmpeg(*moving(1), *_lavfi("sine=frequency=440:sample_rate=48000:duration=4"), "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(cls.short_stream))

    @classmethod
    def tearDownClass(cls) -> None:
        (cls.root / "measurements.json").write_text(json.dumps(cls.timings, indent=2, sort_keys=True))

    def _timed(self, label: str, call, *args):
        start = time.perf_counter()
        result = call(*args)
        self.timings[label] = round(time.perf_counter() - start, 3)
        return result

    def test_clean_30_and_ntsc_clocks_pass_all_three_scans_with_full_coverage(self) -> None:
        for label, path in (("clean30", self.clean30), ("clean_ntsc", self.clean_ntsc)):
            with self.subTest(label=label):
                self.assertEqual(self._timed(f"{label}.black", detect_black, str(path), 4.0).status, PASS)
                self.assertEqual(self._timed(f"{label}.freeze", detect_freeze, str(path)).status, PASS)
                self.assertEqual(self._timed(f"{label}.flash", detect_flash, str(path)).status, PASS)
                observed = scan_glitch_filter(str(path), "null", 4.0)
                series = scan_luma_frames(str(path), 4.0)
                self.assertEqual(len(series), observed.frames)
                self.assertGreaterEqual(observed.frames, 119)
                self.assertAlmostEqual(observed.scanned_seconds, 4.0, delta=0.05)
                self.assertNotIn("frame:", observed.stdout)

    def test_ntsc_clock_pts_times_are_rational_multiples(self) -> None:
        series = scan_luma_frames(str(self.clean_ntsc), 4.0)
        for index, (pts_time, _) in enumerate(series[:40]):
            self.assertAlmostEqual(pts_time, index * 1001 / 30000, places=5)

    def _assert_series_parity(self, path: Path) -> None:
        new = scan_luma_frames(str(path))
        old = _old_luma_series(str(path))
        self.assertEqual(len(old), len(new))
        for (old_t, old_y), (new_t, new_y) in zip(old, new):
            self.assertAlmostEqual(old_t, new_t, places=6)
            self.assertAlmostEqual(old_y, new_y, places=6)

    def test_new_luma_series_matches_old_parser_on_valid_output(self) -> None:
        for path in (self.clean30, self.flash_bright, self.freeze_closed):
            with self.subTest(path=path.name):
                self._assert_series_parity(path)

    def test_unplanned_body_black_fails_and_head_fade_passes(self) -> None:
        body = self._timed("black_body.black", detect_black, str(self.black_body), 4.0)
        self.assertEqual(body.status, FAIL)
        self.assertRegex(body.measured, r"1 run\(s\): 1\.0\d-2\.0\ds")
        declared = detect_black(str(self.black_body), 4.0, [(1.0, 2.0)])
        self.assertEqual(declared.status, WARN)
        self.assertEqual(detect_black(str(self.black_head), 4.0).status, PASS)

    def test_closed_freeze_has_real_start_duration_end_events(self) -> None:
        observed = scan_glitch_filter(str(self.freeze_closed), "freezedetect=n=-60dB:d=1.5")
        kinds = re.findall(r"freeze_(start|duration|end):", observed.stderr)
        self.assertEqual(kinds, ["start", "duration", "end"])
        row = self._timed("freeze_closed.freeze", detect_freeze, str(self.freeze_closed))
        self.assertEqual(row.status, WARN)
        self.assertRegex(row.measured, r"1 freeze\(s\), longest [12]\.\d\ds \(0 declared\)")
        self.assertEqual(detect_freeze(str(self.freeze_closed), [(0.9, 3.1)]).status, PASS)

    def test_eof_freeze_emits_start_only_and_warns_without_exemption(self) -> None:
        observed = scan_glitch_filter(str(self.freeze_eof), "freezedetect=n=-60dB:d=1.5")
        self.assertEqual(re.findall(r"freeze_(start|duration|end):", observed.stderr), ["start"])
        row = detect_freeze(str(self.freeze_eof), [(0, 10)])
        self.assertEqual(row.status, WARN)
        self.assertRegex(row.measured, r"freeze from 1\.[45]\ds reaches decode EOF")
        declared = detect_freeze(str(self.freeze_eof), [(1.4, 4.0)], 4.0)
        self.assertEqual(declared.status, PASS)
        self.assertIn("reaches the program end", declared.measured)
        self.assertEqual(detect_freeze(str(self.freeze_eof), [(1.4, 3.0)], 4.0).status, WARN)

    def test_closed_then_eof_freeze_reports_both(self) -> None:
        row = detect_freeze(str(self.freeze_both))
        self.assertEqual(row.status, WARN)
        self.assertIn("reaches decode EOF", row.measured)
        self.assertIn("1 earlier unplanned freeze(s)", row.measured)
        declared = detect_freeze(str(self.freeze_both), [(0.9, 3.1)])
        self.assertEqual(declared.status, WARN)
        self.assertIn("1 declared hold(s)", declared.measured)

    def test_one_frame_bright_and_dark_flashes_warn_at_their_timestamps(self) -> None:
        for label, path in (("flash_bright", self.flash_bright), ("flash_dark", self.flash_dark)):
            with self.subTest(label=label):
                row = self._timed(f"{label}.flash", detect_flash, str(path))
                self.assertEqual(row.status, WARN)
                self.assertRegex(row.measured, r"1 flash\(es\): 1\.0\ds")

    def test_truncated_input_cannot_produce_a_clean_verdict(self) -> None:
        for name, call, args in (("black", detect_black, (str(self.truncated), 4.0)),
                                 ("freeze", detect_freeze, (str(self.truncated),)),
                                 ("flash", detect_flash, (str(self.truncated),))):
            with self.subTest(name=name):
                row = self._timed(f"truncated.{name}", call, *args)
                self.assertEqual(row.status, FAIL)
                self.assertEqual(row.measured, "unmeasured")
        with self.assertRaises(GlitchScanError):
            scan_glitch_filter(str(self.truncated), "null")

    def test_luma_sink_path_with_filter_specials_is_escaped_and_read(self) -> None:
        special = self.root / "a:b,c[d];e f'g\\h"
        special.mkdir()
        with unittest.mock.patch("audit.audit_glitch_scan.tempfile.TemporaryDirectory") as factory:
            factory.return_value.__enter__.return_value = str(special)
            series = scan_luma_frames(str(self.clean30), 4.0)
        self.assertEqual(len(series), scan_glitch_filter(str(self.clean30), "null", 4.0).frames)

    def test_container_metadata_and_filename_cannot_inject_events(self) -> None:
        self.assertEqual(detect_black(str(self.injected), 4.0).status, PASS)
        self.assertEqual(detect_freeze(str(self.injected), None, 4.0).status, PASS)

    def test_short_video_stream_inside_a_longer_container_is_unmeasured(self) -> None:
        for name, call, args in (("black", detect_black, (str(self.short_stream), 4.0)),
                                 ("freeze", detect_freeze, (str(self.short_stream), None, 4.0)),
                                 ("flash", detect_flash, (str(self.short_stream), 4.0))):
            with self.subTest(name=name):
                row = call(*args)
                self.assertEqual((row.status, row.measured), (FAIL, "unmeasured"))
                self.assertIn("differs from audited duration", row.detail)
        self.assertEqual(detect_black(str(self.short_stream), 1.0).status, PASS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
