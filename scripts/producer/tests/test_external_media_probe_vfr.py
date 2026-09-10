"""Timestamp-collision regressions for external-media full decode."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from headless.external_media_probe_policy import MediaProbeLimits, NODE_PROBE
from headless.external_media_snapshot import MAX_EXTERNAL_MEDIA_BYTES

FFMPEG = shutil.which("ffmpeg")


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [FFMPEG or "ffmpeg", "-nostdin", "-v", "error", *arguments],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _decode(path: Path, *, vfr: bool) -> subprocess.CompletedProcess[str]:
    arguments = [
        "-xerror", "-threads", "4", "-i", str(path),
        "-map", "0:v?", "-map", "0:a?",
    ]
    if vfr:
        arguments.extend(("-vsync", "vfr"))
    arguments.extend(("-f", "null", "-"))
    return _run(*arguments)


@unittest.skipUnless(FFMPEG, "ffmpeg required")
class ExternalMediaProbeVfrTests(unittest.TestCase):
    """Output timestamp repair must not weaken decoder failure handling."""

    def test_duplicate_source_timestamp_is_only_an_output_collision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Path(raw) / "duplicate-pts.mkv"
            created = _run(
                "-y", "-f", "lavfi", "-i",
                "testsrc2=size=64x64:rate=30:duration=0.2",
                "-vf", "settb=expr=1/1000,"
                "setpts='if(eq(N,3),67,N*33)'",
                "-vsync", "passthrough", "-c:v", "ffv1", str(fixture),
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            baseline = _decode(fixture, vfr=False)
            self.assertEqual(baseline.returncode, 0, baseline.stderr)
            self.assertIn("non monotonically increasing dts", baseline.stderr)
            repaired = _decode(fixture, vfr=True)
            self.assertEqual(repaired.returncode, 0, repaired.stderr)
            self.assertEqual(repaired.stderr, "")

    def test_vfr_output_does_not_hide_a_real_decode_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            valid, corrupt = root / "valid.ts", root / "corrupt.ts"
            created = _run(
                "-y", "-f", "lavfi", "-i",
                "testsrc2=size=64x64:rate=30:duration=1",
                "-c:v", "mpeg2video", "-f", "mpegts", str(valid),
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            payload = valid.read_bytes()
            self.assertGreater(len(payload), 500)
            corrupt.write_bytes(payload[:-500])
            rejected = _decode(corrupt, vfr=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("decoder", rejected.stderr.lower())


class ExternalMediaProbeVfrContractTests(unittest.TestCase):
    """The embedded container command keeps fail-closed decode semantics."""

    def test_output_repair_does_not_change_source_or_policy_limits(self) -> None:
        # 16 GiB since 2026-09-07: the real long-form source class (C0679, 9.58 GiB)
        # is admitted deliberately; this pin still catches accidental drift.
        self.assertEqual(MAX_EXTERNAL_MEDIA_BYTES, 16 * 1024 ** 3)
        self.assertEqual(asdict(MediaProbeLimits()), {
            "max_bytes": 16 * 1024 ** 3,   # deliberate 2026-09-07 admission-class change
            "max_width": 8192,
            "max_height": 8192,
            "max_frames": 2_000_000,
            "max_duration_seconds": 6 * 60 * 60,
            "max_streams": 32,
            "max_decode_seconds": 20 * 60,
        })

    def test_all_av_streams_decode_with_vfr_output_synchronization(self) -> None:
        compact = "".join(NODE_PROBE.split())
        decode = (
            "'-xerror','-threads','4','-i',input,"
            "'-map','0:v?','-map','0:a?',"
            "'-vsync','vfr','-f','null','-'"
        )
        self.assertIn(decode, compact)
        self.assertNotIn("fps_mode", NODE_PROBE)
        self.assertNotIn("discardcorrupt", NODE_PROBE)
        self.assertNotIn("ignore_err", NODE_PROBE)
        self.assertIn("row.status!==0||String(row.stderr||'').trim()", compact)


if __name__ == "__main__":
    unittest.main()
