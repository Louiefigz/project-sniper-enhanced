"""Production alternate-take orchestration derives choice and fails closed."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from edit.alternate_take_candidates import alternate_take_output_range
from edit.alternate_take_controller import run
from edit.alternate_take_types import AlternateTakeAuthorityError
from edit.cut_repair_context_sources import canonical_bytes
from tests._p2_alternate_take_fixture import AlternateTakeFixture
from tests._p2_candidate_qc_fixture import CandidateQcFixture, _write

_REGION = {
    "xPpm": 250_000, "yPpm": 420_000,
    "widthPpm": 500_000, "heightPpm": 300_000,
}


def _request(region: dict | None = None) -> dict:
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-alternate-take-request",
        "visualSpeechRegion": region or _REGION,
    }


class AlternateTakeControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = AlternateTakeFixture()
        self.manifest_path = os.path.join(
            self.fixture.producer, "manifest.json")
        self._write_manifest()

    def tearDown(self) -> None:
        self.fixture.clean()

    def _write_manifest(self, source_id: str = "raw-1") -> None:
        value = {"sources": [{
            "id": source_id,
            "path": self.fixture.base.source_path,
            "contentHash": self.fixture.base.source_hash,
            "transcriptPath": "raw.transcript.json",
        }]}
        _write(self.manifest_path, canonical_bytes(value))

    def _run(self, request: dict | None = None) -> dict:
        return run(
            self.fixture.producer, self.fixture.preparation_hash,
            self.manifest_path, request if request is not None else _request())

    def test_inserted_window_uses_inside_edge_for_both_directions(self) -> None:
        context = {
            "totalFrames": 120,
            "segments": [{
                "segmentId": "segment-a", "elementVersion": 1,
                "outputFrames": {"startFrame": 30, "endFrameExclusive": 90},
            }],
        }
        operation = {
            "segment": {
                "segmentId": "segment-a", "elementVersion": 1,
                "edge": "start",
            },
            "extensionFrames": 18,
            "pictureDirtyWindows": [
                {"startFrame": 30, "endFrameExclusive": 90}],
        }
        self.assertEqual(
            alternate_take_output_range(context, operation),
            {"firstFrame": 30, "endFrameExclusive": 48})
        operation["segment"]["edge"] = "end"
        self.assertEqual(
            alternate_take_output_range(context, operation),
            {"firstFrame": 72, "endFrameExclusive": 90})

    def test_derives_unique_matching_later_take_without_caller_id(self) -> None:
        result = self._run()
        self.assertEqual(result["status"], "selection-published")
        self.assertEqual(
            result["selectedCandidateId"],
            self.fixture.selected["candidateId"])
        self.assertNotIn("retakeId", _request())
        self.assertNotIn("candidateId", _request())
        self.assertNotIn("transcriptPath", _request())

    def test_cli_executes_same_production_controller(self) -> None:
        request_path = os.path.join(self.fixture.producer, "selection.json")
        _write(request_path, canonical_bytes({
            "schemaVersion": 1,
            "kind": "cut-repair-alternate-take-controller-input",
            "alternateTake": _request(),
        }))
        script = os.path.realpath(
            os.path.join(os.path.dirname(__file__), "..", "edit",
                         "alternate_take_controller.py"))
        result = subprocess.run(
            [sys.executable, script, self.fixture.producer,
             self.fixture.preparation_hash, self.manifest_path, request_path],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env={**os.environ, "PYTHONPATH":
                 os.path.dirname(os.path.dirname(__file__))},
            capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"],
                         "selection-published")

    def test_missing_visual_region_blocks_picture_preparation(self) -> None:
        with self.assertRaisesRegex(
                AlternateTakeAuthorityError, "explicit visual speech region"):
            run(
                self.fixture.producer, self.fixture.preparation_hash,
                self.manifest_path, None)

    def test_request_cannot_supply_detector_or_candidate_identity(self) -> None:
        with self.assertRaisesRegex(
                AlternateTakeAuthorityError, "request is malformed"):
            self._run({**_request(), "retakeId": 0})

    def test_manifest_must_bind_the_prepared_source(self) -> None:
        self._write_manifest("caller-substitution")
        with self.assertRaisesRegex(
                AlternateTakeAuthorityError, "prepared source authority"):
            self._run()

    def test_no_matching_released_event_blocks(self) -> None:
        with mock.patch(
                "edit.alternate_take_derivation.released_retake_ids",
                return_value=[]):
            with self.assertRaisesRegex(
                    AlternateTakeAuthorityError, "one released later take"):
                self._run()

    def test_two_operation_matching_events_block_as_ambiguous(self) -> None:
        with mock.patch(
                "edit.alternate_take_derivation.released_retake_ids",
                return_value=[0, 0]):
            with self.assertRaisesRegex(
                    AlternateTakeAuthorityError, "one released later take"):
                self._run()

    def test_replay_is_exact_and_changed_region_conflicts(self) -> None:
        first = self._run()
        self.assertEqual(first, self._run())
        changed = {**_REGION, "xPpm": 200_000}
        with self.assertRaisesRegex(
                AlternateTakeAuthorityError, "publication failed closed"):
            self._run(_request(changed))

    def test_audio_only_is_not_applicable_and_rejects_visual_input(self) -> None:
        fixture = CandidateQcFixture()
        try:
            result = run(
                fixture.producer, fixture.preparation_hash,
                "/manifest/not-needed.json", None)
            self.assertEqual(result["status"], "not-applicable-audio-only")
            with self.assertRaisesRegex(
                    AlternateTakeAuthorityError, "audio-only"):
                run(
                    fixture.producer, fixture.preparation_hash,
                    "/manifest/not-needed.json", _request())
        finally:
            fixture.clean()


if __name__ == "__main__":
    unittest.main(verbosity=2)
