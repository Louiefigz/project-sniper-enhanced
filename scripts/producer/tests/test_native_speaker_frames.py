"""Speaker-observation frame plan and picture pass (REVIEW M1, M4, m1, m4).

This module covers the cap boundary, the sparse phase, exact decimal range bounds, keepalive frames, and
the frame pass over generated arrays. The shared reader is stubbed, so nothing runs ffmpeg or decodes
media.
"""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import numpy as np

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from studio import native_speaker_faces as faces
from studio import native_speaker_observations as observations
from studio import native_speaker_sampling as sampling

CAP = 'Speaker observation sampling exceeds 6000 frames'
SOURCE = {'path': '/synthetic.media', 'resolution': [64, 36], 'duration': 4.0, 'frameRate': '30/1'}


def _plan(*bounds: tuple[float, float], rate: Fraction = Fraction(30)) -> dict:
    """The plan for one clip whose word ranges each hold one word with these (start, end) seconds."""
    words = [{'sourceWord': i, 'text': f'w{i}', 'start': start, 'end': end} for i, (start, end) in enumerate(bounds)]
    scripts = ({'clipId': 'A', 'scriptIdentity': 'a' * 64, 'wordRanges': [[i, i] for i in range(len(bounds))]},)
    request = observations.ObservationRequest(Path('m.json'), Path('t.json'), scripts, Path('o'))
    return observations.observation_plan(request, words, rate)


class PlanBoundaryTests(unittest.TestCase):
    """Exact edges of the sampling rule."""

    def test_cap_boundary_is_6000(self) -> None:
        """35778 frames sample exactly 6000 and pass; one more sampled frame is refused by name (E-S6)."""
        self.assertEqual(len(_plan((0.0, 1192.6))['frames']), 6000)
        with self.assertRaises(ValueError) as refused:
            _plan((0.0, 1192.7))
        self.assertEqual(str(refused.exception), CAP)
        self.assertEqual(sampling.MAX_FRAMES, 6000)

    def test_sparse_phase_counts_from_the_range_start(self) -> None:
        """A range whose first frame (33) is not a multiple of 6 samples 33, 39, 45, ... not 36, 42, 48."""
        plan = _plan((1.1, 5.0))
        self.assertEqual(plan['ranges'][0]['firstFrame'], 33)
        self.assertEqual([row['frame'] for row in plan['frames'] if not row['dense']][:3], [51, 57, 63])

    def test_decimal_bounds_keep_every_frame_inside_the_range(self) -> None:
        """0.3-3.7 s at 30 fps is frames 9..110; binary floats would add frames 8 and 111 (REVIEW m1)."""
        plan = _plan((0.3, 3.7))
        self.assertEqual((plan['ranges'][0]['firstFrame'], plan['ranges'][0]['endFrame']), (9, 111))
        frames = [row['frame'] for row in plan['frames']]
        self.assertEqual((frames[0], frames[-1]), (9, 110))
        at_2997 = _plan((0.3, 3.7), rate=Fraction(30000, 1001))['ranges'][0]
        self.assertEqual((at_2997['firstFrame'], at_2997['endFrame']), (8, 111))


class KeepaliveTests(unittest.TestCase):
    """Decode-only frames bound every stretch of the one decode (REVIEW M1)."""

    def test_keepalives_bound_the_head_gaps_and_tail(self) -> None:
        """From frame 0 to the last counted frame no two selected frames are more than 1800 apart."""
        plan = _plan((400.0, 440.0), (450.0, 480.0))
        selection = sampling.frame_selection({**SOURCE, 'resolution': [64, 36]}, plan, 22322)
        frames, planned = list(selection.frames), {row['frame'] for row in plan['frames']}
        self.assertEqual((frames[0], frames[-1], selection.total_frames), (0, 22321, 22322))
        self.assertLessEqual(max(b - a for a, b in zip(frames, frames[1:])), sampling.KEEPALIVE_FRAMES)
        self.assertEqual(sampling.KEEPALIVE_FRAMES, 1800)
        self.assertTrue(planned <= set(frames))
        self.assertEqual(sampling.keepalive_frames(sorted(planned), 22322), sorted(set(frames) - planned))
        self.assertRaisesRegex(ValueError, 'holds 14399 frames', sampling.frame_selection, SOURCE, plan, 14399)

    def test_keepalive_frames_print_progress_and_are_never_measured(self) -> None:
        """Every decoded frame advances progress; only sampled frames reach the detector and the record."""
        plan = {**_plan((1.0, 1.5)), 'clock': {'frameCount': 120}}
        detected = []

        def detect(image: np.ndarray) -> list[dict]:
            """Stub detector: one face inside the 64x36 frame."""
            detected.append(image.shape)
            return [{'x': 10.0, 'y': 5.0, 'w': 12.0, 'h': 14.0, 'score': 0.9}]

        def reader(_path: Path, selection: object, compare: object, _root: Path) -> tuple[list, dict]:
            """Stands in for the shared reader: hands every selected frame to the pass, in order."""
            return [compare(frame, np.zeros((36, 64, 3), np.uint8)) for frame in selection.frames], {'frames': 0}

        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        request = {'model': {'path': '/model.onnx'}, 'scoreThreshold': 0.7}
        with patch.object(faces, 'face_detector', return_value=detect), \
                patch.object(faces, 'compare_selected_frames', side_effect=reader), \
                contextlib.redirect_stdout(io.StringIO()) as printed:
            rows, sheets, decode = faces.measure_frames(request, SOURCE, plan, root)
        planned = [row['frame'] for row in plan['frames']]
        self.assertEqual([row['frame'] for row in rows], planned)
        self.assertEqual(len(detected), len(planned))
        self.assertEqual((decode['keepaliveFrames'], decode['keepaliveEvery']), (2, 1800))
        self.assertEqual(len(printed.getvalue().splitlines()), len(planned) + 2)
        self.assertEqual(printed.getvalue().splitlines()[-1], f'SNIPER_PROGRESS speaker-frames {len(planned) + 2}')
        self.assertEqual([Path(row['path']).name for row in sheets], ['A-1.jpg'])


class FaceBoxTests(unittest.TestCase):
    """A box wholly outside the frame is refused, never shown as the whole frame (REVIEW m4)."""

    def test_out_of_frame_box_refused(self) -> None:
        """In the frame pass and in the tiles; a partly outside box is kept."""
        frame = np.zeros((36, 64, 3), np.uint8)
        outside = {'frame': 7, 't': 0.2, 'faces': [{'x': 70.0, 'y': 5.0, 'w': 10.0, 'h': 10.0, 'score': 0.9}]}
        self.assertRaisesRegex(ValueError, 'lies outside the 64x36 frame', faces.face_tiles, frame, outside)
        partly = {'frame': 7, 't': 0.2, 'faces': [{'x': -5.0, 'y': 5.0, 'w': 10.0, 'h': 10.0, 'score': 0.9}]}
        self.assertEqual(len(faces.face_tiles(frame, partly)), 1)
        frame_pass = faces.FramePass({7: {'frame': 7, 't': 0.2, 'dense': True}},
                                     lambda _image: outside['faces'], {})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertRaisesRegex(ValueError, 'lies outside', frame_pass, 7, frame)


if __name__ == '__main__':
    unittest.main()
