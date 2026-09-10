"""Deterministic plan-to-Palmier native caption mapping contracts."""
import unittest

from _common import *  # noqa: F401,F403
from palmier.desktop_native_captions import (
    MCP_CAPTION_KEYS, native_caption_settings,
    validate_native_caption_settings)
from palmier.live_acceptance_worklist_contract import validate_steps
from palmier.mcp_client import PalmierError


class NativeCaptionMappingTests(unittest.TestCase):
    def test_short_karaoke_maps_to_exact_mcp_vocabulary(self):
        settings = native_caption_settings({
            "target": {"mode": "short"},
            "captions": {"burn": True, "style": "karaoke"},
        })
        self.assertEqual(set(settings), {
            "language", "maxWords", "textCase", "fontName", "fontSize",
            "color", "borderColor", "highlightColor", "isBold", "isItalic",
            "alignment", "animation", "transform", "censorProfanity"})
        self.assertEqual(settings, {
            "language": "en", "maxWords": 4, "textCase": "auto",
            "fontName": "Inter", "fontSize": 58, "color": "#FFFFFF",
            "borderColor": "#000000", "highlightColor": "#FFD166",
            "isBold": True, "isItalic": False, "alignment": "center",
            "animation": "highlightBlock",
            "transform": {"centerX": 0.5, "centerY": 0.82},
            "censorProfanity": False,
        })

    def test_explicit_native_fields_override_defaults_but_meta_never_leaks(self):
        settings = native_caption_settings({
            "target": {"mode": "long"},
            "captions": {
                "burn": False, "style": "line", "animation": "wordReveal",
                "fontSize": 52, "backgroundColor": "#111827",
                "transform": {"centerX": 0.5, "centerY": 0.88},
            },
        })
        self.assertNotIn("burn", settings)
        self.assertNotIn("style", settings)
        self.assertEqual(settings["backgroundColor"], "#111827")
        self.assertEqual(settings["transform"]["centerY"], 0.88)
        self.assertLessEqual(set(settings), MCP_CAPTION_KEYS)

    def test_plan_and_tool_schema_drift_fail_before_execution(self):
        with self.assertRaisesRegex(PalmierError, "no native mapping"):
            native_caption_settings({
                "target": {"mode": "short"},
                "captions": {"style": "karaoke", "futureKnob": 1},
            })
        valid = native_caption_settings({
            "target": {"mode": "short"},
            "captions": {"style": "karaoke"},
        })
        with self.assertRaisesRegex(PalmierError, "schema drift"):
            validate_native_caption_settings({**valid, "burn": True})
        with self.assertRaisesRegex(PalmierError, "schema drift"):
            validate_steps([{"op": "native-captions",
                             "settings": {**valid, "futureKnob": 1}}], "repair")

    def test_transform_and_animation_are_strict(self):
        valid = native_caption_settings({
            "target": {"mode": "short"},
            "captions": {"style": "karaoke"},
        })
        with self.assertRaisesRegex(PalmierError, "centerX/centerY"):
            validate_native_caption_settings({
                **valid, "transform": {"centerY": 0.82}})
        with self.assertRaisesRegex(PalmierError, "unsupported"):
            validate_native_caption_settings({
                **valid, "animation": "karaoke"})

    def test_scalar_types_and_readability_bounds_are_strict(self):
        valid = native_caption_settings({
            "target": {"mode": "short"},
            "captions": {"style": "karaoke"},
        })
        cases = (
            ({"maxWords": 9}, "within 1-8"),
            ({"fontSize": float("nan")}, "fontSize"),
            ({"fontName": ""}, "string settings"),
            ({"isBold": 1}, "flags"),
            ({"censorProfanity": "false"}, "flags"),
        )
        for changed, message in cases:
            with self.subTest(changed=changed), self.assertRaisesRegex(
                    PalmierError, message):
                validate_native_caption_settings({**valid, **changed})


if __name__ == "__main__":
    unittest.main()
