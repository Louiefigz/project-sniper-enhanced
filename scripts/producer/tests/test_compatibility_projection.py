"""Focused contract tests for the P1 compatibility timeline projection."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edit import compatibility_projection as projection  # noqa: E402


APPROVED_HASH = "a" * 64


def _plan() -> dict:
    return {
        "planVersion": 1,
        "cutTrack": [
            {"sourceId": "raw-1", "start": 0, "end": 4, "speed": 1},
            {"sourceId": "raw-2", "start": 5, "end": 11, "speed": 1},
        ],
        "cutDecisions": {"schemaVersion": 1, "removals": []},
    }


class CompatibilityProjectionTests(unittest.TestCase):
    def test_projection_is_deterministic_across_object_key_order(self) -> None:
        first = projection.build_projection(_plan(), APPROVED_HASH)
        reordered = json.loads(json.dumps(_plan(), sort_keys=True))
        second = projection.build_projection(reordered, APPROVED_HASH)
        self.assertEqual(first, second)
        self.assertEqual(
            projection.canonical_json(first), projection.canonical_json(second))

    def test_speed_changes_cut_timeline_and_receipt_digests(self) -> None:
        baseline = projection.build_projection(_plan(), APPROVED_HASH)
        changed_plan = _plan()
        changed_plan["cutTrack"][1]["speed"] = 2
        changed = projection.build_projection(changed_plan, APPROVED_HASH)
        for key in ("cutTrackDigest", "timelineMapHash"):
            self.assertNotEqual(baseline[key], changed[key])
        self.assertNotEqual(
            projection.stable_digest(baseline),
            projection.stable_digest(changed))
        self.assertEqual(baseline["timelineMap"]["outputDuration"], 10)
        self.assertEqual(changed["timelineMap"]["outputDuration"], 7)

    def test_audio_lead_changes_map_hash_without_changing_picture_length(self) -> None:
        baseline = projection.build_projection(_plan(), APPROVED_HASH)
        changed_plan = _plan()
        changed_plan["cutTrack"][1]["audioLeadMs"] = 120
        changed = projection.build_projection(changed_plan, APPROVED_HASH)
        self.assertEqual(baseline["timelineMap"]["outputDuration"],
                         changed["timelineMap"]["outputDuration"])
        self.assertNotEqual(baseline["timelineMapHash"], changed["timelineMapHash"])
        self.assertEqual(
            changed["timelineMap"]["segments"][1]["audio_lead_s"], 0.12)

    def test_lf14_precision_survives_projection_and_hash_payload(self) -> None:
        plan = _plan()
        plan["cutTrack"] = [
            {
                "sourceId": "raw-1", "start": 70.07,
                "end": 733.2325, "speed": 1.0,
            },
            {
                "sourceId": "raw-1", "start": 736.5691666666667,
                "end": 913.3707916666667, "speed": 1.0,
            },
        ]
        result = projection.build_projection(plan, APPROVED_HASH)
        timeline = result["timelineMap"]
        payload = projection.timeline_hash_payload(timeline)
        self.assertEqual(timeline["outputDuration"], 839.964125)
        self.assertEqual(timeline["segments"][-1]["out_end"], 839.964125)
        self.assertEqual(payload["outputDuration"], 839_964_125)
        self.assertEqual(
            payload["segments"][-1]["out_end"],
            839_964_125,
        )

    def test_hashes_are_self_consistent(self) -> None:
        result = projection.build_projection(_plan(), APPROVED_HASH)
        self.assertEqual(
            result["cutTrackDigest"], projection.stable_digest(_plan()["cutTrack"]))
        self.assertEqual(result["cutDecisionsDigest"],
                         projection.stable_digest(_plan()["cutDecisions"]))
        self.assertEqual(result["timelineMapHash"],
                         projection.stable_digest(
                             projection.timeline_hash_payload(
                                 result["timelineMap"])))
        stored = json.loads(projection.canonical_json(result))
        self.assertEqual(
            result["timelineMapHash"],
            projection.stable_digest(
                projection.timeline_hash_payload(stored["timelineMap"])))
        self.assertRegex(result["compilerHash"], r"^[a-f0-9]{64}$")
        self.assertRegex(projection.stable_digest(result), r"^[a-f0-9]{64}$")

    def test_shared_schema_matches_emitted_projection(self) -> None:
        schema_path = (
            Path(__file__).resolve().parents[3] / "schemas" / "producer"
            / "compatibility-timeline-projection-v1.schema.json")
        with schema_path.open(encoding="utf-8") as handle:
            schema = json.load(handle)
        result = projection.build_projection(_plan(), APPROVED_HASH)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(result), set(schema["required"]))
        self.assertEqual(set(result), set(schema["properties"]))
        segment = result["timelineMap"]["segments"][0]
        segment_schema = schema["$defs"]["segment"]
        self.assertEqual(set(segment), set(segment_schema["required"]))
        self.assertEqual(set(segment), set(segment_schema["properties"]))

    def test_rejects_malformed_hash_and_plan(self) -> None:
        invalid = [
            (copy.deepcopy(_plan()), "A" * 64),
            ({"cutTrack": [], "cutDecisions": {
                "schemaVersion": 1, "removals": []}}, APPROVED_HASH),
            ({**_plan(), "cutDecisions": []}, APPROVED_HASH),
        ]
        zero_speed = _plan()
        zero_speed["cutTrack"][0]["speed"] = 0
        invalid.append((zero_speed, APPROVED_HASH))
        negative_start = _plan()
        negative_start["cutTrack"][0]["start"] = -1
        invalid.append((negative_start, APPROVED_HASH))
        for plan, approved_hash in invalid:
            with self.subTest(plan=plan, approved_hash=approved_hash):
                with self.assertRaises(projection.ProjectionError):
                    projection.build_projection(plan, approved_hash)

    def test_compile_plan_remains_audio_lead_validator(self) -> None:
        plan = _plan()
        plan["cutTrack"][0]["audioLeadMs"] = 80
        with self.assertRaisesRegex(
                projection.ProjectionError, "timeline compilation failed"):
            projection.build_projection(plan, APPROVED_HASH)

    def test_cli_loads_plan_and_writes_exact_canonical_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan_path = os.path.join(directory, "edit_plan.json")
            out_path = os.path.join(directory, "projection.json")
            with open(plan_path, "w", encoding="utf-8") as handle:
                json.dump(_plan(), handle)
            self.assertEqual(
                projection.main([plan_path, APPROVED_HASH, out_path]), 0)
            with open(out_path, encoding="utf-8") as handle:
                raw = handle.read()
            parsed = json.loads(raw)
            self.assertEqual(raw, projection.canonical_json(parsed) + "\n")

    def test_compiler_hash_binds_declared_source_bytes_and_python(self) -> None:
        self.assertIn(
            Path(projection.__file__).resolve(), projection._COMPILER_SOURCES)
        digest = hashlib.sha256(projection._COMPILER_DOMAIN)
        version = (
            f"{sys.version_info.major}.{sys.version_info.minor}".encode("ascii"))
        projection._bind_part(digest, "python-major-minor", version)
        for path in projection._COMPILER_SOURCES:
            projection._bind_part(digest, path.name, path.read_bytes())
        self.assertEqual(projection.compiler_hash(), digest.hexdigest())

    def test_compiler_hash_changes_when_projection_semantics_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "compatibility_projection.py"
            source.write_text("semantic-version = 1\n", encoding="utf-8")
            declared = projection._COMPILER_SOURCES
            try:
                projection._COMPILER_SOURCES = (source,)
                baseline = projection.compiler_hash()
                source.write_text("semantic-version = 2\n", encoding="utf-8")
                self.assertNotEqual(baseline, projection.compiler_hash())
            finally:
                projection._COMPILER_SOURCES = declared


if __name__ == "__main__":
    unittest.main(verbosity=2)
