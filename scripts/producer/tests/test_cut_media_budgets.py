"""Explicit long-form byte budgets must not relax the private preview default."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import call, patch

from _common import *  # noqa: F401,F403
from cut_preview_audio import AudioContext, render_source_audio
from cut_preview_io import MAX_MEDIA
from cut_preview_media import observe_media
from cut_preview_picture import picture_clock


class CutMediaBudgetTests(unittest.TestCase):
    """Prove bound propagation, real byte rejection and unchanged clock checks."""

    def test_picture_checks_both_reads_with_the_explicit_budget(self) -> None:
        document = {'streams': [{'start_pts': 0, 'time_base': '1/30', 'r_frame_rate': '30/1'}],
            'packets': [{'pts': 0, 'dts': 0, 'duration': 1, 'size': 4, 'data_hash': 'SHA256:' + 'a' * 64}]}
        response = subprocess.CompletedProcess([], 0, json.dumps(document).encode(), b'')
        for budget in (MAX_MEDIA, 3 * 1024 ** 3):
            with patch('cut_preview_picture.file_hash', return_value='b' * 64) as hashed, \
                    patch('cut_preview_picture.run_bounded', return_value=response):
                arguments = () if budget == MAX_MEDIA else (budget,)
                result = picture_clock(Path('/unused.mp4'), 'ffprobe', *arguments)
                self.assertEqual(result['packetCount'], 1)
                self.assertEqual(hashed.call_args_list, [call(Path('/unused.mp4'), budget)] * 2)

    def test_real_byte_limits_are_not_disabled_by_the_new_argument(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / 'bounded.mp4'
            path.write_bytes(b'bounded-media')
            with patch('cut_preview_picture.run_bounded') as probe:
                with self.assertRaisesRegex(RuntimeError, 'over budget'):
                    picture_clock(path, 'ffprobe', 4)
                probe.assert_not_called()
            with patch('cut_preview_media.probe') as probe:
                with self.assertRaisesRegex(RuntimeError, 'over budget'):
                    observe_media(path, {}, {}, 4)
                probe.assert_not_called()
            path.unlink()
            path.symlink_to(Path(temporary).resolve() / 'missing.mp4')
            with self.assertRaises(OSError):
                picture_clock(path, 'ffprobe', 3 * 1024 ** 3)

    def test_media_observation_passes_the_budget_to_both_hashes(self) -> None:
        video = dict(codec_type='video', codec_name='h264', pix_fmt='yuv420p', width=1920,
            height=1080, r_frame_rate='30/1', avg_frame_rate='30/1', start_pts=0, nb_read_frames='30')
        audio = dict(codec_type='audio', codec_name='aac', sample_rate='48000', channels=2,
            channel_layout='stereo', time_base='1/48000', duration_ts=48000, start_pts=0)
        profile = dict(width=1920, height=1080, fps='30/1')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / 'media.mp4'
            path.write_bytes(b'fixture')
            with patch('cut_preview_media.file_hash', return_value='a' * 64) as hashed, \
                    patch('cut_preview_media.probe', return_value={'streams': [video, audio]}), \
                    patch('cut_preview_media._decode_pcm', return_value=48128):
                result = observe_media(path, profile, {'ffmpeg': 'ffmpeg', 'ffprobe': 'ffprobe'}, 3 * 1024 ** 3)
                self.assertEqual(result['audio']['presentationVsVideoSamples'], 0)
                self.assertEqual(hashed.call_args_list, [call(path, 3 * 1024 ** 3)] * 2)

    def test_audio_passes_explicit_budget_without_changing_mux_quality(self) -> None:
        context = AudioContext({}, {}, Path('/unused'), {'fps': '30/1'},
            {'ffmpeg': 'ffmpeg', 'ffprobe': 'ffprobe'}, {})
        row = {'endSample': 48000}
        with patch('cut_preview_audio._channel_authorities', return_value={}), \
                patch('cut_preview_audio._float_parts', return_value=([row], Path('/unused'))), \
                patch('cut_preview_audio._concatenate'), patch('cut_preview_audio.origin_arguments', return_value=[]), \
                patch('cut_preview_audio.picture_clock', return_value={}) as clock, \
                patch('cut_preview_audio.verify_picture_origin', return_value={}), \
                patch('cut_preview_audio._run') as mux, patch('cut_preview_audio.write_new'), \
                patch('cut_preview_audio.file_hash', return_value='a' * 64):
            render_source_audio(context, 3 * 1024 ** 3)
            self.assertEqual(clock.call_args_list, [
                call(Path('/unused/cut-concat.mp4'), 'ffprobe', 3 * 1024 ** 3),
                call(Path('/unused/cut-preview.mp4'), 'ffprobe', 3 * 1024 ** 3)])
            command = mux.call_args.args[0]
            self.assertEqual(command[command.index('-c:v') + 1], 'copy')
            self.assertEqual(command[command.index('-b:a') + 1], '192k')


if __name__ == '__main__':
    unittest.main(verbosity=2)
