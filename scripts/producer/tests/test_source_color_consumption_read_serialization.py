"""Real producer JSON spellings over owned TEMP artifacts; native leaf is STUBBED.

The normal renderer uses json.dump(indent=2) for timeline and manifestation,
whereas its source-color evidence uses canonical JSON. These are deliberately
different raw byte domains. No source, code, tool or native inventory is changed.
"""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from _source_color_consumption_read_fixture import ConsumptionReadFixture
from audio import audio_mix_picture
from cut_manifestation_authority import _expected_part
from guided_source_color_consumption_read import hold_source_color_consumption


class ProducerTimelineFixture(ConsumptionReadFixture):
    """Keep actual compile_stage JSON spelling before the real manifestation writer."""

    def _new(self, path: Path, raw: bytes) -> None:
        """Use the renderer's exact serializer only for its allowlisted TEMP timeline."""
        if path == self.paths["timelineMap"]:
            raw = json.dumps(self.timeline, indent=2).encode("utf8")
        super()._new(path, raw)


class ConsumptionSerializationTests(unittest.TestCase):
    """Real file/packet parsers must accept the producer's mixed numeric spelling."""

    def fixture(self, kind: type = ConsumptionReadFixture) -> ConsumptionReadFixture:
        """Own a fresh exact TEMP root; mock only the ffprobe subprocess leaf."""
        value = object.__new__(kind)
        self.addCleanup(value.cleanup)
        value.__init__()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {"PATH": str(value.tools)}))
        stack.enter_context(patch.object(audio_mix_picture, "_run", side_effect=value.native))
        return value

    def test_actual_producer_timeline_and_manifestation_json_are_readable(self) -> None:
        """Actual compile JSON retains 0.0/1.0; canonical evidence retains 0/1."""
        value = self.fixture(ProducerTimelineFixture)
        timeline = json.loads(value.paths["timelineMap"].read_bytes())
        self.assertIs(type(timeline["segments"][0]["src_start"]), float)
        self.assertIs(type(value.consumed["cuts"][0]["segment"]["src_start"]), int)
        held = hold_source_color_consumption(value.evidence, value.context)
        self.assertEqual(held.record, value.consumed)
        self.assertEqual(len(value.native_calls), 3)

    def test_actual_manifestation_float_fields_match_canonical_consumption(self) -> None:
        """Isolate raw manifestation floats from the separately canonical evidence join."""
        value = self.fixture()
        record = deepcopy(value.manifestation)
        record["parts"] = [_expected_part(segment, part)
            for segment, part in zip(value.timeline["segments"], record["parts"])]
        value.change(value.paths["cutManifestation"], json.dumps(record, indent=2).encode("utf8"))
        reference = value.ref(value.paths["cutManifestation"])
        value.evidence["fullProgram"]["cutManifestation"] = reference
        value.bindings["fullProgram"]["receipts"]["cutManifestation"] = reference
        value.reseal()
        self.assertIs(type(record["parts"][0]["srcStart"]), float)
        self.assertIs(type(value.consumed["manifestation"]["parts"][0]["srcStart"]), int)
        held = hold_source_color_consumption(value.evidence, value.context)
        self.assertEqual(held.record, value.consumed)
        self.assertEqual(len(value.native_calls), 3)


if __name__ == "__main__":
    unittest.main()
