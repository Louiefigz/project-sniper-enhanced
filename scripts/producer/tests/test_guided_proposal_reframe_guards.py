"""Actual cut/closure hook tests with pure TEST authority values and tiny JSON files."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _guided_proposal_reframe_fixture import accepted, candidate, operation, packet, replace_operations
from cut_preview_authority import REQUEST_HASHES
from cut_preview_io import digest, file_hash
from edit.compatibility_projection import build_projection
from guided_body_execution import assert_body_files, revalidate_body_files
import guided_body_pipeline as body_pipeline
import guided_opening_pipeline as opening_pipeline
from guided_opening_inputs import OpeningInputs, _cut
from guided_media_profile import CAPTION_SHORT_PROFILE, SHORT_PROFILE
from guided_proposal_reframe import V6_SCHEMA


def cut_inputs(plan: dict, result: dict, proposal: dict, profile: str = CAPTION_SHORT_PROFILE) -> OpeningInputs:
    """TEST-only hashes exercise relational guards, never create an approval fact."""
    projection = build_projection(plan, digest(plan))
    request = {key: "a" * 64 for key in REQUEST_HASHES}
    request.update(schemaVersion=1, createdAt="2026-09-07T00:00:00.000Z", planHash=digest(plan),
                   timelineMapHash=projection["timelineMapHash"], projectionReceiptHash=digest(projection))
    lock = {key: request[key] for key in ("cutAuthorityDigest", "cutApprovalReceiptHash",
            "cutReviewApprovalReceiptHash", "timelineMapHash", "projectionReceiptHash")}
    lock.update(approvedCutPlanHash=digest(plan), manifestHash="b" * 64)
    request["pictureLockHash"] = digest(lock)
    request["requestHash"] = digest({key: value for key, value in request.items() if key != "requestHash"})
    refs = {"acceptedPlan": {"sha256": request["planHash"]}, "pictureLock": {"sha256": request["pictureLockHash"]},
            "cutProjection": {"sha256": request["projectionReceiptHash"]}, "manifest": {"sha256": lock["manifestHash"]}}
    docs = {"acceptedPlan": plan, "candidatePlan": result, "readinessPacket": proposal, "cutRequest": request,
            "pictureLock": lock, "cutProjection": projection, "timelineMap": projection["timelineMap"]}
    return OpeningInputs(Path("/TEST-not-a-source-or-approval/input.json"), "c" * 64,
                         {"profile": profile, "documents": refs}, docs)


class CutGuardTests(unittest.TestCase):
    def test_actual_cut_hook_permits_only_exact_request_derived_crop(self) -> None:
        _cut(cut_inputs(accepted(), candidate(), packet()))
        result = candidate()
        result["reframe"]["crop"] = [0, 0, 1, 1]
        with self.assertRaisesRegex(RuntimeError, "requested projection"):
            _cut(cut_inputs(accepted(), result, packet()))

    def test_existing_cut_decisions_and_target_guards_stay_before_exception(self) -> None:
        changes = [{"cutTrack": [{"sourceId": "raw-1", "start": 2, "end": 9.8, "speed": 1}]},
                   {"cutDecisions": {"removals": ["TEST changed"]}}, {"target": {**accepted()["target"], "fps": 24}}]
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(RuntimeError, "locked"):
                _cut(cut_inputs(accepted(), {**candidate(), **change}, packet()))

    def test_v4_v5_and_v6_without_crop_cannot_borrow_new_exception(self) -> None:
        proposals = []
        for version in (4, 5):
            request = packet()
            request["proposal"]["schemaVersion"] = version
            proposals.append(request)
        proposals.append(replace_operations(packet(), [operation("preserve-cut")]))
        for request in proposals:
            with self.subTest(request=request), self.assertRaisesRegex(RuntimeError, "submitted manual short reframe"):
                _cut(cut_inputs(accepted(), candidate(), request))

    def test_old_manual_short_matching_geometry_and_captions_remains_accepted(self) -> None:
        plan = candidate()
        plan["captions"] = {"burn": False}
        del plan["captionsTrack"]
        request = packet()
        request["proposal"]["schemaVersion"] = 4
        _cut(cut_inputs(plan, deepcopy(plan), request, SHORT_PROFILE))
        changed = {**plan, "captions": {"burn": True}}
        with self.assertRaisesRegex(RuntimeError, "captions"):
            _cut(cut_inputs(plan, changed, request, SHORT_PROFILE))

    def test_style_only_target_tolerance_remains_but_crop_needs_caption_profile(self) -> None:
        result = candidate()
        result["target"]["graphicsStyle"] = "cutaway-only"
        result["target"]["graphicsStyleRationale"] = "TEST ONLY prior style tolerance."
        _cut(cut_inputs(accepted(), result, packet()))
        with self.assertRaisesRegex(RuntimeError, "profile"):
            _cut(cut_inputs(accepted(), result, packet(), SHORT_PROFILE))


class DependencyGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-v6-draft-pure-", dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.producer = self.root / "scripts/producer"
        self.producer.mkdir(parents=True)
        self.schema = self.root / "schemas/producer"
        self.schema.mkdir(parents=True)
        self.code = self.producer / "TEST_entry.py"
        self.code.write_text("# TEST ONLY inert closure bytes\n", encoding="utf-8")
        self.normal = self.schema / "channel-normalization-receipt-v1.schema.json"
        self.normal.write_text('{"TEST": "normal"}', encoding="utf-8")
        self.extra = self.schema / V6_SCHEMA
        self.extra.write_text('{"TEST": "V6"}', encoding="utf-8")

    def expected(self) -> dict:
        return {str(path.relative_to(self.root)): file_hash(path) for path in (self.code, self.normal, self.extra)}

    def test_only_v6_adds_exact_schema_and_changed_json_rejects(self) -> None:
        expected = self.expected()
        with patch.object(opening_pipeline, "__file__", str(self.producer / "guided_opening_pipeline.py")), \
                patch.object(opening_pipeline, "local_python_import_closure", return_value=[self.code]):
            old = opening_pipeline._execution_closure(expected)
            self.assertEqual(old, opening_pipeline._execution_closure(expected, 5))
            current = opening_pipeline._execution_closure(expected, 6)
            self.assertEqual(len(current), len(old) + 1)
            self.assertIn({"path": str(self.extra.relative_to(self.root)), "sha256": file_hash(self.extra)}, current)
            self.extra.write_text('{"TEST": "changed"}', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "pinned closure"):
                opening_pipeline._execution_closure(expected, 6)

    def dependencies(self, duplicate: bool = False) -> tuple:
        control = self.producer / "TEST_control.json"
        control.write_text('{"TEST": "control"}', encoding="utf-8")
        lock = self.producer / "pipeline-lock.json"
        lock.write_text('{"TEST": "lock"}', encoding="utf-8")
        inputs = OpeningInputs(control, file_hash(control), {"documents": {},
            "pipeline": {"lockPath": str(lock), "lockSha256": file_hash(lock)}}, {})
        row = {"path": str(self.extra.relative_to(self.root)), "sha256": file_hash(self.extra)}
        pipeline = {"bodyExecutionClosure": [row] if duplicate else [],
                    "opening": {"executionClosure": [row], "tools": {}}}
        return inputs, pipeline, row

    def test_body_holds_extra_opening_schema_once_and_detects_late_change(self) -> None:
        inputs, pipeline, _ = self.dependencies(True)
        with patch.object(body_pipeline, "__file__", str(self.producer / "guided_body_pipeline.py")):
            held = body_pipeline.hold_body_dependencies(inputs, pipeline)
        self.assertEqual(sum(row.path == self.extra for row in held), 1)
        clock = SimpleNamespace(remaining=lambda: 10)
        revalidate_body_files(held, clock)
        self.extra.write_text('{"TEST": "changed JSON"}', encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            assert_body_files(held, clock)

    def test_body_rejects_conflicting_code_and_opening_schema_hash(self) -> None:
        inputs, pipeline, row = self.dependencies()
        pipeline["bodyExecutionClosure"] = [row]
        pipeline["opening"]["executionClosure"] = [{**row, "sha256": "a" * 64}]
        with patch.object(body_pipeline, "__file__", str(self.producer / "guided_body_pipeline.py")), \
                self.assertRaisesRegex(RuntimeError, "conflicting"):
            body_pipeline.hold_body_dependencies(inputs, pipeline)


if __name__ == "__main__":
    unittest.main()
