"""Small actual synthetic codec tests; no source ingest or editorial qualification."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cut_preview_io import write_new
from studio.native_runtime import digest
from studio.native_segments.manifest import Tools, describe_piece, packet_table
from studio.native_segments.review_media import PackageMediaInputs, build_package, derive_media, local_pieces


def command(args: list[str]) -> bytes:
    """Run bounded generated test media through the launcher-provided FFmpeg."""
    return subprocess.run(args, check=True, capture_output=True, timeout=30).stdout


class ReviewPackageMediaTests(unittest.TestCase):
    """Exercise real concat, PCM excerpt, AAC padding and final sRGB correction."""

    def setUp(self) -> None:
        """Use generated colors/tones only, isolated from any production authority."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.tools = {name: str(Path(shutil.which(name)).resolve()) for name in ('ffmpeg', 'ffprobe')}
        self.canvas = {'width': 64, 'height': 36, 'frameRate': '25/1', 'totalFrames': 100}
        self.request = {'output': str(self.root), 'tools': self.tools,
                        'revision': {'canvas': self.canvas, 'grid': {'timescale': 25}}}
        write_new(self.root / 'export-request.json', self.request)
        self.scope = {'id': 'TEST chunk', 'kind': 'chunk', 'frameRange': [10, 30]}
        self.values = [self.picture(index, color) for index, color in enumerate(('red', 'blue'))]
        master = self.root / 'master.wav'
        command([self.tools['ffmpeg'], '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
                 'sine=frequency=440:sample_rate=48000:duration=4', '-ac', '2', '-c:a', 'pcm_f32le', str(master)])
        receipt = self.root / 'master.json'
        write_new(receipt, {'output': str(master), 'masterSha256': digest(master)})
        self.prepared = {'masterReceipt': str(receipt), 'masterReceiptSha256': digest(receipt)}

    def picture(self, index: int, color: str) -> dict:
        """Generate compatible closed-GOP source windows with an obvious synthetic seam."""
        file = self.root / f'window-{index}.mp4'
        command([self.tools['ffmpeg'], '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
                 f'color=c={color}:s=64x36:r=25:d=0.4', '-an', '-c:v', 'libx264', '-preset', 'ultrafast',
                 '-tune', 'zerolatency', '-pix_fmt', 'yuv420p', '-bf', '0', '-g', '10', '-keyint_min', '10',
                 '-x264-params', 'colorprim=bt709:transfer=bt709:colormatrix=bt709:range=limited',
                 '-sc_threshold', '0', '-color_range', 'tv', '-colorspace', 'bt709', '-color_trc', 'bt709',
                 '-color_primaries', 'bt709', '-video_track_timescale', '25', str(file)])
        bounds = 10 + index * 10, 20 + index * 10
        return {'piece': describe_piece(file, bounds, Tools.of(self.request))}

    def test_continuous_mux_preserves_absolute_pcm_and_final_color(self) -> None:
        """Generated media exercises real transformations without production authority."""
        directory = self.root / 'package'
        directory.mkdir()
        inputs = PackageMediaInputs(self.request, self.scope, self.values, self.prepared)
        result = derive_media(inputs, directory)
        self.assertEqual(set(result), {'picture', 'assembly', 'audio', 'mux', 'media'})
        self.assertFalse(list(directory.glob('*stage.json')))
        self.assertTrue(result['assembly']['piecePayloadsIdentical'])
        self.assertEqual(result['assembly']['keyframes'], [0, 10])
        self.assertEqual([result['audio'][key] for key in ('startSample', 'endSampleExclusive')], [19200, 57600])
        self.assertEqual(result['media']['audioClock']['presentedSamples'], 38400)
        self.assertTrue(result['media']['color']['aacPacketsIdentical'])
        file = Path(result['media']['path'])
        streams = json.loads(command([self.tools['ffprobe'], '-v', 'error', '-show_streams', '-of', 'json', str(file)]))
        video = next(row for row in streams['streams'] if row['codec_type'] == 'video')
        self.assertEqual(video['color_transfer'], 'iec61966-2-1')
        self.assertEqual(len(packet_table(file, Tools.of(self.request))), 20)

    def test_gap_and_incompatible_stream_refuse_without_hidden_reencode(self) -> None:
        """Metadata claims cannot bridge a missing frame or change stream interpretation."""
        gap = copy.deepcopy(self.values)
        gap[1]['piece']['startFrame'] += 1
        with self.assertRaisesRegex(ValueError, 'gap or overlap'):
            local_pieces(gap, self.scope)
        incompatible = copy.deepcopy(self.values)
        incompatible[1]['piece']['stream']['color_transfer'] = 'iec61966-2-1'
        with self.assertRaisesRegex(ValueError, 'packet-compatible'):
            local_pieces(incompatible, self.scope)


class ReviewPackageAuthorityTests(unittest.TestCase):
    """Production wrappers retain independent before/after authority checks."""

    def test_invalid_production_inputs_never_reach_media(self) -> None:
        """Extraction cannot turn an invalid request into a media launch."""
        with patch('studio.native_segments.review_media.source_state', side_effect=ValueError('stale')), \
                patch('studio.native_segments.review_media.derive_media') as media:
            with self.assertRaisesRegex(ValueError, 'stale'):
                build_package({}, {}, Path('/unused'))
        media.assert_not_called()

    def test_input_change_during_media_refuses_candidate(self) -> None:
        """Successful media processing cannot bless changed production authority."""
        before, after = ({'generation': 1}, [], {}), ({'generation': 2}, [], {})
        with patch('studio.native_segments.review_media.source_state', side_effect=[before, after]) as source, \
                patch('studio.native_segments.review_media.derive_media', return_value={}) as media:
            with self.assertRaisesRegex(ValueError, 'inputs changed during derivation'):
                build_package({}, {}, Path('/unused'))
        self.assertEqual(source.call_count, 2)
        media.assert_called_once()
