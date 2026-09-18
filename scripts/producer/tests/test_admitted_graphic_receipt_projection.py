"""Current worker clocks must agree before projection into historical receipts."""
from __future__ import annotations

import copy
import unittest

from headless.admitted_graphic_receipt_projection import _writer_lane
from headless.admitted_graphic_receipt_types import AdmittedGraphicRenderReceiptError


def _lane() -> dict:
    """Synthetic schema-only input; no execution or publication claim."""
    asset = {'codec': 'prores', 'durationS': 2.5, 'fps': 30.0,
        'frameCount': 75, 'height': 1920, 'pixelFormat': 'yuva444p12le',
        'profile': '4444', 'sha256': 'a' * 64, 'sizeBytes': 10, 'width': 1080}
    return {'result': {'cached': False, 'fmt': 'mov', 'fps': '30',
        'key': 'b' * 64, 'kind': 'section-marker', 'path': '/test/graphic.mov',
        'proof': {'asset': asset}}, 'selectionId': 'held-selection'}


class CurrentReceiptClockProjectionTests(unittest.TestCase):
    """Only redundant verified transport metadata may leave the writer shape."""

    def test_matching_current_clock_preserves_original_and_measured_fps(self) -> None:
        original = _lane()
        before = copy.deepcopy(original)
        projected = _writer_lane(original)
        self.assertEqual(original, before)
        self.assertNotIn('fps', projected['result'])
        self.assertEqual(projected['result']['proof']['asset']['fps'], 30.0)
        self.assertEqual(projected['selectionId'], original['selectionId'])
        self.assertEqual(set(projected['result']), {'cached', 'fmt', 'key', 'kind', 'path', 'proof'})

    def test_unknown_or_missing_result_fields_are_not_silently_dropped(self) -> None:
        for change in ('extra', 'missing'):
            with self.subTest(change=change):
                value = _lane()
                if change == 'extra':
                    value['result']['unrecognized'] = True
                else:
                    del value['result']['fps']
                with self.assertRaises(AdmittedGraphicRenderReceiptError):
                    _writer_lane(value)

    def test_worker_clock_requires_current_exact_string(self) -> None:
        for fps in (30, 30.0, True, '30.0', '30000/1001', '60', None):
            with self.subTest(fps=fps):
                value = _lane()
                value['result']['fps'] = fps
                with self.assertRaisesRegex(AdmittedGraphicRenderReceiptError, 'FPS'):
                    _writer_lane(value)

    def test_measured_clock_cannot_disagree_or_use_coercible_types(self) -> None:
        for fps in (29.97, 60, True, '30', None, float('inf'), float('nan')):
            with self.subTest(fps=fps):
                value = _lane()
                value['result']['proof']['asset']['fps'] = fps
                with self.assertRaisesRegex(AdmittedGraphicRenderReceiptError, 'FPS'):
                    _writer_lane(value)

    def test_missing_measured_asset_is_not_a_clock_proof(self) -> None:
        value = _lane()
        value['result']['proof'] = {}
        with self.assertRaises(AdmittedGraphicRenderReceiptError):
            _writer_lane(value)


if __name__ == '__main__':
    unittest.main()
