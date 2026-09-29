"""Captured-reference reverse-seek/phone-text diagnostics and audio failure naming."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _native_audio_stage_fixture import AudioProjectFixture, fake_prepare_dialogue, owner_factory, write_json
from studio import native_audio_stage as stage
from studio.native_capture_diagnostics import capture_diagnostics, font_px, small_text_report
from studio.native_font_readiness import declared_text_sizes
from studio.native_picture_references import qualify_reverse_frames
from studio.native_runtime import digest

SHAPE = (1920, 1080, 3)


def frame_image(path: Path, value: int, speck: bool = False) -> dict:
    """Write one TEST JPEG; an optional bright block models a future connector speck."""
    pixels = np.full(SHAPE, value, dtype=np.uint8)
    if speck:
        pixels[900:1000, 400:700] = 255
    Image.fromarray(pixels).save(path, quality=95)
    return {'path': str(path), 'sha256': digest(path)}


class CaptureDiagnosticsTests(unittest.TestCase):
    """The early diagnostic uses exactly the final reverse-seek gate's measurements."""

    def setUp(self) -> None:
        """A TEST project canvas and a three-row forward/reverse capture receipt."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        write_json(self.project / 'SHORT-PROJECT.json', {'canvas': {'frameRate': '30/1', 'totalFrames': 30}})
        self.state = [{'id': 'native-title-line-0', 'text': 'TEST title', 'font': '700 72px / 80px Inter'},
                      {'id': 'label-a', 'text': 'TEST tiny label', 'font': '700 27px / 31.05px Inter'}]

    def receipt(self, speck: bool) -> Path:
        """Forward frames 0 and 24, then a reverse seek of 24 (optionally with a speck)."""
        rows = []
        for index, (frame, repeat) in enumerate(((0, False), (24, False), (24, True))):
            image = frame_image(self.root / f'pose-{index}.jpg', 40, speck and repeat)
            rows.append({'frame': frame, 'repeat': repeat, 'visualState': self.state, 'payload': [], **image})
        file = self.root / 'native-frames.json'
        write_json(file, {'status': 'native-references-and-seek-states-pass', 'frames': rows})
        return file

    def test_stable_reverse_seek_is_clean_and_matches_the_final_gate(self) -> None:
        """A byte-identical reverse seek passes both the diagnostic and the unchanged final gate."""
        report = capture_diagnostics(self.receipt(False), self.project)
        self.assertEqual(report['reverseSeek']['status'], 'reverse-seek-stable')
        self.assertEqual(len(qualify_reverse_frames(json.loads((self.root / 'native-frames.json').read_text()),
                                                    SHAPE)), 1)

    def test_reverse_speck_is_reported_exactly_where_the_final_gate_would_fail(self) -> None:
        """Future-connector pixels on a reverse seek become an early drift finding."""
        report = capture_diagnostics(self.receipt(True), self.project)
        self.assertEqual(report['status'], 'defects')
        self.assertEqual((report['reverseSeek']['status'], report['reverseSeek']['failed'][0]['frame']),
                         ('reverse-seek-drift', 24))
        with self.assertRaisesRegex(RuntimeError, 'Reverse-seek pixel stability failed'):
            qualify_reverse_frames(json.loads((self.root / 'native-frames.json').read_text()), SHAPE)

    def test_phone_text_reads_rendered_and_declared_sizes(self) -> None:
        """27 px captured text and declared 30 px CSS are review findings; 72 px is not."""
        report = small_text_report({'frames': [{'frame': 3, 'repeat': False, 'visualState': self.state}]})
        self.assertEqual([(row['id'], row['fontPx']) for row in report['elements']], [('label-a', 27.0)])
        self.assertIsNone(font_px('normal'))
        (self.project / 'index.html').write_text('<style>.a{font-size: 30px}.b{font-size:72px}</style>')
        (self.project / 'compositions').mkdir()
        (self.project / 'compositions/flow.html').write_text('<template><p style="font-size:27px">x</p></template>')
        rows = declared_text_sizes(self.project)['declarations']
        self.assertEqual([(row['file'], row['fontPx']) for row in rows],
                         [('compositions/flow.html', 27.0), ('index.html', 30.0)])


class AudioFailureNamingTests(unittest.TestCase):
    """A failed audio stage names the exact shared check that failed."""

    def setUp(self) -> None:
        """Real stage parent/worker code with only DSP and supervision faked."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.f = AudioProjectFixture(self.base)
        runtime = self.base / 'runtime'
        (runtime / 'dist').mkdir(parents=True)
        (runtime / 'dist/cli.js').write_text('TEST CLI, never executed')
        self.plan = stage.AudioStagePlan(self.f.project, self.base / 'audio-v1', runtime=runtime)
        self.enterContext(mock.patch('studio.native_run.NativeRun', side_effect=owner_factory(stage.worker)))
        self.enterContext(mock.patch('studio.native_run_config.local_environment', return_value=(self.f.tools, {})))
        self.enterContext(mock.patch.object(stage, 'require_tool_resolution'))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_hum_failure_names_the_check_and_measurement(self) -> None:
        """The failure record carries audio_tonal_hum and its measured line, as the audit needed."""
        def hum(request: dict, value: dict, finishing: object) -> dict:
            """Write a real-format failed receipt, then fail like prepare_native_master."""
            fake_prepare_dialogue(request, value, finishing)
            receipt = Path(request['output']) / 'audio-preparation/receipt.json'
            record = json.loads(receipt.read_text())
            record.update(status='failed', audioQuality=[{'name': 'audio_tonal_hum', 'status': 'fail',
                          'measured': '53.0 Hz; prominence 21.8 dB', 'detail': 'stable narrow tone'}])
            receipt.write_text(json.dumps(record))
            raise RuntimeError('Early native float master failed shared audio quality checks')
        with mock.patch('studio.native_short_delivery.prepare_dialogue', side_effect=hum), \
                self.assertRaises(stage.AudioStageFailure) as caught:
            stage.prepare_stage(self.plan)
        record = caught.exception.record
        self.assertIn('audio_tonal_hum: 53.0 Hz', record['error'])
        self.assertEqual(record['diagnostics']['failedChecks'][0]['name'], 'audio_tonal_hum')
        self.assertFalse((self.plan.root / 'audio-stage.json').exists())


if __name__ == '__main__':
    unittest.main()
