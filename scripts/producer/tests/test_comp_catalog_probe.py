#!/usr/bin/env python3
"""Unit tests for the comp capability probe's STATIC pass (no renders)."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from graphics import comp_catalog_probe as probe
from graphics.graphics_render import COMPOSITIONS_DIR

_SYNTH_TOKENS = ":root { --canvas-w: 1080px; --canvas-h: 1920px; }"
_SYNTH_COMP = """<!doctype html>
<html data-composition-variables='[
  {"id":"text","type":"string","default":"Hello"},
  {"id":"slotX","type":"number","default":120},
  {"id":"align","type":"enum","default":"left"},
  {"id":"iconFile","type":"string","default":""}
]'>
<head><style>
  #syn-root { position: relative; width: var(--canvas-w); height: var(--canvas-h); }
</style></head>
<body><div id="syn-root" data-composition-id="synth" data-width="1080"
  data-height="1920" data-duration="2.5"></div></body></html>
"""


class TestStaticParse(unittest.TestCase):
    def test_synthetic_canvas_vars_and_knobs(self):
        self.assertEqual(probe.tokens_canvas(_SYNTH_TOKENS), (1080, 1920))
        self.assertEqual(probe.css_canvas(_SYNTH_COMP, _SYNTH_TOKENS),
                         (1080, 1920))
        entry = probe.static_probe("synth", _SYNTH_COMP)
        self.assertEqual(entry["canvas"], [1080, 1920])
        self.assertEqual(entry["aspect"], "9:16")
        self.assertEqual(entry["specFields"],
                         ["align", "iconFile", "slotX", "text"])
        self.assertEqual(entry["positionKnobs"], ["align", "slotX"])
        self.assertNotIn("canvasNote", entry)

    def test_real_statement_card_static(self):
        path = os.path.join(COMPOSITIONS_DIR, "statement-card.html")
        with open(path, encoding="utf-8") as handle:
            html = handle.read()
        entry = probe.static_probe("statement-card", html)
        self.assertEqual(entry["canvas"], [1920, 1080])
        self.assertEqual(entry["aspect"], "16:9")
        self.assertIn("text", entry["specFields"])
        self.assertEqual(entry["positionKnobs"], [])
        self.assertNotIn("canvasNote", entry)


class TestParseDeterminism(unittest.TestCase):
    def test_static_catalog_is_deterministic(self):
        first = probe.build_catalog(cache_dir="", workers=1, static_only=True)
        second = probe.build_catalog(cache_dir="", workers=1, static_only=True)
        self.assertEqual(first, second)
        self.assertEqual(first["digest"], second["digest"])
        self.assertEqual(len(first["comps"]), 46)

    def test_digest_tracks_content(self):
        catalog = probe.build_catalog(cache_dir="", workers=1,
                                      static_only=True)
        mutated = {**catalog, "comps": {**catalog["comps"]}}
        mutated["comps"]["statement-card"] = dict(
            mutated["comps"]["statement-card"], aspect="9:16")
        import hashlib
        import json
        digest = hashlib.sha1(json.dumps(
            mutated["comps"], sort_keys=True,
            ensure_ascii=True).encode("utf-8")).hexdigest()
        self.assertNotEqual(digest, catalog["digest"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
