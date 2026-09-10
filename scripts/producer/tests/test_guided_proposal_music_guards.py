"""V7 exact schema closure and live cut-hook tests, with no media or approval."""
from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _guided_proposal_music_fixture import values
from cut_preview_io import file_hash
from guided_body_execution import assert_body_files
import guided_body_pipeline as body_pipeline
from guided_media_profile import CAPTION_SHORT_PROFILE, OPENING_PROFILE
from guided_opening_inputs import OpeningInputs, _cut
import guided_opening_pipeline as opening_pipeline
from guided_proposal_reframe import V6_SCHEMA, V7_SCHEMA
from test_guided_proposal_reframe_guards import cut_inputs


class MusicHookTests(unittest.TestCase):
    """Request-derived geometry/music share real7 operations and locked cut authority."""

    def test_actual_cut_hook_accepts_seven_with_and_without_crop(self) -> None:
        """The same hook validates the no-crop branch and preserves actual7 mixed indices."""
        for crop in (False, True):
            plan, result, packet, manifest = values(crop=crop)
            profile = CAPTION_SHORT_PROFILE if crop else OPENING_PROFILE
            inputs = cut_inputs(plan, result, packet, profile)
            inputs.documents["manifest"] = manifest
            self.assertEqual(_cut(inputs), manifest["music"][0])

    def test_locked_target_and_cut_cannot_be_changed_by_music_request(self) -> None:
        """New authoring payloads never weaken existing cut/target checks."""
        for field in ("target", "cutTrack", "cutDecisions"):
            plan, result, packet, manifest = values()
            result[field] = {}
            inputs = cut_inputs(plan, result, packet, OPENING_PROFILE)
            inputs.documents["manifest"] = manifest
            with self.assertRaisesRegex(RuntimeError, "locked"):
                _cut(inputs)


class MusicClosureTests(unittest.TestCase):
    """V7 is held as7; it never borrows historical6 schema bytes or renews a clock."""

    def setUp(self) -> None:
        """Use a private inert closure rather than existing runtime or source inventories."""
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-music-closure-", dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.producer, self.schema = self.root / "scripts/producer", self.root / "schemas/producer"
        self.producer.mkdir(parents=True)
        self.schema.mkdir(parents=True)
        self.code = self.producer / "TEST_entry.py"
        self.code.write_text("# TEST ONLY inert Python bytes\n", encoding="utf-8")
        names = ("channel-normalization-receipt-v1.schema.json", V6_SCHEMA, V7_SCHEMA)
        for name in names:
            (self.schema / name).write_text('{"TEST": "' + name + '"}', encoding="utf-8")
        self.expected = {str(path.relative_to(self.root)): file_hash(path)
                         for path in (self.code, *(self.schema / name for name in names))}

    def test_actual_seven_schema_only_and_missing_or_changed_pin_rejects(self) -> None:
        """No actual7 request can be executed against only aV6 pinned schema."""
        logical = str((self.schema / V7_SCHEMA).relative_to(self.root))
        with patch.object(opening_pipeline, "__file__", str(self.producer / "guided_opening_pipeline.py")), \
                patch.object(opening_pipeline, "local_python_import_closure", return_value=[self.code]):
            old = opening_pipeline._execution_closure(self.expected, 5)
            seven = opening_pipeline._execution_closure(self.expected, 7)
            self.assertEqual(len(seven), len(old) + 1)
            self.assertIn({"path": logical, "sha256": self.expected[logical]}, seven)
            self.assertFalse(any(row["path"].endswith(V6_SCHEMA) for row in seven))
            with self.assertRaisesRegex(RuntimeError, "pinned closure"):
                opening_pipeline._execution_closure({key: value for key, value in self.expected.items()
                                                    if key != logical}, 7)
            (self.schema / V7_SCHEMA).write_text('{"TEST":"changed"}', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "pinned closure"):
                opening_pipeline._execution_closure(self.expected, 7)

    def test_body_holds_original_seven_schema_and_rechecks_late_bytes(self) -> None:
        """The existing body dependency holder includes the exact opening7 schema once."""
        control, lock = self.producer / "TEST_control.json", self.producer / "pipeline-lock.json"
        control.write_text('{"TEST":"control"}', encoding="utf-8")
        lock.write_text('{"TEST":"lock"}', encoding="utf-8")
        inputs = OpeningInputs(control, file_hash(control), {"documents": {},
            "pipeline": {"lockPath": str(lock), "lockSha256": file_hash(lock)}}, {})
        schema = self.schema / V7_SCHEMA
        row = {"path": str(schema.relative_to(self.root)), "sha256": file_hash(schema)}
        pipeline = {"bodyExecutionClosure": [row], "opening": {"executionClosure": [row], "tools": {}}}
        with patch.object(body_pipeline, "__file__", str(self.producer / "guided_body_pipeline.py")):
            held = body_pipeline.hold_body_dependencies(inputs, pipeline)
        self.assertEqual(sum(item.path == schema for item in held), 1)
        clock = SimpleNamespace(remaining=lambda: 10)
        assert_body_files(held, clock)
        schema.write_text('{"TEST":"replaced"}', encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            assert_body_files(held, clock)


if __name__ == "__main__":
    unittest.main()
