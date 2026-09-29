"""Current-pixel gate, sealed evidence and exact-resume bounds; no render qualification."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

import test_native_long_section_compatibility as compatibility_fixture
from cut_preview_io import bound_json
from studio.native_runtime import digest
from studio.native_segments import owners
from studio.native_segments.probe import dependency_frames, require_dependency_probe
from studio.native_segments.verify import verify_long_segment_probes
from studio.native_segments.manifest import FINAL_COLOR


class DependencyProofTests(unittest.TestCase):
    """Use original registered StageEvidence plus explicitly synthetic media boundaries."""

    def setUp(self) -> None:
        """Complete an actual repair/copy/seal chain with the existing fake-decoder fixture."""
        self.fixture = compatibility_fixture.LongSectionCompatibilityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.request = self.fixture.admit(self.fixture.child())
        self.fixture.complete(self.request)
        self.phase = 'segment-picture-0'
        self.value = owners.current_window(self.request, self.phase)
        self.record = bound_json(Path(self.request['output']) / f'{self.phase}-stage.json')

    def test_receipt_references_and_every_native_capture_are_sealed(self) -> None:
        """A nested JSON hash alone cannot substitute for the original owned artifact closure."""
        for name in ('dependencyProof', 'dependencyCapture', 'dependencyComparison', 'probe0'):
            record = copy.deepcopy(self.record)
            record['artifacts'].pop(name)
            with self.subTest(artifact=name), self.assertRaises(ValueError):
                require_dependency_probe(self.request, self.phase, self.value, record)

    def test_missing_current_comparison_or_changed_reference_is_rejected(self) -> None:
        """A technical donor seal does not authorize reuse without current native comparison."""
        value = {**self.value}
        value.pop('dependencyProbe')
        with self.assertRaisesRegex(ValueError, 'lacks sealed current-project'):
            require_dependency_probe(self.request, self.phase, value, self.record)
        value = copy.deepcopy(self.value)
        value['probes'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'reference inventory changed'):
            require_dependency_probe(self.request, self.phase, value, self.record)

    def test_original_comparison_corruption_fails_real_stage_reader(self) -> None:
        """Changing the comparison file after owner completion invalidates the retained stage."""
        file = Path(self.record['artifacts']['dependencyComparison']['path'])
        file.write_bytes(file.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'changed|differs'):
            owners.current_window(self.request, self.phase)


class SegmentPixelComparisonTests(unittest.TestCase):
    """Run the actual pixel comparator using controlled decoded RGB, without media subprocesses."""

    def test_absolute_frames_map_to_local_frames_with_final_color_interpretation(self) -> None:
        """A C donor uses local 0..N frame indices and the exact final sRGB metadata interpretation."""
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        file = root / 'probe.jpg'
        Image.new('RGB', (320, 180), (0, 0, 0)).save(file)
        probes = [{'frame': frame, 'path': str(file), 'sha256': digest(file)} for frame in (500, 512, 524)]
        piece = {'path': str(root / 'TEST.mp4'), 'startFrame': 500, 'endFrameExclusive': 525,
                 'stream': dict(FINAL_COLOR)}
        canvas = {'width': 320, 'height': 180, 'totalFrames': 1000, 'frameRate': '25/1'}

        def decoded(_path: Path, selection: object, callback: object, _directory: Path) -> tuple:
            """The synthetic decoder sees exactly the donor's local schedule and input tags."""
            self.assertEqual(selection.frames, (0, 12, 24))
            self.assertEqual(selection.total_frames, 25)
            self.assertTrue(selection.filter_bytes.startswith(b'setparams=range=limited:'))
            return [callback(frame, np.zeros(selection.shape, dtype=np.uint8)) for frame in selection.frames], {}

        with patch('studio.native_segments.verify.compare_selected_frames', side_effect=decoded):
            result = verify_long_segment_probes(probes, piece, canvas, root / 'comparison')
            self.assertTrue(result['passed'])
            self.assertEqual(result['absoluteFrames'], [500, 512, 524])
            self.assertEqual(result['runtimeQualification'], 'not-established')
            Image.new('RGB', (320, 180), (255, 255, 255)).save(file)
            changed = [{**row, 'sha256': digest(file)} for row in probes]
            with self.assertRaisesRegex(ValueError, 'changed frame outside'):
                verify_long_segment_probes(changed, piece, canvas, root / 'mismatch')

    def test_all_bounded_windows_keep_endpoints_and_midpoint(self) -> None:
        """Small nondivisible window lengths cannot exceed the native sample inventory bound."""
        for length in range(1, 601):
            points = dependency_frames({'startFrame': 900, 'endFrame': 900 + length})
            self.assertLessEqual(len(points), 12)
            self.assertEqual((points[0], points[-1]), (900, 899 + length))
            self.assertIn((1800 + length - 1) // 2, points)

    def test_unknown_color_and_outside_donor_indices_refuse_before_decoder(self) -> None:
        """No guessed color transform or clamped source frame can turn into a passing sample."""
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        canvas = {'width': 320, 'height': 180, 'totalFrames': 1000, 'frameRate': '25/1'}
        piece = {'path': str(root / 'TEST.mp4'), 'startFrame': 500, 'endFrameExclusive': 525,
                 'stream': dict(FINAL_COLOR)}
        with patch('studio.native_segments.verify.compare_selected_frames') as decoder:
            for field in FINAL_COLOR:
                changed = {**piece, 'stream': {**piece['stream'], field: 'unknown'}}
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'color route'):
                    verify_long_segment_probes([{'frame': 500}], changed, canvas, root / 'unused')
            for frame in (499, 525):
                with self.assertRaisesRegex(ValueError, 'outside'):
                    verify_long_segment_probes([{'frame': frame}], piece, canvas, root / 'unused')
            decoder.assert_not_called()


if __name__ == '__main__':
    unittest.main()
