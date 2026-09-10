"""Actual lower cut/closure integration with inert TEST documents, never admission."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _guided_proposal_presenter_fixture import asset, noop, operation, values
from _guided_proposal_music_fixture import values as music_values
from cut_preview_io import file_hash
from guided_body_execution import assert_body_files
import guided_body_pipeline as body_pipeline
from guided_media_profile import CAPTION_SHORT_PROFILE, OPENING_PROFILE, profile_for_plan
import guided_opening_inputs as opening_inputs
from guided_opening_inputs import OpeningInputs, _cut
import guided_opening_pipeline as opening_pipeline
from guided_proposal_music import guided_music_policy
from guided_proposal_presenter import guided_presenter_policy
from guided_proposal_presenter_frames import V8_SCHEMA
from guided_proposal_reframe import V6_SCHEMA, V7_SCHEMA
from test_guided_proposal_reframe_guards import cut_inputs


def presenter_inputs(operations: list | None = None) -> OpeningInputs:
    """Pure held-shaped cut hashes exercise the real guard, not actual cut consent."""
    plan, candidate, packet, manifest = values(operations=operations)
    packet["evidence"]["musicPolicy"] = guided_music_policy(plan, manifest)
    result = cut_inputs(plan, candidate, packet, OPENING_PROFILE)
    result.documents["manifest"] = manifest
    return result


class PresenterCutGuardTests(unittest.TestCase):
    """Only prior-lane validation receives a local view; all held documents stay actual8."""

    def test_actual_v8_packet_and_candidate_survive_lower_hook_unchanged(self) -> None:
        """The helper runs first; old validators see7 but the exact candidate still carries layout."""
        inputs = presenter_inputs()
        before = deepcopy(inputs)
        original = inputs.documents["readinessPacket"]
        with patch.object(opening_inputs, "validate_requested_manual_crop", wraps=opening_inputs.validate_requested_manual_crop) as crop, \
                patch.object(opening_inputs, "validate_requested_music", wraps=opening_inputs.validate_requested_music) as music:
            self.assertIsNone(_cut(inputs))
        self.assertEqual(inputs, before)
        for call in (crop.call_args, music.call_args):
            self.assertIs(call.args[1], inputs.documents["candidatePlan"])
            self.assertIsNot(call.args[2], original)
            self.assertEqual(call.args[2]["proposal"]["schemaVersion"], 7)
            self.assertEqual(call.args[2]["evidence"]["schemaVersion"], 7)
            self.assertEqual(call.args[2]["proposal"]["clauses"], original["proposal"]["clauses"])
        self.assertEqual(original["proposal"]["operations"][0]["type"], "presenter-layout-window")
        with self.assertRaisesRegex(RuntimeError, "presenterLayouts"):
            profile_for_plan(inputs.documents["candidatePlan"], OPENING_PROFILE)

    def test_paired_style_is_exact_before_legacy_validators(self) -> None:
        """V8 cannot borrow the old style-free comparison to hide changed style metadata."""
        inputs = presenter_inputs()
        proposal = inputs.documents["readinessPacket"]["proposal"]
        target = inputs.documents["candidatePlan"]["target"]
        target.update({key: proposal[key] for key in ("graphicsStyle", "graphicsStyleRationale")})
        self.assertIsNone(_cut(inputs))
        for change in ({"graphicsStyleRationale": "different"}, {"width": 1080}, {"scope": "full"}, {"extra": None}):
            altered = deepcopy(inputs)
            altered.documents["candidatePlan"]["target"].update(change)
            with patch.object(opening_inputs, "validate_requested_music") as music, \
                    self.assertRaisesRegex(RuntimeError, "target"):
                _cut(altered)
            music.assert_not_called()

    def test_historical_versions_and_actual8_noop_preserve_inherited_track(self) -> None:
        """Old parsers receive actual versions, while8 no-op still supplies the verified local7 view."""
        for version in range(2, 9):
            inputs = presenter_inputs([noop()])
            packet = inputs.documents["readinessPacket"]
            packet["proposal"]["schemaVersion"] = packet["evidence"]["schemaVersion"] = version
            if version < 8:
                del packet["proposal"]["operations"][0]["presenterLayout"]
            if version < 7:
                del packet["proposal"]["operations"][0]["music"]
            inputs.documents["acceptedPlan"]["presenterLayouts"] = None
            inputs.documents["candidatePlan"]["presenterLayouts"] = None
            # Recreate TEST cut hashes after original initial plan authoring, never patch a held real project.
            current = cut_inputs(inputs.documents["acceptedPlan"], inputs.documents["candidatePlan"], packet, OPENING_PROFILE)
            current.documents["manifest"] = inputs.documents["manifest"]
            self.assertIsNone(_cut(current))
            del current.documents["candidatePlan"]["presenterLayouts"]
            with self.assertRaisesRegex(RuntimeError, "inherited"):
                _cut(current)

    def test_bad_versions_or_unrequested_layout_reject_before_prior_lane_work(self) -> None:
        """Unknown/coerced versions never reach a historical no-op path."""
        for version in (True, 8.0, "8", 1, 9, None):
            inputs = presenter_inputs()
            inputs.documents["readinessPacket"]["proposal"]["schemaVersion"] = version
            with patch.object(opening_inputs, "validate_requested_manual_crop") as crop, \
                    self.assertRaisesRegex(RuntimeError, "integer proposal"):
                _cut(inputs)
            crop.assert_not_called()
        inputs = presenter_inputs([noop()])
        inputs.documents["candidatePlan"]["presenterLayouts"] = []
        with self.assertRaisesRegex(RuntimeError, "inherited"):
            _cut(inputs)

    def test_v8_crop_keeps_candidate_layout_and_current_profile_refuses(self) -> None:
        """A validated presenter field is not stripped to bypass the legacy manual-caption guard."""
        plan, candidate, packet, manifest = music_values(crop=True)
        for target in (plan["target"], candidate["target"]):
            target.update(scope="produced", lanes={"captions": "auto", "graphics": "off"})
        packet["proposal"]["schemaVersion"] = packet["evidence"]["schemaVersion"] = 8
        for row in packet["proposal"]["operations"]:
            row["presenterLayout"] = None
        presenter = operation()
        presenter.update(startAnchor=0, endAnchorExclusive=1)
        presenter["presenterLayout"].update(sourceIds=["raw-1"], enterFrames=1, exitFrames=1)
        index = len(packet["proposal"]["operations"])
        packet["proposal"]["operations"].append(presenter)
        packet["proposal"]["clauses"][0]["operationIndices"].append(index)
        manifest["broll"] = [asset()]
        packet["evidence"].update(target=deepcopy(plan["target"]), frameRate="30/1", totalFrames=258, anchors=[0, 258],
            segments=[{"index": 0, "sourceId": "raw-1", "startFrame": 0, "endFrameExclusive": 258}],
            presenterPolicy=guided_presenter_policy(plan, manifest))
        candidate["presenterLayouts"] = [{"operationIndex": index, "startFrame": 0, "endFrameExclusive": 258,
            "layout": deepcopy(presenter["presenterLayout"])}]
        inputs = cut_inputs(plan, candidate, packet, CAPTION_SHORT_PROFILE)
        inputs.documents["manifest"] = manifest
        before = deepcopy(inputs)
        with self.assertRaisesRegex(RuntimeError, "presenterLayouts"):
            _cut(inputs)
        self.assertEqual(inputs, before)


class PresenterClosureTests(unittest.TestCase):
    """Both actual8 and local7 schema bytes belong to the held execution closure."""

    def setUp(self) -> None:
        """New private inert files replace only the fixture's imported source inventory."""
        temp = tempfile.TemporaryDirectory(prefix="sniper-presenter-schema-", dir="/private/tmp")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.producer, self.schema = self.root / "scripts/producer", self.root / "schemas/producer"
        self.producer.mkdir(parents=True)
        self.schema.mkdir(parents=True)
        self.code = self.producer / "TEST_entry.py"
        self.code.write_text("# TEST ONLY inert closure\n", encoding="utf-8")
        names = ("channel-normalization-receipt-v1.schema.json", V6_SCHEMA, V7_SCHEMA, V8_SCHEMA)
        for name in names:
            (self.schema / name).write_text('{"TEST":"' + name + '"}', encoding="utf-8")
        self.expected = {str(path.relative_to(self.root)): file_hash(path) for path in (self.code, *(self.schema / name for name in names))}

    def closure(self, expected: dict, version: int) -> list:
        """Run actual closure comparison against a tiny independent TEST root."""
        with patch.object(opening_pipeline, "__file__", str(self.producer / "guided_opening_pipeline.py")), \
                patch.object(opening_pipeline, "local_python_import_closure", return_value=[self.code]):
            return opening_pipeline._execution_closure(expected, version)

    def test_v8_requires_both_exact_schemas_but_old_versions_do_not(self) -> None:
        """No schema7-only pin can silently authorize actual8 or vice versa."""
        current = self.closure(self.expected, 8)
        wanted = {str((self.schema / name).relative_to(self.root)) for name in (V8_SCHEMA, V7_SCHEMA)}
        self.assertTrue(wanted.issubset({row["path"] for row in current}))
        self.assertEqual(len(current), len(self.closure(self.expected, 5)) + 2)
        self.assertFalse(any(row["path"].endswith(V8_SCHEMA) for row in self.closure(self.expected, 7)))
        for missing in wanted:
            with self.assertRaisesRegex(RuntimeError, "pinned closure"):
                self.closure({key: value for key, value in self.expected.items() if key != missing}, 8)
        for changed in wanted:
            path = self.root / changed
            old = path.read_bytes()
            path.write_bytes(b'{"TEST":"different"}')
            with self.assertRaisesRegex(RuntimeError, "pinned closure"):
                self.closure(self.expected, 8)
            path.write_bytes(old)

    def test_body_retains_both_schemas_and_rejects_late_change(self) -> None:
        """Existing body dependency holding includes both exact opening schema rows."""
        control, lock = self.producer / "TEST_control.json", self.producer / "pipeline-lock.json"
        control.write_text('{"TEST":"input"}', encoding="utf-8")
        lock.write_text('{"TEST":"lock"}', encoding="utf-8")
        inputs = OpeningInputs(control, file_hash(control), {"documents": {},
            "pipeline": {"lockPath": str(lock), "lockSha256": file_hash(lock)}}, {})
        rows = [{"path": str((self.schema / name).relative_to(self.root)), "sha256": file_hash(self.schema / name)} for name in (V7_SCHEMA, V8_SCHEMA)]
        pipeline = {"bodyExecutionClosure": [], "opening": {"executionClosure": rows, "tools": {}}}
        with patch.object(body_pipeline, "__file__", str(self.producer / "guided_body_pipeline.py")):
            held = body_pipeline.hold_body_dependencies(inputs, pipeline)
        self.assertTrue({self.schema / V7_SCHEMA, self.schema / V8_SCHEMA}.issubset({item.path for item in held}))
        (self.schema / V8_SCHEMA).write_text('{"TEST":"late replacement"}', encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            assert_body_files(held, SimpleNamespace(remaining=lambda: 10))


if __name__ == "__main__":
    unittest.main()
