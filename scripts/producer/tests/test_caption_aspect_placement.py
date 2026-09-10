"""Explicit caption aspect boundaries preserve placement intent and portrait bytes."""
from __future__ import annotations

import unittest

from captions.caption_ass_projection import _style_line
from captions.caption_contract import CaptionContractError
from captions.caption_plan_pipeline import _destination
from producer_config import CAPTION_LAYOUT_BY_ASPECT, SAFE_BOX


def _baseline(destination: dict, placement: str) -> int:
    """Read actual ASS bottom alignment, not an independent approximate formula."""
    fields = _style_line(0, {'placement': placement}, {'font': 'Inter'}, destination).split(',')
    return destination['height'] - int(fields[-2])


class CaptionAspectPlacementTests(unittest.TestCase):
    """Landscape must not inherit portrait's large bottom platform obstruction."""

    def test_portrait_destination_and_ass_placement_are_unchanged(self) -> None:
        actual = _destination({'target': {'mode': 'short'}})
        expected = {'profileId': 'short-9x16', 'width': 1080, 'height': 1920,
                    'safeZones': dict(SAFE_BOX)}
        self.assertEqual(actual, expected)
        for placement in ('bottom-center', 'lower-third', 'center', 'top-center'):
            with self.subTest(placement=placement):
                cue = {'placement': placement}
                self.assertEqual(_style_line(0, cue, {}, actual), _style_line(0, cue, {}, expected))

    def test_landscape_bottom_center_keeps_declared_seventy_percent_position(self) -> None:
        destination = _destination({'target': {'mode': 'longform'}})
        self.assertEqual(_baseline(destination, 'bottom-center'), round(1080 * .70))
        self.assertGreater(_baseline(destination, 'bottom-center'), 1080 * .65)

    def test_landscape_insets_use_current_landscape_layout_authority(self) -> None:
        destination = _destination({'target': {'mode': 'longform'}})
        layout = CAPTION_LAYOUT_BY_ASPECT['16:9']
        self.assertEqual(destination['safeZones'], {
            'top': round(SAFE_BOX['top'] * 1080 / 1920),
            'bottom': 1080 - layout['baseline_max_y'],
            'left': layout['margin_l'], 'right': layout['margin_r']})
        self.assertEqual(_baseline(destination, 'lower-third'), round(1080 * .76))

    def test_unknown_target_cannot_infer_a_destination(self) -> None:
        with self.assertRaises(CaptionContractError):
            _destination({'target': {'mode': 'unknown'}})


if __name__ == '__main__':
    unittest.main(verbosity=2)
