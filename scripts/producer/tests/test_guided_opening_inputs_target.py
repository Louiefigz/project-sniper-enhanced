"""The opening worker's locked-target rule mirrors the TS input builder's style-only tolerance."""
from __future__ import annotations

import unittest

from _common import *  # noqa: F401,F403

from guided_opening_inputs import STYLE_ONLY_TARGET_KEYS, style_free_target


class StyleFreeTargetTests(unittest.TestCase):
    def test_only_v4_style_keys_are_removed_everything_else_stays_locked(self) -> None:
        accepted = {"mode": "longform", "scope": "produced", "width": 1920, "height": 1080, "fps": 30,
                    "lanes": {"motion": "off", "transitions": "off", "captions": "off", "broll": "off"}}
        candidate = {**accepted, "graphicsStyle": "cutaway-only",
                     "graphicsStyleRationale": "the cards are the variety"}
        self.assertEqual(style_free_target(candidate), accepted)
        self.assertEqual(STYLE_ONLY_TARGET_KEYS, ("graphicsStyle", "graphicsStyleRationale"))
        drifted = {**candidate, "excerpt": True}
        self.assertNotEqual(style_free_target(drifted), accepted)       # any other key still changes the lock
        self.assertNotEqual(style_free_target({**candidate, "fps": 24}), accepted)
        self.assertIsNone(style_free_target(None))                       # non-dicts compare as themselves


if __name__ == "__main__":
    unittest.main(verbosity=2)
