#!/usr/bin/env python3
"""Unit tests for the comp capability probe's STATIC pass (no renders)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from graphics import comp_catalog_probe as probe
from graphics.comp_capability_artifact import (
    SCHEMA_VERSION,
    capability_digest,
    composition_paths,
    current_source_digest,
)
from graphics.comp_capability_refresh import _entry
from graphics.graphics_render import COMPOSITIONS_DIR
from graphics.template_contract import entry_errors

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

    def test_real_catalog_line_swap_static(self):
        path = os.path.join(COMPOSITIONS_DIR, "line-swap.html")
        with open(path, encoding="utf-8") as handle:
            html = handle.read()
        entry = probe.static_probe("line-swap", html)
        self.assertEqual(entry["canvas"], [1080, 1920])
        self.assertEqual(entry["aspect"], "9:16")
        self.assertIn("lineA", entry["specFields"])
        self.assertEqual(entry["positionKnobs"], [])
        self.assertNotIn("canvasNote", entry)


class TestParseDeterminism(unittest.TestCase):
    def test_glitch_probe_uses_its_real_transient_window(self):
        self.assertEqual(probe.probe_duration(
            "glitch-hit", {"durMs": 400}), 0.4)

    def test_static_catalog_is_deterministic(self):
        first = probe.build_catalog(cache_dir="", workers=1, static_only=True)
        second = probe.build_catalog(cache_dir="", workers=1, static_only=True)
        self.assertEqual(first, second)
        self.assertEqual(first["digest"], second["digest"])
        self.assertEqual(first["schemaVersion"], SCHEMA_VERSION)
        self.assertEqual(first["sourceDigest"], current_source_digest())
        self.assertEqual(len(first["comps"]), 7)

    def test_digest_tracks_content(self):
        catalog = probe.build_catalog(cache_dir="", workers=1,
                                      static_only=True)
        mutated = {**catalog, "comps": {**catalog["comps"]}}
        mutated["comps"]["line-swap"] = dict(
            mutated["comps"]["line-swap"], aspect="16:9")
        digest = capability_digest(mutated["comps"])
        self.assertNotEqual(digest, catalog["digest"])


class TestExplicitPipelineProbe(unittest.TestCase):
    """Probe-only authored TEST content never weakens normal template admission."""

    def test_retired_pipeline_is_absent_and_rejected(self) -> None:
        """Probe defaults cannot register a retired design for delivery."""
        self.assertFalse(Path(COMPOSITIONS_DIR, "module-pipeline.html").exists())
        entry = {"kind": "module-pipeline", "spec": {}, "outStart": 0, "outEnd": 4}
        self.assertTrue(any("retired" in error for error in entry_errors(entry)))

    def test_all_registered_refresh_entries_construct_without_gate_bypass(self) -> None:
        """Metadata preflight covers all seven registered catalog ports before any native work."""
        paths = composition_paths()
        self.assertEqual(len(paths), 7)
        for file in paths:
            source = Path(file).read_text()
            with self.subTest(kind=Path(file).stem):
                self.assertEqual(entry_errors(_entry(Path(file).stem, source), source), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
