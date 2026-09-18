"""Real-media proof for Palmier candidate full-decode authority."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from _common import *  # noqa: F401,F403
from palmier.mcp_client import PalmierError
from palmier.native_qc_export import _full_decode, _stream_count


def _media(path: str) -> None:
    result = subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=24:d=0.5",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=0.5",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", path,
    ], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)


class NativeExportDecodeTests(unittest.TestCase):
    def test_real_candidate_fully_decodes_and_corruption_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            media = os.path.join(tmp, "candidate.mp4")
            _media(media)
            _full_decode(media)
            with open(media, "wb") as handle:
                handle.write(b"not-an-mp4")
            with self.assertRaisesRegex(PalmierError, "full A/V decode"):
                _full_decode(media)

    def test_stream_count_never_aliases_two_audio_authorities(self) -> None:
        probe = {"streams": [
            {"codec_type": "video"},
            {"codec_type": "audio"},
            {"codec_type": "audio"},
            {"codec_type": "subtitle"},
        ]}
        self.assertEqual(_stream_count(probe, "video"), 1)
        self.assertEqual(_stream_count(probe, "audio"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
