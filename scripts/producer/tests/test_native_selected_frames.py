"""Exact streamed RGB inventory and cleanup tests without launching media tools."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import cut_preview_io as bounded
from studio import native_selected_frames as selected


class SelectedFrameTests(unittest.TestCase):
    """Every integer-index comparison survives pipe chunking and large schedules."""

    def setUp(self) -> None:
        """Use tiny inert pixels and exclusively owned temporary files."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.selection = selected.SelectedFrames((0, 2, 4), 4, 2, 5)
        self.raw = bytes(range(self.selection.frame_bytes * 3))

    def compare(self, frame: int, pixels: np.ndarray) -> dict:
        """Check exact pixel order, including bytes straddling pipe reads."""
        index = self.selection.frames.index(frame)
        start = index * self.selection.frame_bytes
        self.assertEqual(pixels.shape, self.selection.shape)
        self.assertEqual(pixels.tobytes(), self.raw[start:start + self.selection.frame_bytes])
        return {'frame': frame, 'passed': True}

    def test_irregular_chunks_equal_original_concatenated_file_hash(self) -> None:
        """Splitting inside rows and frames cannot change any comparison or byte."""
        consumer = selected.FrameConsumer(self.selection, self.compare)
        offsets = [0, 1, 23, 24, 49, len(self.raw)]
        for start, end in zip(offsets, offsets[1:]):
            consumer.consume(self.raw[start:end])
        result = consumer.finish()
        self.assertEqual([r['frame'] for r in consumer.comparisons], [0, 2, 4])
        self.assertEqual(result['sha256'], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(result['decodedBytes'], len(self.raw))
        self.assertEqual(result['scratchBytes'], 0)

    def test_full_180_second_60fps_schedule_retains_all_10800_comparisons(self) -> None:
        """Long schedules use bounded RGB memory, not fewer validation frames."""
        count = 180 * 60
        selection = selected.SelectedFrames(tuple(range(count)), 2, 2, count)
        raw = bytes(range(12)) * count
        consumer = selected.FrameConsumer(selection, lambda frame, pixels: {'frame': frame})
        consumer.consume(raw)
        result = consumer.finish()
        self.assertEqual([r['frame'] for r in consumer.comparisons], list(range(count)))
        self.assertEqual(result['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertLessEqual(result['peakRgbBufferBytes'], selection.frame_bytes + 65536)
        self.assertEqual(selected.MAX_SELECTED_FRAMES, 100000)

    def test_rational_clock_and_canvas_shapes_keep_exact_indexes(self) -> None:
        """Neither NTSC fractions nor landscape geometry alter frame selection."""
        for width, height in [(4, 2), (2, 4)]:
            canvas = {'frameRate': '30000/1001', 'width': width, 'height': height, 'totalFrames': 5}
            value = selected.selected_frames(canvas, [{'frame': 0}, {'frame': 4}])
            self.assertEqual(value.frames, (0, 4))
            self.assertEqual(value.shape, (height, width, 3))
        with self.assertRaises(ValueError):
            selected.selected_frames({**canvas, 'frameRate': '30000/0'}, [{'frame': 0}])
        del canvas['height']
        with self.assertRaisesRegex(ValueError, 'both explicit'):
            selected.selected_frames(canvas, [{'frame': 0}])

    def test_invalid_schedules_fail_without_launch(self) -> None:
        """Missing, repeated, reordered, boolean and out-of-range indexes cannot pass."""
        for frames in [(), (0, 0), (2, 0), (-1,), (5,), (True,)]:
            with self.subTest(frames=frames), self.assertRaises(ValueError):
                selected.SelectedFrames(frames, 4, 2, 5)
        with self.assertRaisesRegex(ValueError, 'geometry'):
            selected.SelectedFrames((0,), 100000, 100000, 1)

    def test_partial_and_extra_frames_never_qualify(self) -> None:
        """An EOF inside the last frame and one extra byte are explicit failures."""
        for count in [0, 24, len(self.raw) - 1]:
            consumer = selected.FrameConsumer(self.selection, self.compare)
            consumer.consume(self.raw[:count])
            with self.assertRaisesRegex(RuntimeError, 'incomplete'):
                consumer.finish()
        consumer = selected.FrameConsumer(self.selection, self.compare)
        with self.assertRaisesRegex(RuntimeError, 'excess'):
            consumer.consume(self.raw + b'x')

    def decode_stub(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        """Inspect the exact native conversion and then supply known RGB bytes."""
        self.assertNotIn('-vf', command)
        script = Path(command[command.index('-filter_script:v') + 1])
        self.assertEqual(script.read_bytes(), self.selection.filter_bytes)
        self.assertIn(selected.COLOR_FILTER.encode(), script.read_bytes())
        self.assertEqual(command[-9:], ['-fps_mode', 'passthrough', '-threads', '1',
                                       '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'])
        kwargs['consume_stdout'](self.raw)
        return subprocess.CompletedProcess(command, 0, b'', b'')

    def test_decode_preserves_filter_settings_and_cleans_owned_script(self) -> None:
        """The only temporary file is the unchanged filter expression, never RGB."""
        with patch.object(selected, 'require_encoded_geometry'), \
                patch.object(selected, 'run_bounded', side_effect=self.decode_stub):
            comparisons, result = selected.compare_selected_frames(
                self.root / 'inert.mp4', self.selection, self.compare, self.root)
        self.assertEqual(len(comparisons), 3)
        self.assertEqual(result['rgbScratchBytes'], 0)
        self.assertEqual(result['scratchBytes'], len(self.selection.filter_bytes))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_decode_failure_and_cancellation_remove_only_owned_script(self) -> None:
        """Callback failure or cancellation leaves prior output untouched and no scratch."""
        prior = self.root / 'prior.rgb'
        prior.write_bytes(b'preserve')
        for failure in [RuntimeError('decode failed'), KeyboardInterrupt()]:
            with patch.object(selected, 'require_encoded_geometry'), \
                    patch.object(selected, 'run_bounded', side_effect=failure):
                with self.assertRaises(type(failure)):
                    selected.compare_selected_frames(self.root / 'inert.mp4', self.selection,
                                                     self.compare, self.root)
            self.assertEqual(list(self.root.iterdir()), [prior])
            self.assertEqual(prior.read_bytes(), b'preserve')

    def test_existing_or_replaced_filter_is_never_deleted(self) -> None:
        """Exclusive creation and inode ownership forbid cleanup of unrelated files."""
        script = self.root / 'selected-filter.txt'
        script.write_bytes(b'old')
        with self.assertRaises(FileExistsError), selected.owned_filter(self.root, b'new'):
            self.fail('must not enter')
        self.assertEqual(script.read_bytes(), b'old')
        script.unlink()
        with self.assertRaisesRegex(RuntimeError, 'filter changed'):
            with selected.owned_filter(self.root, b'new'):
                alternate = self.root / 'alternate.txt'
                alternate.write_bytes(b'other inode')
                alternate.replace(script)
        self.assertEqual(script.read_bytes(), b'other inode')

    def test_equal_area_wrong_geometry_and_decoder_diagnostics_fail(self) -> None:
        """A transposed canvas is not accepted merely because raw byte counts agree."""
        probe = subprocess.CompletedProcess([], 0, json.dumps({'streams': [{'width': 2, 'height': 4}]}).encode(), b'')
        with patch.object(selected, 'run_bounded', return_value=probe):
            with self.assertRaisesRegex(RuntimeError, 'dimensions'):
                selected.require_encoded_geometry(self.root / 'inert.mp4', self.selection)
        for code, stderr in [(1, b''), (0, b'error')]:
            bad = subprocess.CompletedProcess([], code, b'', stderr)
            with patch.object(selected, 'require_encoded_geometry'), \
                    patch.object(selected, 'run_bounded', return_value=bad):
                with self.assertRaisesRegex(RuntimeError, 'decode failed'):
                    selected.compare_selected_frames(self.root / 'inert.mp4', self.selection,
                                                     self.compare, self.root)

    def test_unrelated_bitstream_side_data_does_not_change_geometry(self) -> None:
        """FFprobe may emit empty side-data objects with exact requested dimensions."""
        stream = {'width': self.selection.width, 'height': self.selection.height, 'side_data_list': [{}]}
        probe = subprocess.CompletedProcess([], 0, json.dumps({'streams': [stream]}).encode(), b'')
        with patch.object(selected, 'run_bounded', return_value=probe):
            selected.require_encoded_geometry(self.root / 'inert.mp4', self.selection)


class StreamingProcessTests(unittest.TestCase):
    """The shared subprocess reader cleans its child even when a consumer aborts."""

    def test_consumed_output_is_not_retained_in_completed_process(self) -> None:
        """A real tiny Python pipe exercises both independent stdout and stderr reads."""
        received = bytearray()
        command = [sys.executable, '-c', 'import sys;sys.stdout.buffer.write(b"x"*131073);sys.stderr.write("ok")']
        result = bounded.run_bounded(command, maximum=140000, consume_stdout=received.extend)
        self.assertEqual(len(received), 131073)
        self.assertEqual((result.stdout, result.stderr), (b'', b'ok'))

    def test_consumer_abort_kills_and_reaps_owned_child(self) -> None:
        """Ordinary exceptions and user cancellation have the same cleanup boundary."""
        real_popen, children = subprocess.Popen, []

        def launch(*args: object, **kwargs: object) -> subprocess.Popen:
            """Record the actual test-only child for cleanup assertions."""
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        command = [sys.executable, '-c', 'import sys,time;sys.stdout.write("x");sys.stdout.flush();time.sleep(30)']
        for failure in [RuntimeError('consumer failed'), KeyboardInterrupt()]:
            with patch.object(bounded.subprocess, 'Popen', side_effect=launch):
                with self.assertRaises(type(failure)):
                    bounded.run_bounded(command, consume_stdout=lambda data: (_ for _ in ()).throw(failure))
            self.assertIsNotNone(children[-1].poll())
            self.assertTrue(children[-1].stdout.closed and children[-1].stderr.closed)

    def test_streaming_stderr_has_its_own_bound(self) -> None:
        """A large allowed RGB stream does not authorize equally large diagnostics."""
        with patch.object(bounded, 'MAX_JSON', 16):
            with self.assertRaisesRegex(RuntimeError, 'diagnostics'):
                bounded.run_bounded([sys.executable, '-c', 'import sys;sys.stderr.write("x"*17)'],
                                    maximum=1000, consume_stdout=lambda data: None)


if __name__ == '__main__':
    unittest.main()
