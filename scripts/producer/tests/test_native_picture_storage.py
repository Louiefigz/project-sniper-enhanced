"""Reserve admission and exact picture-QC orchestration with inert media fixtures."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from cut_preview_io import MAX_JSON, file_hash, file_identity
from native_render_resources import GIB, ResourcePolicy
from native_render_storage import allocation_requirement, check_allocation, require_disk_allocation
from studio import native_picture_references as references
from studio import native_short_delivery as delivery
from studio.native_selected_frames import FrameConsumer

FULL_DECODE = delivery.full_decode


class DiskAllocationTests(unittest.TestCase):
    """The existing resource reserve must remain after all predictable allocations."""

    def test_exact_allocation_plus_reserve_boundary(self) -> None:
        """Exactly enough is accepted; one fewer byte fails before file creation."""
        policy = ResourcePolicy(minimum_disk_free_gib=1.5)
        requirement = allocation_requirement(137, policy)
        threshold = int(1.5 * GIB) + 137
        self.assertEqual(requirement['requiredFreeBytes'], threshold)
        self.assertEqual(check_allocation(threshold, requirement)['observedFreeBytes'], threshold)
        self.assertEqual(check_allocation(threshold + 1, requirement)['observedFreeBytes'], threshold + 1)
        with self.assertRaisesRegex(RuntimeError, 'allocation refused'):
            check_allocation(threshold - 1, requirement)

    def test_invalid_byte_counts_never_become_capacity(self) -> None:
        """NaN, floats, booleans, strings and negative allocations cannot weaken policy."""
        for value in [-1, True, 1.1, '4', float('nan'), float('inf')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                allocation_requirement(value, ResourcePolicy())
            with self.subTest(value=value), self.assertRaises(ValueError):
                check_allocation(value, allocation_requirement(0, ResourcePolicy()))

    def test_live_free_capacity_is_measured_on_canonical_output_filesystem(self) -> None:
        """Existing files affect measured free capacity; no cache eviction occurs."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            prior = root / 'preserve.txt'
            prior.write_text('old output')
            with patch('native_render_storage.shutil.disk_usage', return_value=SimpleNamespace(free=11 * GIB)) as usage:
                receipt = require_disk_allocation(root, GIB)
            usage.assert_called_once_with(root)
            self.assertEqual(receipt['reservedBytes'], 10 * GIB)
            self.assertEqual(prior.read_text(), 'old output')

    def test_access_time_is_not_part_of_content_identity(self) -> None:
        """Ordinary filesystem reads must not look like replacement or content mutation."""
        fields = dict(st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4, st_ctime_ns=5, st_nlink=1)
        self.assertEqual(file_identity(SimpleNamespace(**fields, st_atime_ns=6)),
                         file_identity(SimpleNamespace(**fields, st_atime_ns=7)))


class PictureQualificationTests(unittest.TestCase):
    """Use real small PNG evidence and mocked codecs, retaining every gate and metric."""

    def setUp(self) -> None:
        """Three unique forward references plus one repeated frame keep reverse coverage."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.canvas = {'frameRate': '30000/1001', 'width': 4, 'height': 2, 'totalFrames': 5}
        self.pixels, rows = {}, []
        for index, frame in enumerate([0, 2, 4, 2]):
            pixels = np.full((2, 4, 3), frame * 20, dtype=np.uint8)
            path = self.root / f'frame-{index}.png'
            Image.fromarray(pixels).save(path)
            self.pixels[frame] = pixels
            rows.append({'frame': frame, 'path': str(path), 'sha256': file_hash(path),
                         'repeat': index == 3, 'visualState': {'frame': frame}, 'payload': []})
        self.native = {'status': 'native-references-and-seek-states-pass', 'frames': rows,
                       'expectedCapturePoints': [0, 2, 4, 2]}
        self.receipt = self.root / 'native-frames.json'
        self.write_receipt()
        self.candidate = self.root / 'review.mp4'
        self.candidate.write_bytes(b'inert mp4 fixture - no codecs')
        self.enterContext(patch.object(delivery, 'observe_picture_source', return_value=SimpleNamespace(packets=[()] * 5)))
        self.enterContext(patch('native_render_storage.shutil.disk_usage', return_value=SimpleNamespace(free=20 * GIB)))
        self.decode = self.enterContext(patch.object(delivery, 'compare_selected_frames', side_effect=self.stream_fixture))
        self.full = self.enterContext(patch.object(delivery, 'full_decode'))

    def write_receipt(self) -> None:
        """Write a changed fixture only when testing an explicit rejection."""
        self.receipt.write_text(json.dumps(self.native))

    def stream_fixture(self, candidate: Path, selection: object, compare: object,
                       directory: Path) -> tuple[list[dict], dict]:
        """Feed every selected byte through the actual streaming comparison adapter."""
        consumer = FrameConsumer(selection, compare)
        for frame in selection.frames:
            consumer.consume(self.pixels[frame].tobytes())
        return consumer.comparisons, consumer.finish()

    def test_every_comparison_reverse_check_and_full_decode_survive(self) -> None:
        """Exact metrics, final frame and repeated frame remain in the result receipt."""
        result = delivery.qualify_picture(self.root, self.canvas)
        self.assertEqual([row['frame'] for row in result['comparisons']], [0, 2, 4])
        self.assertEqual([row['frame'] for row in result['reverseSeekComparisons']], [2])
        self.assertTrue(all(row['mae'] == 0 and row['psnrDb'] == 100 for row in result['comparisons']))
        self.assertEqual(result['candidateSha256'], file_hash(self.candidate))
        self.assertEqual(result['storageAdmission']['reservedBytes'], 10 * GIB)
        self.assertGreater(result['storageAdmission']['plannedAllocationBytes'], MAX_JSON)
        self.assertTrue(result['fullAudioVideoDecodePassed'])
        self.assertFalse(result['humanListeningApproved'])
        self.full.assert_called_once_with(self.candidate, timeout=180)
        self.assertEqual(list((self.root / 'picture-qc').iterdir()), [self.root / 'picture-qc/result.json'])

    def test_missing_comparison_or_reordered_inventory_fails_before_decode(self) -> None:
        """The original capture inventory cannot silently shrink or change order."""
        self.native['frames'].pop(1)
        self.write_receipt()
        with self.assertRaisesRegex(RuntimeError, 'schedule'):
            delivery.qualify_picture(self.root, self.canvas)
        self.decode.assert_not_called()

    def test_changed_source_reference_candidate_or_receipt_never_passes(self) -> None:
        """Mutation after comparisons invalidates the verdict and prevents a pass receipt."""
        for target in [self.candidate, self.receipt, Path(self.native['frames'][0]['path'])]:
            with self.subTest(target=target):
                before = target.read_bytes()
                self.full.side_effect = lambda candidate, timeout: target.write_bytes(before + b'changed')
                with self.assertRaisesRegex(RuntimeError, 'changed'):
                    delivery.qualify_picture(self.root, self.canvas)
                self.assertFalse((self.root / 'picture-qc/result.json').exists())
                target.write_bytes(before)
                (self.root / 'picture-qc').rmdir()

    def test_reference_mismatch_and_scene_drift_cannot_relax_thresholds(self) -> None:
        """A mismatched source binding or reverse state fails before encoding checks."""
        self.native['frames'][0]['sha256'] = '0' * 64
        self.write_receipt()
        with self.assertRaisesRegex(RuntimeError, 'reference changed'):
            delivery.qualify_picture(self.root, self.canvas)
        self.full.assert_not_called()

    def test_reserve_failure_occurs_before_decoder_or_scratch_directory(self) -> None:
        """One-byte inadequate projected capacity rejects before any allocation."""
        with patch('native_render_storage.shutil.disk_usage', return_value=SimpleNamespace(free=10 * GIB)):
            with self.assertRaisesRegex(RuntimeError, 'allocation refused'):
                delivery.qualify_picture(self.root, self.canvas)
        self.decode.assert_not_called()
        self.assertFalse((self.root / 'picture-qc').exists())

    def test_incomplete_decode_never_reaches_full_decode_or_pass_receipt(self) -> None:
        """Failed selected-frame inventory preserves prior files and leaves no RGB."""
        self.decode.side_effect = RuntimeError('incomplete frame inventory')
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            delivery.qualify_picture(self.root, self.canvas)
        self.full.assert_not_called()
        self.assertEqual(list((self.root / 'picture-qc').iterdir()), [])

    def test_picture_tolerance_is_unchanged_and_shape_is_declared(self) -> None:
        """MAE 2 is accepted only with PSNR at least 40; changed geometry always fails."""
        path = Path(self.native['frames'][0]['path'])
        self.assertTrue(references.picture_metrics(path, self.pixels[0] + 2, (2, 4, 3))['passed'])
        self.assertFalse(references.picture_metrics(path, self.pixels[0] + 3, (2, 4, 3))['passed'])
        with self.assertRaisesRegex(RuntimeError, 'dimensions'):
            references.picture_metrics(path, self.pixels[0].reshape(4, 2, 3), (4, 2, 3))

    def test_independent_full_decode_maps_both_complete_streams(self) -> None:
        """Selected-frame streaming never replaces complete audio/video error detection."""
        with patch.object(delivery, 'run') as run:
            FULL_DECODE(self.candidate)
        command = run.call_args.args[0]
        self.assertEqual(command[-7:], ['-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'])
        self.assertIn('-xerror', command)
        self.assertNotIn('-frames:v', command)

    def test_long_full_decode_honors_explicit_budget(self) -> None:
        """Fifteen-minute verification keeps the full decode with its larger bound."""
        with patch.object(delivery, 'run') as run:
            FULL_DECODE(self.candidate, timeout=1800)
        self.assertEqual(run.call_args.kwargs['timeout'], 1800)
        self.assertNotIn('-frames:v', run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
