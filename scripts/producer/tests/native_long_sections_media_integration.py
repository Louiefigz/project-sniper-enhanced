"""Explicit jailed synthetic-media test of section joining, not public Long qualification.

Run through ./sniper and /usr/bin/sandbox-exec with native_localhost_only.sb.
The generated three-second landscape fixture exercises encoded clocks, packet
preservation and complete decode. It grants no playback or editorial approval.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _private_budget_root import use_private_budget_root  # noqa: E402  (tests/ is this script's own folder)
from studio.native_segments.assemble import concat
from studio.native_segments.manifest import Tools, check_compatible, check_coverage, describe_piece
from studio.native_segments.verify import verify_assembly


class LongSectionsMediaTests(unittest.TestCase):
    """Use actual generated H.264 bytes; all checks run inside the caller's media jail."""

    def setUp(self) -> None:
        """Require available local tools and an isolated temporary artifact directory."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
        if not ffmpeg or not ffprobe:
            self.skipTest('FFmpeg/ffprobe required for actual encoded-media evidence')
        self.tools = Tools(ffmpeg, ffprobe)

    def encode(self, start: int, width: int = 320) -> dict:
        """Encode one 30-frame globally timed section using the closed-GOP contract."""
        output = self.root / f'section-{start}-{width}.mp4'
        source = (f'testsrc2=size={width}x180:rate=30,trim=start_frame={start}:'
                  f'end_frame={start + 30},setpts=PTS-STARTPTS')
        command = [self.tools.ffmpeg, '-nostdin', '-v', 'error', '-n', '-f', 'lavfi', '-i', source,
                   '-frames:v', '30', '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '15',
                   '-bf', '0', '-g', '30', '-keyint_min', '30', '-sc_threshold', '0',
                   '-x264-params', 'colorprim=bt709:transfer=bt709:colormatrix=bt709',
                   '-colorspace:v', 'bt709', '-color_primaries:v', 'bt709', '-color_trc:v', 'bt709',
                   '-color_range', 'tv', '-video_track_timescale', '15360', '-pix_fmt', 'yuv420p',
                   str(output)]
        subprocess.run(command, check=True, capture_output=True, timeout=60)
        return describe_piece(output, (start, start + 30), self.tools)

    def test_three_sections_join_without_changed_packets_or_frame_clock(self) -> None:
        """All 90 frames retain their per-section payloads and decode through both joins."""
        pieces = [self.encode(start) for start in (0, 30, 60)]
        check_coverage(pieces, 90)
        reference = pieces[0]['stream']
        check_compatible(pieces, reference)
        output = self.root / 'joined.mp4'
        concat(pieces, output, self.tools, 15360)
        result = verify_assembly(output, pieces, self.tools, reference)
        self.assertEqual(result['packets'], 90)
        self.assertEqual(result['keyframes'], [0, 30, 60])
        self.assertTrue(result['piecePayloadsIdentical'])
        subprocess.run([self.tools.ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-err_detect',
                        'explode', '-i', str(output), '-f', 'null', '-'],
                       check=True, capture_output=True, timeout=60)

    def test_missing_section_is_refused_before_concat(self) -> None:
        """A/C alone cannot silently remove B's 30-frame range from the program."""
        pieces = [self.encode(start) for start in (0, 60)]
        with self.assertRaises(ValueError):
            check_coverage(pieces, 90)

    def test_mismatched_section_stream_is_refused_without_reencode(self) -> None:
        """A section encoded at different geometry cannot enter packet-copy assembly."""
        first, incompatible = self.encode(0), self.encode(30, 640)
        with self.assertRaisesRegex(ValueError, 'not packet-compatible'):
            check_compatible([first, incompatible], first['stream'])


if __name__ == '__main__':
    use_private_budget_root()  # private budget authority; the host pool stays real (T0 supervised-script rule)
    unittest.main()
