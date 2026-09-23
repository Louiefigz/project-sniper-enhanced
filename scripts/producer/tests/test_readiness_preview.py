"""Bounded live preview decode and retained-evidence checks; no editorial claim."""
from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _native_media_fixture import HAVE_NATIVE, valid_mp4
from readiness_preview import observe_preview, verify_preview
from studio.native_run_config import local_environment


@unittest.skipUnless(HAVE_NATIVE, 'needs the native macOS media jail')
class ReadinessPreviewTests(unittest.TestCase):
    """Use real moving pixels/audio through the existing admission owner."""

    def test_decode_reuse_tamper_and_malformed_input(self) -> None:
        """A reused decode must retain its exact snapshot and original bytes."""
        tools, environment = local_environment()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, environment):
            root = Path(temporary).resolve()
            with patch('_native_media_fixture.FFMPEG', tools['ffmpeg']):
                clip = valid_mp4(root / 'preview.mp4', seconds=1)
            evidence = observe_preview(clip, root / 'snapshots')
            verify_preview(evidence)
            self.assertEqual(evidence['admission']['decoded']['facts']['declaredFrames'], 30)
            for key in ('isolation', 'runtime', 'snapshot'):
                invalid = copy.deepcopy(evidence)
                invalid['admission'][key] = {}
                with self.assertRaises((RuntimeError, ValueError, KeyError)):
                    verify_preview(invalid)
            clip.write_bytes(b'TEST corrupt replacement')
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                verify_preview(evidence)
            with self.assertRaises(RuntimeError):
                observe_preview(clip, root / 'rejected')


if __name__ == '__main__':
    unittest.main()
