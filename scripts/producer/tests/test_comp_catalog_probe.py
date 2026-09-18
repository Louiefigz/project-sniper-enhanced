#!/usr/bin/env python3
"""Unit tests for the comp capability probe's STATIC pass (no renders)."""
from __future__ import annotations

import os
import sys
import unittest
from copy import deepcopy
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
from graphics.template_contract import declared_variables, entry_errors
from graphics.template_visual_contract import pipeline_timing

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
        self.assertEqual(len(first["comps"]), 53)

    def test_digest_tracks_content(self):
        catalog = probe.build_catalog(cache_dir="", workers=1,
                                      static_only=True)
        mutated = {**catalog, "comps": {**catalog["comps"]}}
        mutated["comps"]["statement-card"] = dict(
            mutated["comps"]["statement-card"], aspect="9:16")
        digest = capability_digest(mutated["comps"])
        self.assertNotEqual(digest, catalog["digest"])


class TestExplicitPipelineProbe(unittest.TestCase):
    """Probe-only authored TEST content never weakens normal template admission."""

    def test_complete_pipeline_probe_has_explicit_content_and_exact_lands(self) -> None:
        """All present modules use real content, not the renderer's preview sample."""
        html = Path(COMPOSITIONS_DIR, "nateherk-pipeline.html").read_text()
        declared = declared_variables(html)
        before = deepcopy(declared)
        spec = probe.probe_spec("nateherk-pipeline", declared)
        for field in ("eyebrow", "headlineLines", "explainer", "nodes", "footChip"):
            self.assertTrue(spec.get(field), field)
        self.assertEqual(len(spec["headlineLines"].split("|")), 2)
        self.assertEqual(len(spec["nodes"].split("|")), 6)
        self.assertEqual(spec["moduleLands"], "0.2|1.1|2.0")
        self.assertEqual(spec["layout"], "full-canvas")
        self.assertIs(spec["presenterFrame"], False)
        self.assertEqual(spec["exit"], "hold")
        self.assertEqual(declared, before)

    def test_real_refresh_entry_obeys_final_module_dwell_and_rejects_blank(self) -> None:
        """The actual shared gate still rejects truncation and preview-only content."""
        html = Path(COMPOSITIONS_DIR, "nateherk-pipeline.html").read_text()
        entry = _entry("nateherk-pipeline", html)
        self.assertEqual(entry["outEnd"], 3.45)
        self.assertEqual(pipeline_timing(entry["spec"]), (2.0, 0.2, 0.0))
        self.assertEqual(entry_errors(entry, html), [])
        self.assertTrue(entry_errors({**entry, "outEnd": 3.44}, html))
        with self.assertRaisesRegex(ValueError, "no explicit content"):
            probe.probe_duration("nateherk-pipeline", {})

    def test_all_registered_refresh_entries_construct_without_gate_bypass(self) -> None:
        """Metadata preflight covers all 53 real kinds before any native work."""
        paths = composition_paths()
        self.assertEqual(len(paths), 53)
        for file in paths:
            source = Path(file).read_text()
            with self.subTest(kind=Path(file).stem):
                self.assertEqual(entry_errors(_entry(Path(file).stem, source), source), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
