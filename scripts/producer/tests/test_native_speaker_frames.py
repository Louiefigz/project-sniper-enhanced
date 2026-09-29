"""Speaker-observation frame plan, packet clock and picture pass.

Covers REVIEW M1, M4, m1 and m4, and X78 DM1 and DM-m4.

This module covers:
- the cap boundary, the sparse phase and exact decimal range bounds;
- the packet frame clock, including an IMG_5954-like clock (29.997 fps average, 30/1 nominal);
- keepalive frames;
- the frame pass over generated arrays.

Probes and the shared reader are stubbed, so nothing runs ffmpeg or ffprobe or decodes media.
"""
from __future__ import annotations

import contextlib
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
from studio import native_speaker_faces as faces
from studio import native_speaker_media as media
from studio import native_speaker_observations as observations
from studio import native_speaker_sampling as sampling

CAP = 'Speaker observation sampling exceeds 6000 frames'
SOURCE = {'path': '/synthetic.media', 'resolution': [64, 36], 'duration': 4.0, 'frameRate': '30/1'}
VIDEO = {'codec_type': 'video', 'start_time': '0.000000', 'time_base': '1/600'}
AUDIO = {'codec_type': 'audio', 'start_time': '0.000000', 'time_base': '1/48000'}


def _probe(frames: list[int], video: dict = VIDEO, audio: dict = AUDIO, first: str = '0') -> dict:
    """A probe stub: packets at 20 ticks of 1/600 s per nominal 30p frame index, in the given order, and the
    first decoded audio frame's pts (``first``, in the audio time_base)."""
    return {'streams': [video, audio], 'packets': [(str(20 * n), '___') for n in frames], 'audioFirstPts': first}


def _plan(*bounds: tuple[float, float], rate: Fraction = Fraction(30), clock: object = None) -> dict:
    """The plan for one clip whose word ranges each hold one word with these (start, end) seconds."""
    words = [{'sourceWord': i, 'text': f'w{i}', 'start': start, 'end': end} for i, (start, end) in enumerate(bounds)]
    scripts = ({'clipId': 'A', 'scriptIdentity': 'a' * 64, 'wordRanges': [[i, i] for i in range(len(bounds))]},)
    request = observations.ObservationRequest(Path('m.json'), Path('t.json'), scripts, Path('o'))
    if clock is not None:
        return sampling.frame_plan(request, words, clock)
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
        selection = media.frame_selection({**SOURCE, 'resolution': [64, 36]}, plan, 22322)
        frames, planned = list(selection.frames), {row['frame'] for row in plan['frames']}
        self.assertEqual((frames[0], frames[-1], selection.total_frames), (0, 22321, 22322))
        self.assertLessEqual(max(b - a for a, b in zip(frames, frames[1:])), media.KEEPALIVE_FRAMES)
        self.assertEqual(media.KEEPALIVE_FRAMES, 1800)
        self.assertTrue(planned <= set(frames))
        self.assertEqual(media.keepalive_frames(sorted(planned), 22322), sorted(set(frames) - planned))
        self.assertRaisesRegex(ValueError, 'holds 14399 frames', media.frame_selection, SOURCE, plan, 14399)

    def test_keepalive_frames_print_progress_and_are_never_measured(self) -> None:
        """Every decoded frame advances progress; only sampled frames reach the detector and the record."""
        plan = {**_plan((1.0, 1.5)), 'clock': {'frameCount': 120}}
        detected, totals = [], []

        def detect(image: np.ndarray) -> list[dict]:
            """Stub detector: one face inside the 64x36 frame."""
            detected.append(image.shape)
            return [{'x': 10.0, 'y': 5.0, 'w': 12.0, 'h': 14.0, 'score': 0.9}]

        def reader(_path: Path, selection: object, compare: object, _root: Path) -> tuple[list, dict]:
            """Stands in for the shared reader: hands every selected frame to the pass, in order."""
            totals.append(selection.total_frames)
            return [compare(frame, np.zeros((36, 64, 3), np.uint8)) for frame in selection.frames], {'frames': 0}

        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        request = {'model': {'path': '/model.onnx'}, 'scoreThreshold': 0.7}
        with patch.object(faces, 'face_detector', return_value=detect), \
                patch.object(faces, 'compare_selected_frames', side_effect=reader), \
                contextlib.redirect_stdout(io.StringIO()) as printed:
            rows, sheets, decode = faces.measure_frames(request, SOURCE, plan, root)
        planned = [row['frame'] for row in plan['frames']]
        self.assertEqual([row['frame'] for row in rows], planned)
        self.assertEqual((len(detected), totals), (len(planned), [120]))
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
        for edge in ({'x': 64.0, 'y': 5.0}, {'x': 5.0, 'y': 36.0}, {'x': -10.0, 'y': 5.0}, {'x': 5.0, 'y': -10.0}):
            box = {'frame': 7, 't': 0.2, 'faces': [{**edge, 'w': 10.0, 'h': 10.0, 'score': 0.9}]}
            self.assertRaisesRegex(ValueError, 'lies outside', faces.face_tiles, frame, box)
        partly = {'frame': 7, 't': 0.2, 'faces': [{'x': -5.0, 'y': 5.0, 'w': 10.0, 'h': 10.0, 'score': 0.9}]}
        self.assertEqual(len(faces.face_tiles(frame, partly)), 1)
        frame_pass = faces.FramePass({7: {'frame': 7, 't': 0.2, 'dense': True}},
                                     lambda _image: outside['faces'], {})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertRaisesRegex(ValueError, 'lies outside', frame_pass, 7, frame)


class PacketClockTests(unittest.TestCase):
    """Frame times are the video packets' own timestamps (X78 DM1): exact, no threshold."""

    def test_img_5954_like_clock_is_accepted_and_exact(self) -> None:
        """Two dropped frames: 22320 packets, 29.997 fps average, 30/1 nominal. Accepted, mapped by timestamp."""
        clock, info = media.stream_clock(_probe([n for n in range(22322) if n not in (5000, 15000)]), Fraction(30))
        self.assertEqual((info['frameCount'], info['indexDriftFrames']), (22320, -2.0))
        self.assertAlmostEqual((info['frameCount'] - 1) / info['lastFrameSeconds'], 29.997, places=3)
        plan = _plan((740.2, 744.068), clock=clock)
        self.assertEqual((plan['ranges'][0]['firstFrame'], plan['ranges'][0]['endFrame']), (22204, 22320))
        self.assertEqual(plan['frames'][0]['t'], 740.2)
        self.assertEqual(_plan((740.2, 741.2), clock=clock)['ranges'][0]['endFrame'], 22234)  # H02: an end on a frame start
        limits = sampling.clipped_limits(plan, clock)
        self.assertEqual(len(limits), 1)
        self.assertIn('clip A words 0-0 (740.200-744.068 s)', limits[0])
        for inside in ((700.0, 710.0), (740.2, 744.06)):
            self.assertEqual(sampling.clipped_limits(_plan(inside, clock=clock), clock), [], inside)

    def test_container_alignment_discard_and_decode_order(self) -> None:
        """The first decoded audio frame aligns the clocks; discard packets drop; decode order is sorted."""
        order = [0, 3, 1, 2] + list(range(4, 240))
        probe = _probe(order, audio={**AUDIO, 'start_time': '-0.021333'}, first='-1024')
        probe['packets'] = [('-40', 'KD_'), ('-20', '_D_')] + probe['packets']
        clock, info = media.stream_clock(probe, Fraction(60))
        self.assertEqual((info['frameCount'], info['discardedPackets']), (240, 2))
        lead = Fraction(1024, 48000)
        self.assertEqual(clock.times[:3], (lead, Fraction(1, 30) + lead, Fraction(2, 30) + lead))
        early = _plan((0.0, 0.5), clock=clock)
        self.assertEqual((early['ranges'][0]['firstFrame'], len(early['clipped'])), (0, 1))  # H03 clamp, H11 limit
        dropped, info = media.stream_clock(_probe(order, audio={**AUDIO, 'start_time': '-0.021333'}), Fraction(60))
        self.assertEqual((dropped.times[0], info['audioStartSeconds'], info['audioStreamStartSeconds']), (0, 0.0, -0.021333))
        mkv = {'codec_type': 'video', 'start_time': '0.000000', 'time_base': '1/1000'}
        packets = [(str(round(n * 1000 / 30)), '___') for n in range(90)]
        mkv_probe = {'streams': [mkv, AUDIO], 'packets': packets, 'audioFirstPts': '0'}
        self.assertEqual(media.stream_clock(mkv_probe, Fraction(30))[1]['frameCount'], 90)

    def test_only_unreadable_timestamps_refuse(self) -> None:
        """An unreadable timestamp, start_time or time_base, a missing stream, or no presentable packet."""
        good = _probe(list(range(10)))
        cases = (({**good, 'packets': [('N/A', '___')] + good['packets']}, 'no readable presentation timestamp'),
                 ({**good, 'audioFirstPts': ''}, 'first decoded audio frame has no readable presentation timestamp'),
                 (_probe(list(range(10)), audio={'codec_type': 'audio', 'start_time': '0'}), 'no readable time_base'),
                 (_probe(list(range(10)), audio={**AUDIO, 'start_time': 'N/A'}), 'no readable start_time'),
                 (_probe(list(range(10)), video={**VIDEO, 'start_time': 'N/A'}), 'no readable start_time'),
                 (_probe(list(range(10)), video={'codec_type': 'video', 'start_time': '0'}), 'no readable time_base'),
                 ({'streams': [VIDEO], 'packets': good['packets']}, 'no audio stream'),
                 ({**good, 'packets': [('0', 'KD_')]}, 'no presentable packets'))
        for probe, message in cases:
            self.assertRaisesRegex(ValueError, message, media.stream_clock, probe, Fraction(30))

    def test_probe_commands_read_headers_then_packet_timestamps(self) -> None:
        """Headers as JSON, v:0 packet pts and flags as CSV, then the first decoded a:0 frame's pts (X87 F-m1)."""
        replies = [subprocess.CompletedProcess([], 0, json.dumps({'streams': [VIDEO, AUDIO]}).encode(), b''),
                   subprocess.CompletedProcess([], 0, b'0,K__\n20,___\n', b''),
                   subprocess.CompletedProcess([], 0, b'1024\n2048\n', b'')]
        with patch.object(media, 'run_bounded', side_effect=replies) as run:
            probe = media.probe_streams('/synthetic.media', '/pinned/ffprobe')
        header, packets, audio = (call.args[0] for call in run.call_args_list)
        self.assertEqual(audio[audio.index('-select_streams') + 1:audio.index('-select_streams') + 6],
                         ['a:0', '-read_intervals', '%+#8', '-show_entries', 'frame=pts'])
        self.assertEqual(probe['audioFirstPts'], '1024')
        self.assertEqual((header[0], header[header.index('-show_entries') + 1]), ('/pinned/ffprobe', media.HEADER_ENTRIES))
        self.assertEqual(packets[packets.index('-select_streams') + 1:packets.index('-select_streams') + 4],
                         ['v:0', '-show_entries', 'packet=pts,flags'])
        self.assertEqual(probe['packets'], [('0', 'K__'), ('20', '___')])


if __name__ == '__main__':
    unittest.main()
