"""Retained-Short channel authority wiring with real receipts and mocked media commands."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio.channel_normalization import ChannelAuthority, ChannelRequest, ChannelTools, SourceIdentity
from audio.channel_normalization_receipt import decision, peak_token, seal_channel_receipt
from studio import native_short_dialogue as delivery
from studio import native_short_delivery as pipeline
from studio.native_runtime import digest


class NativeDialogueChannelsTests(unittest.TestCase):
    """Channel choice comes from shared observed policy, before any native loudness mastering."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'retained-reference.wav'
        self.source.write_bytes(b'TEST retained lossless Short')

    def authority(self, peaks: list[float]) -> ChannelAuthority:
        """Seal the same source/decision shape as the shared observer, without invoking codecs."""
        source, sha = str(self.source), digest(self.source)
        tools = ChannelTools('/TEST/ffmpeg', 'a' * 64, '/TEST/ffprobe', 'b' * 64)
        stat = self.source.stat()
        identity = SourceIdentity(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        receipt = seal_channel_receipt({'schemaVersion': 1, 'kind': 'channel-normalization-receipt',
            'source': {'path': source, 'sha256': sha, 'sizeBytes': stat.st_size,
                       'selector': 'a:0', 'selectedStreamIndex': 0},
            'stream': {'codec': 'pcm_f32le', 'sampleRate': 48000, 'channels': 2,
                       'channelLayout': 'stereo', 'peakDbfs': [peak_token(value) for value in peaks]},
            'decision': decision(2, peaks),
            'tools': {'ffmpegPath': tools.ffmpeg_path, 'ffmpegSha256': tools.ffmpeg_sha256,
                      'ffprobePath': tools.ffprobe_path, 'ffprobeSha256': tools.ffprobe_sha256,
                      'peakFilter': 'astats=metadata=0:reset=0'}})
        return ChannelAuthority(ChannelRequest(source, sha, 'a:0', tools), identity, receipt)

    def test_both_dead_channel_orientations_and_verified_stereo_use_the_shared_filter(self) -> None:
        for index, peaks in enumerate(([-80, -10], [-10, -80], [-20, -19])):
            directory = self.root / str(index); directory.mkdir()
            authority = self.authority(peaks)
            def render(command: list[str]) -> str:
                Path(command[-1]).write_bytes(b'TEST normalized float')
                return ''
            with patch.object(delivery, 'system_program_request', return_value=authority.request) as request, \
                    patch.object(delivery, 'observe_channel_authority', return_value=authority) as observe, \
                    patch.object(delivery, 'exact_float_audio_clock', return_value={'samples': 1854720}) as clock, \
                    patch.object(delivery, 'run', side_effect=render) as run:
                output = delivery.normalize_dialogue_reference(self.source, 1854720, directory)
            request.assert_called_once_with(str(self.source)); observe.assert_called_once_with(authority.request)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index('-i') + 1], str(self.source))
            self.assertEqual(command[command.index('-c:a') + 1], 'pcm_f32le')
            self.assertEqual(command[command.index('-af') + 1], authority.filter_for('stereo')
                             + ',aresample=48000,atrim=end_sample=1854720,asetpts=PTS-STARTPTS')
            self.assertEqual(clock.call_count, 2)
            record = json.loads((directory / 'channel-normalization.json').read_text())
            self.assertEqual(record['inputSha256Before'], record['inputSha256After'])
            self.assertEqual(record['outputSha256'], digest(output))
            self.assertEqual(record['channelAuthority'], authority.receipt)
            self.assertEqual(record['status'], 'channel-policy-applied')

    def test_source_change_during_normalization_fails_and_retains_the_authority(self) -> None:
        authority = self.authority([-80, -10])
        def mutate(command: list[str]) -> str:
            Path(command[-1]).write_bytes(b'TEST output')
            self.source.write_bytes(b'mutated retained source')
            return ''
        with patch.object(delivery, 'system_program_request', return_value=authority.request), \
                patch.object(delivery, 'observe_channel_authority', return_value=authority), \
                patch.object(delivery, 'exact_float_audio_clock', return_value={}), \
                patch.object(delivery, 'run', side_effect=mutate), self.assertRaisesRegex(RuntimeError, 'identity changed'):
            delivery.normalize_dialogue_reference(self.source, 1854720, self.root)
        record = json.loads((self.root / 'channel-normalization.json').read_text())
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(record['channelAuthority'], authority.receipt)

    def test_invalid_channel_filter_receipt_cannot_reach_materialization(self) -> None:
        authority = self.authority([-80, -10])
        authority.receipt['decision']['stereoFilter'] = 'anull'
        with patch.object(delivery, 'system_program_request', return_value=authority.request), \
                patch.object(delivery, 'observe_channel_authority', return_value=authority), \
                patch.object(delivery, 'run') as run, self.assertRaises(ValueError):
            delivery.normalize_dialogue_reference(self.source, 1854720, self.root)
        run.assert_not_called()
        self.assertEqual(json.loads((self.root / 'channel-normalization.json').read_text())['status'], 'failed')

    def test_premaster_requires_normalized_reference_before_finishing(self) -> None:
        """The registered concat can only feed finishing through shared channel policy."""
        normalized = self.root / 'normalized.wav'
        request = {'output': str(self.root), 'project': str(self.root),
                   'tools': {'ffmpeg': '/TEST/ffmpeg', 'ffprobe': '/TEST/ffprobe'}}
        canvas = {'frameRate': '25/1', 'totalFrames': 25}
        order = []
        with patch.object(pipeline, 'dialogue_reference', return_value=self.source), \
                patch.object(pipeline, 'normalize_dialogue_reference',
                             side_effect=lambda *args: order.append('normalize') or normalized) as normalize, \
                patch.object(pipeline, 'finish_native_audio',
                             side_effect=lambda *args: order.append('finish') or normalized) as finish:
            self.assertEqual(pipeline.dialogue_premaster(request, canvas, None), normalized)
        normalize.assert_called_once_with(self.source, 48000, self.root)
        self.assertEqual(order, ['normalize', 'finish'])
        self.assertEqual(finish.call_args.args[0].path, str(normalized))

    def test_failed_channel_policy_cannot_reach_native_finishing(self) -> None:
        """A failed normalizer is terminal, with no unnormalized fallback."""
        request = {'output': str(self.root), 'project': str(self.root)}
        canvas = {'frameRate': '25/1', 'totalFrames': 25}
        with patch.object(pipeline, 'dialogue_reference', return_value=self.source), \
                patch.object(pipeline, 'normalize_dialogue_reference', side_effect=RuntimeError('channel policy')), \
                patch.object(pipeline, 'finish_native_audio') as finish, \
                self.assertRaisesRegex(RuntimeError, 'channel policy'):
            pipeline.dialogue_premaster(request, canvas, None)
        finish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
