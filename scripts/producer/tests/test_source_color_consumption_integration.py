"""Actual writer-to-cold-consumption integration, with native/provenance TEST leaves.

The original source holder, cut/master recorder, compiler, manifestation joins,
publisher, finite file holds and packet parsers run. This is not decoded media,
full audio/source admission, color qualification, selection or human approval.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from _source_color_batch_fixture import current_batch_test_pins
from _source_color_consumption_integration_fixture import ConsumptionIntegrationFixture
from audio import audio_mix_picture
from guided_source_color_consumption_read import hold_source_color_consumption
from guided_source_color_media_evidence import write_source_color_media_evidence


class ConsumptionIntegrationTests(unittest.TestCase):
    """Production artifact domains cross the live/cold seam without weakening reader roles."""

    @classmethod
    def setUpClass(cls) -> None:
        """Capture current implementation pins once, only during a coordinated stable window."""
        cls.pins = current_batch_test_pins()

    def setUp(self) -> None:
        """Each case owns exact TEMP artifacts; production dependency files are never mutated."""
        self.f = ConsumptionIntegrationFixture(self.pins)
        self.addCleanup(self.f.cleanup)

    def test_actual_writer_and_recorder_outputs_survive_cold_consumption_replay(self) -> None:
        """Keep original clock, raw compiler floats, actual publication and all ordered occurrences."""
        f = self.f
        prepared = f.ready()
        ref = write_source_color_media_evidence(f.context, prepared, f.root)
        section = json.loads(Path(ref["path"]).read_bytes())
        context = f.read_context(ref, prepared, section["observations"])
        timeline = json.loads(f.timeline.read_bytes())
        manifestation = json.loads((f.base / "cut_manifestation.v1.json").read_bytes())
        self.assertIs(type(timeline["segments"][0]["src_start"]), float)
        self.assertIs(type(manifestation["parts"][0]["srcStart"]), float)
        self.assertIs(type(section["pictureConsumption"]["cuts"][0]["segment"]["src_start"]), int)
        self.assertEqual(context.deadline, f.source.clock.end)
        with patch.dict(os.environ, {"PATH": str(f.tools)}), \
                patch.object(audio_mix_picture, "_run", side_effect=f.native) as native:
            held = hold_source_color_consumption(section, context)
            self.assertEqual(held.record, section["pictureConsumption"])
            self.assertEqual(native.call_count, 3)
            held.check()
            held.assert_metadata()
            self.assertEqual(native.call_count, 3)
            self._publication(held.record)
            f.change(f.bus_path, b"TEST late bus substitution")
            self.assertRaisesRegex(RuntimeError, "changed", held.assert_metadata)
            self.assertEqual(native.call_count, 3)

    def _publication(self, record: dict) -> None:
        """Assert live seal/current base/copy joins with neither metadata-only provenance nor approval claims."""
        f = self.f
        self.assertEqual(record["basePublication"]["receiptPath"], str(f.master_path))
        self.assertEqual(record["basePublication"]["receipt"]["sha256"], f.base_sha)
        self.assertEqual(record["master"]["outputPath"], str(f.picture_path))
        self.assertEqual([row["segment"]["source_id"] for row in record["cuts"]], ["raw-b", "raw-a", "raw-b"])
        self.assertFalse(record["colorQualified"])
        self.assertFalse(record["deliveryApproved"])


if __name__ == "__main__":
    unittest.main()
