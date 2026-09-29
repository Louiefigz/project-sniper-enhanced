"""Speaker-observation contract items the six P2-06 tests do not reach (REVIEW M4, M2, m2, m3, m6).

All synthetic: the source "media" is a few text bytes that are only hashed; subprocesses are stubbed at
``run_bounded``; nothing runs ffmpeg, ffprobe, ``observe`` or the owner, and nothing reads footage.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import numpy as np

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from producer_config import FACE_TRACK
from studio import native_speaker_inputs as inputs
from studio import native_speaker_media as media
from studio import native_speaker_observations as observations
from studio.native_speaker_sampling import source_clock

RATE = 8000
RECORD_KEYS = {'schemaVersion', 'kind', 'source', 'scripts', 'rate', 'words', 'faces', 'sampling', 'sheets',
               'tools', 'limits'}
FIRST_LIMIT = ('Measurements are cues, not attribution; stills do not establish lip synchronization; '
               'nothing here is listening.')
SOURCE = {'id': 'raw-1', 'duration': 4.0, 'frameRate': '30/1', 'vfr': False, 'resolution': [64, 36], 'rotation': 0,
          'audio': {'present': True, 'channels': 2, 'sampleRate': 48000}}
PROBE = {'streams': [{'codec_type': 'video', 'nb_read_packets': '120', 'duration': '4.000000', 'start_time': '0.000000'},
                     {'codec_type': 'audio', 'nb_read_packets': '188', 'duration': '4.010000', 'start_time': '0.000000'}]}


def _sha(path: Path) -> str:
    """SHA-256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> Path:
    """Write JSON and return the path."""
    path.write_text(json.dumps(value))
    return path


def _tone(seconds: float, amplitude: float) -> np.ndarray:
    """A 1 kHz sine at RATE."""
    return amplitude * np.sin(2 * np.pi * 1000.0 * np.arange(round(seconds * RATE)) / RATE)


class Fixture(unittest.TestCase):
    """A synthetic source, transcript, manifest, tools and a frozen worker request."""

    def setUp(self) -> None:
        """Files in a private temp folder; the 'media' and 'tools' are plain bytes, never executed or decoded."""
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.media, self.tool = self.folder / 'source.media', self.folder / 'ffmpeg'
        self.media.write_bytes(b'synthetic source bytes')
        self.tool.write_bytes(b'not executed')
        self.source = {**SOURCE, 'path': str(self.media), 'sourceSha256': _sha(self.media)}
        self.manifest = _write(self.folder / 'asset_manifest.json', {'sources': [self.source]})
        words = [{'word': f'w{i}', 'start': i * 0.5, 'end': i * 0.5 + 0.5} for i in range(8)]
        self.transcript = _write(self.folder / 'raw-1.json', {'transcript': [{'words': words}]})
        self.scripts = ({'clipId': 'A', 'scriptIdentity': 'a' * 64, 'wordRanges': [[1, 2]]},)
        request = observations.ObservationRequest(self.manifest, self.transcript, self.scripts, self.folder / 'out')
        self.body = {**inputs.inspection_request(request),
                     'tools': {'ffmpeg': str(self.tool), 'ffprobe': str(self.tool)}}

    def measure(self, decode: object) -> dict:
        """``_measure`` with the subprocesses stubbed; ``decode`` stands in for the audio decode."""
        faces = ([], [], {'frames': 0})
        with patch.object(observations, '_pinned_decoders'), \
                patch.object(observations, 'probe_streams', return_value=PROBE), \
                patch.object(observations, 'decode_audio', side_effect=decode), \
                patch.object(observations, 'measure_frames', return_value=faces), \
                contextlib.redirect_stdout(io.StringIO()):
            return observations._measure(self.body, observations.current_inputs(self.body), self.folder)


class RecordTests(Fixture):
    """The record's keys and identities, and the source re-hash around the decode."""

    def test_record_keys_and_bound_identities(self) -> None:
        """Exactly the P2-06 keys; source and transcript identities, scripts with word ranges, P2's first limit."""
        record = self.measure(lambda *_: np.stack([_tone(2.0, 0.5), _tone(2.0, 0.1)], axis=1))
        self.assertEqual(set(record), RECORD_KEYS)
        self.assertEqual(record['source'], {'id': 'raw-1', 'sourceSha256': self.source['sourceSha256'],
                                            'transcriptSha256': _sha(self.transcript)})
        self.assertEqual(record['scripts'], [{'clipId': 'A', 'scriptIdentity': 'a' * 64, 'wordRanges': [[1, 2]]}])
        self.assertEqual(record['limits'][0], FIRST_LIMIT)
        self.assertEqual(record['tools'], {'ffmpegSha256': _sha(self.tool), 'modelSha256': self.body['model']['sha256'],
                                           'detector': 'yunet-2023mar', 'scoreThreshold': 0.7})
        self.assertEqual(record['sampling']['clock']['frameCount'], 120)
        self.assertEqual(record['sampling']['audio'], {'sampleRate': 8000, 'channels': 2})
        self.assertEqual([row['sourceWord'] for row in record['words']], [1, 2])
        mono = self.measure(lambda *_: _tone(2.0, 0.5).reshape(-1, 1))
        self.assertEqual(mono['limits'][3:], ['Mono source: there is no left-right cue, so lrDb is null for every word.'])

    def test_source_rehashed_before_and_after_the_decode(self) -> None:
        """Changed bytes are refused before any subprocess, and again when they change during the decode."""
        guard = AssertionError('reached a subprocess')
        self.body['source'] = {**self.body['source'], 'sourceSha256': '0' * 64}
        with patch.object(observations, '_pinned_decoders'), \
                patch.object(observations, 'probe_streams', side_effect=guard), \
                patch.object(observations, 'decode_audio', side_effect=guard), contextlib.redirect_stdout(io.StringIO()):
            self.assertRaisesRegex(ValueError, 'source bytes changed before', observations._measure, self.body,
                                   {'source': self.body['source'], 'words': []}, self.folder)
        self.body['source'] = self.source

        def rewrite(*_: object) -> np.ndarray:
            """The decode 'sees' the file change underneath it."""
            self.media.write_bytes(b'other bytes')
            return np.stack([_tone(2.0, 0.5), _tone(2.0, 0.1)], axis=1)

        self.assertRaisesRegex(ValueError, 'source bytes changed after', self.measure, rewrite)

    def test_decoder_pin(self) -> None:
        """The frame reader's PATH ffmpeg/ffprobe must be the pinned tools."""
        tools = {'ffmpeg': str(self.tool), 'ffprobe': str(self.tool)}
        with patch.object(observations.shutil, 'which', return_value=str(self.tool)):
            observations._pinned_decoders(tools)
        with patch.object(observations.shutil, 'which', return_value=str(self.folder / 'another-ffmpeg')):
            self.assertRaisesRegex(ValueError, 'would run another ffmpeg', observations._pinned_decoders, tools)


class InputTests(Fixture):
    """The model, the scripts file's identities and the frame-clock refusals."""

    def test_model_must_be_face_track(self) -> None:
        """A request naming another model file, even with its correct hash, is refused."""
        self.assertEqual(Path(self.body['model']['path']), Path(FACE_TRACK['yunet_model_path']).resolve())
        other = self.folder / 'other.onnx'
        other.write_bytes(b'another model')
        body = {**self.body, 'model': {'path': str(other), 'sha256': _sha(other)}}
        self.assertRaisesRegex(ValueError, 'not the FACE_TRACK model', observations.current_inputs, body)

    def test_scripts_file_names_source_and_transcript(self) -> None:
        """A scripts file on another source or transcript, or without the identities, is refused (REVIEW M2)."""
        rows = [dict(row) for row in self.scripts]
        good = {'sourceSha256': self.source['sourceSha256'], 'transcriptSha256': _sha(self.transcript), 'scripts': rows}
        self.assertEqual(inputs.file_scripts(_write(self.folder / 's.json', good), self.manifest, self.transcript),
                         tuple(rows))
        for change, message in (({'transcriptSha256': 'f' * 64}, 'another source or transcript'),
                                ({'sourceSha256': 'f' * 64}, 'another source or transcript')):
            path = _write(self.folder / 'bad.json', {**good, **change})
            self.assertRaisesRegex(ValueError, message, inputs.file_scripts, path, self.manifest, self.transcript)
        old = _write(self.folder / 'old.json', {'scripts': rows})
        self.assertRaisesRegex(ValueError, 'must be', inputs.file_scripts, old, self.manifest, self.transcript)

    def test_source_clock_refusals(self) -> None:
        """Variable frame rate, rotation and malformed rates are refused by name."""
        self.assertEqual(source_clock(SOURCE), Fraction(30))
        for change, message in (({'vfr': True}, 'constant-frame-rate'), ({'vfr': None}, 'constant-frame-rate'),
                                ({'rotation': 90}, 'unrotated'), ({'rotation': None}, 'unrotated'),
                                ({'frameRate': '30'}, "rational frameRate"), ({'frameRate': '30/0'}, "rational frameRate"),
                                ({'resolution': [64]}, 'resolution')):
            self.assertRaisesRegex(ValueError, message, source_clock, {**SOURCE, **change})


class MediaTests(unittest.TestCase):
    """The two subprocess commands, captured at ``run_bounded``, and the stream-clock checks."""

    def test_audio_decoded_at_8000_in_source_channels(self) -> None:
        """``-map 0:a:0``, ``-ar 8000`` and the source's own channel count; mono is never forced to two."""
        for channels in (1, 2):
            source = {**SOURCE, 'path': '/synthetic.media', 'audio': {'present': True, 'channels': channels}}
            done = subprocess.CompletedProcess([], 0, np.zeros(RATE * channels, '<f4').tobytes(), b'')
            with patch.object(media, 'run_bounded', return_value=done) as run:
                samples = media.decode_audio(source, '/pinned/ffmpeg')
            command = run.call_args.args[0]
            self.assertEqual(command[0], '/pinned/ffmpeg')
            self.assertEqual(command[command.index('-ar') + 1], '8000')
            self.assertEqual(command[command.index('-ac') + 1], str(channels))
            self.assertEqual(command[command.index('-map') + 1], '0:a:0')
            self.assertEqual(samples.shape, (RATE, channels))
        three = {**SOURCE, 'path': '/x', 'audio': {'present': True, 'channels': 6}}
        self.assertRaisesRegex(ValueError, 'mono or stereo', media.decode_audio, three, '/pinned/ffmpeg')

    def test_stream_clock(self) -> None:
        """Counted frames match duration x rate within one frame, and audio starts within one frame (REVIEW m2)."""
        done = subprocess.CompletedProcess([], 0, json.dumps(PROBE).encode(), b'')
        with patch.object(media, 'run_bounded', return_value=done) as run:
            probe = media.probe_streams('/synthetic.media', '/pinned/ffprobe')
        self.assertIn('-count_packets', run.call_args.args[0])
        self.assertEqual(media.stream_clock(probe, Fraction(30))['frameCount'], 120)
        video, audio = PROBE['streams']
        cases = (([{**video, 'nb_read_packets': '122'}, audio], 'frame index = time x rate'),
                 ([video, {**audio, 'start_time': '0.050000'}], 'do not share a clock'),
                 ([{**video, 'duration': 'N/A'}, audio], 'no numeric duration'),
                 ([video], 'no audio stream'), ([{**video, 'nb_read_packets': 'N/A'}, audio], 'no counted frames'))
        for streams, message in cases:
            self.assertRaisesRegex(ValueError, message, media.stream_clock, {'streams': streams}, Fraction(30))
        near = {'streams': [video, {**audio, 'start_time': '0.030000'}]}
        self.assertEqual(media.stream_clock(near, Fraction(30))['audioStartSeconds'], 0.03)

    def test_silent_word_has_no_cue_and_a_limit(self) -> None:
        """Digital silence records null levels and a null lrDb, and the limit names the word (REVIEW m3)."""
        samples = np.stack([np.concatenate([_tone(1.0, 0.5), np.zeros(RATE)]),
                            np.concatenate([_tone(1.0, 0.3), np.zeros(RATE)])], axis=1)
        words = [{'sourceWord': 4, 'text': 'a', 'start': 0.2, 'end': 0.6},
                 {'sourceWord': 5, 'text': 'b', 'start': 1.3, 'end': 1.7}]
        rows = observations.stereo_rows(samples, words, RATE)
        self.assertEqual((rows[1]['leftDb'], rows[1]['rightDb'], rows[1]['lrDb'], rows[1]['active']),
                         (None, None, None, False))
        self.assertIsNotNone(rows[0]['lrDb'])
        self.assertEqual(observations.stereo_limits(samples, rows, RATE),
                         ['No active speech-band audio (below -48 dBFS) on source words 5: lrDb is null for those words.'])


if __name__ == '__main__':
    unittest.main()
