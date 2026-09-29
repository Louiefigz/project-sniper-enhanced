"""P2-06 speaker observations: the six plan tests, all synthetic.

Inputs are stereo tones, planned frame lists, a stub face detector and a worker with no live owner.
Nothing here runs ``observe``, reads real media or decodes anything (G17, O24).
"""
from __future__ import annotations

import os
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import numpy as np

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from producer_config import FACE_TRACK
from studio import native_speaker_observations as observations
from studio.native_speaker_observations import ObservationRequest

RATE = 8000
IDENTITY = 'a' * 64
CAP = 'Speaker observation sampling exceeds 6000 frames'


def _tone(seconds: float, amplitude: float) -> np.ndarray:
    """A 1 kHz sine (inside the 120-3400 Hz speech band) sampled at RATE."""
    return amplitude * np.sin(2 * np.pi * 1000.0 * np.arange(round(seconds * RATE)) / RATE)


def _words(bounds: list[tuple[float, float]]) -> list[dict]:
    """Transcript word rows for (start, end) pairs, numbered in order."""
    return [{'sourceWord': index, 'text': f'w{index}', 'start': start, 'end': end}
            for index, (start, end) in enumerate(bounds)]


def _request(*scripts: tuple[str, list[list[int]]]) -> ObservationRequest:
    """A request whose files the pure functions under test never open."""
    rows = tuple({'clipId': clip, 'scriptIdentity': IDENTITY, 'wordRanges': ranges} for clip, ranges in scripts)
    return ObservationRequest(Path('manifest.json'), Path('transcript.json'), rows, Path('observations'))


class StereoTests(unittest.TestCase):
    """Per-word speech-band levels on the 8 kHz filter clock."""

    def test_stereo_sign_follows_louder_channel(self) -> None:
        """Left louder gives a positive lrDb, right louder a negative one; any rate but 8000 Hz is refused by name."""
        left = np.concatenate([_tone(1.0, 0.5), _tone(1.0, 0.1)])
        right = np.concatenate([_tone(1.0, 0.1), _tone(1.0, 0.5)])
        samples = np.stack([left, right], axis=1)
        words = _words([(0.3, 0.7), (1.3, 1.7)])
        rows = observations.stereo_rows(samples, words, RATE)
        self.assertEqual([(row['sourceWord'], row['start'], row['end']) for row in rows], [(0, 0.3, 0.7), (1, 1.3, 1.7)])
        self.assertAlmostEqual(rows[0]['lrDb'], 20 * np.log10(5), delta=0.3)
        self.assertAlmostEqual(rows[1]['lrDb'], -20 * np.log10(5), delta=0.3)
        self.assertGreater(rows[0]['leftDb'], rows[0]['rightDb'])
        self.assertTrue(all(row['active'] is True for row in rows))
        self.assertIsNone(observations.stereo_cue(samples, RATE))
        for rate in (48000, 16000, 8000.0):
            self.assertRaisesRegex(ValueError, f'must be decoded at 8000 Hz.*got {rate!r} Hz',
                                   observations.stereo_rows, samples, words, rate)

    def test_mono_source_has_no_stereo_cue(self) -> None:
        """Mono or a dead channel: lrDb is null for every word and the limit is named; activity is still measured."""
        words = _words([(0.2, 0.6), (1.0, 1.4)])
        mono = _tone(2.0, 0.5)
        for samples in (mono, mono.reshape(-1, 1)):
            rows = observations.stereo_rows(samples, words, RATE)
            self.assertEqual({(row['leftDb'], row['rightDb'], row['lrDb']) for row in rows}, {(None, None, None)})
            self.assertTrue(all(row['active'] is True for row in rows))
            self.assertIn('Mono source', observations.stereo_cue(samples, RATE))
        dead = np.stack([mono, np.zeros_like(mono)], axis=1)
        rows = observations.stereo_rows(dead, words, RATE)
        self.assertEqual([row['lrDb'] for row in rows], [None, None])
        self.assertGreater(rows[0]['leftDb'], rows[0]['rightDb'])
        self.assertIn('Dead channel', observations.stereo_cue(dead, RATE))


class SamplingTests(unittest.TestCase):
    """Which source frames are sampled, and the 6000-frame cap."""

    def test_dense_frames_at_range_end_and_joins(self) -> None:
        """Every 6th frame inside a range, every frame in its last 1.0 s and first 0.5 s, nothing between ranges."""
        words = _words([(index * 0.5, index * 0.5 + 0.5) for index in range(40)])
        plan = observations.observation_plan(_request(('A', [[0, 7], [20, 29]])), words, Fraction(30))
        first = [*range(0, 15), *range(18, 90, 6), *range(90, 120)]
        second = [*range(300, 315), *range(318, 420, 6), *range(420, 450)]
        self.assertEqual([row['frame'] for row in plan['frames']], first + second)
        dense = {row['frame'] for row in plan['frames'] if row['dense']}
        self.assertEqual(dense, {*range(0, 15), *range(90, 120), *range(300, 315), *range(420, 450)})
        self.assertEqual([(row['clipId'], row['wordRange'], row['firstFrame'], row['endFrame']) for row in plan['ranges']],
                         [('A', [0, 7], 0, 120), ('A', [20, 29], 300, 450)])
        self.assertEqual(plan['frames'][-1], {'frame': 449, 't': 14.966667, 'dense': True})
        shared = observations.observation_plan(_request(('B', [[6, 9]]), ('A', [[0, 7]])), words, Fraction(30))
        frames = {row['frame']: row['dense'] for row in shared['frames']}
        self.assertEqual(sorted(frames), [*range(0, 15), *range(18, 90, 6), *range(90, 150)])
        self.assertTrue(all(frames[frame] for frame in range(90, 150)))
        self.assertEqual([row['clipId'] for row in shared['ranges']], ['A', 'B'])

    def test_sampling_cap_refuses(self) -> None:
        """More than 6000 frames is refused by name, for one long range or for the union of the batch's clips."""
        words = _words([(0.0, 600.0), (600.0, 1300.0), (1300.0, 1400.0)])
        with self.assertRaises(ValueError) as long_range:
            observations.observation_plan(_request(('A', [[0, 1]])), words, Fraction(30))
        self.assertEqual(str(long_range.exception), CAP)
        alone = observations.observation_plan(_request(('B', [[1, 1]])), words, Fraction(30))
        self.assertLessEqual(len(alone['frames']), 6000)
        with self.assertRaises(ValueError) as union:
            observations.observation_plan(_request(('A', [[0, 0]]), ('B', [[1, 1]])), words, Fraction(30))
        self.assertEqual(str(union.exception), CAP)


class FaceTests(unittest.TestCase):
    """Face boxes per sampled frame, from an injected stub detector."""

    def test_faces_recorded_in_source_pixels(self) -> None:
        """Detection-pixel boxes map to source pixels per axis; faces below the FACE_TRACK threshold are dropped."""
        threshold = FACE_TRACK['yunet_score_threshold']
        boxes = {12: [{'x': 400.0, 'y': 90.0, 'w': 60.0, 'h': 80.0, 'score': 0.91},
                      {'x': 100.0, 'y': 80.0, 'w': 50.0, 'h': 70.0, 'score': threshold},
                      {'x': 700.0, 'y': 10.0, 'w': 20.0, 'h': 20.0, 'score': threshold - 0.01}],
                 18: []}
        seen = []

        def detect(row: dict) -> list[dict]:
            """The stub detector: fixed boxes per frame, in detection pixels."""
            seen.append(row['frame'])
            return boxes[row['frame']]

        frames = [{'frame': 12, 't': 0.4, 'dense': True, 'scale': [1.5, 2.0]},
                  {'frame': 18, 't': 0.6, 'dense': False, 'scale': [3.0, 3.0]}]
        rows = observations.face_rows(frames, detect)
        self.assertEqual(seen, [12, 18])
        self.assertEqual(rows, [
            {'frame': 12, 't': 0.4, 'faces': [{'x': 150.0, 'y': 160.0, 'w': 75.0, 'h': 140.0, 'score': threshold},
                                              {'x': 600.0, 'y': 180.0, 'w': 90.0, 'h': 160.0, 'score': 0.91}]},
            {'frame': 18, 't': 0.6, 'faces': []}])


class WorkerTests(unittest.TestCase):
    """The worker runs only under its live inspection owner."""

    def _assert_refused(self, file: Path, environment: dict, message: str) -> None:
        """The worker raises ``message`` and never reaches its inputs, the audio decode or the frame pass."""
        guard = AssertionError('the worker reached its inputs or media')
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(observations, 'current_inputs', side_effect=guard), \
                patch.object(observations, 'decode_audio', side_effect=guard), \
                patch.object(observations, 'measure_frames', side_effect=guard), \
                self.assertRaisesRegex(ValueError, message):
            observations.worker(file)

    def test_worker_refuses_detached_request(self) -> None:
        """No live owner in the environment, or another owner's record: refused before any input or media."""
        folder = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        file = folder / 'request.json'
        file.write_text('{}\n')
        detached = {key: value for key, value in os.environ.items() if not key.startswith('SNIPER_INSPECTION_')}
        other = {**detached, 'SNIPER_INSPECTION_REQUEST': str(file),
                 'SNIPER_INSPECTION_OWNER': str(folder / 'another.render.json')}
        self._assert_refused(file, detached, 'Inspection requires its live owner')
        self._assert_refused(file, other, 'Inspection owner changed')
        self.assertEqual([path.name for path in folder.iterdir()], ['request.json'])


if __name__ == '__main__':
    unittest.main()
