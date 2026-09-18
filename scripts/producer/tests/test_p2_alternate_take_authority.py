"""Alternate-take selection is deterministic and mandatory before QC."""
from __future__ import annotations

import copy
import json
import os
import unittest
from unittest import mock

from contracts.schema_validator import (
    SchemaValidationError,
    validate_document,
)
from edit.alternate_take_authority import (
    publish_alternate_take_selection,
)
from edit.alternate_take_candidates import (
    CandidateSetInput,
    build_alternate_take_candidate_set,
)
from edit.alternate_take_selection import (
    AlternateTakeDecision,
    released_selection_policy,
    select_candidate,
)
from edit.alternate_take_types import AlternateTakeAuthorityError
from edit.cut_repair_candidate_qc_contract import load_candidate_authority
from edit.cut_repair_context_sources import canonical_bytes, digest
from tests._p2_alternate_take_fixture import AlternateTakeFixture

_SCHEMA = "cut-repair-alternate-take-selection-v1.schema.json"
_REGION = {
    "xPpm": 250_000, "yPpm": 420_000,
    "widthPpm": 500_000, "heightPpm": 300_000,
}


class AlternateTakeAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = AlternateTakeFixture()

    def tearDown(self) -> None:
        self.fixture.clean()

    def _decision(
        self,
        candidate_id: str | None = None,
        region: dict | None = None,
    ) -> AlternateTakeDecision:
        return AlternateTakeDecision(
            candidate_id or self.fixture.selected["candidateId"],
            released_selection_policy(), region or _REGION)

    def _publish(self) -> tuple[dict, str, str]:
        return publish_alternate_take_selection(
            self.fixture.producer, self.fixture.preparation_hash,
            self.fixture.candidate_set, self._decision())

    def _drifted_detector_closure(self) -> dict:
        drifted = copy.deepcopy(
            self.fixture.candidate_set["detectorToolClosure"])
        drifted["files"][0]["sha256"] = "0" * 64
        core = {key: value for key, value in drifted.items()
                if key != "closureHash"}
        return {**core, "closureHash": digest(core)}

    def test_closed_set_derives_ids_and_inserted_window(self) -> None:
        first = self.fixture.candidate_set
        second = build_alternate_take_candidate_set(CandidateSetInput(
            self.fixture.context, self.fixture.operation,
            self.fixture.transcript_path, 0))
        self.assertEqual(first, second)
        self.assertEqual(
            {row["role"] for row in first["candidates"]},
            {"earlier", "later"})
        for row in first["candidates"]:
            self.assertRegex(row["candidateId"], r"^take-[0-9a-f]{24}$")
            self.assertEqual(row["outputFrameRange"], {
                "firstFrame": 72, "endFrameExclusive": 90})
        self.assertNotEqual(
            self.fixture.selected["outputFrameRange"],
            {"firstFrame": 88, "endFrameExclusive": 110})
        closure = first["detectorToolClosure"]
        self.assertEqual(
            closure["scope"],
            "transitive-repository-choice-derivation-rapidfuzz-"
            "python-executable-not-os-stdlib-dylibs")
        self.assertEqual(
            {row["role"] for row in closure["files"]},
            {
                "closure-controller", "detector-authority-adapter",
                "candidate-range-authority", "operation-binding-derivation",
                "released-selection-policy", "alternate-take-value-types",
                "candidate-qc-value-types", "context-authority",
                "cross-runtime-canonical-json",
                "exact-timing", "target-word-authority", "repair-impact",
                "repair-ranges", "non-ripple-contracts",
                "detector-entrypoint", "detector-config",
                "transcript-policy-helper", "pause-scan-import",
                "python-runtime", "rapidfuzz-package", "rapidfuzz-dispatch",
                "rapidfuzz-implementation",
            })

    def test_receipt_is_required_then_attached_before_qc(self) -> None:
        with self.assertRaisesRegex(
                AlternateTakeAuthorityError, "missing|unreadable"):
            load_candidate_authority(
                self.fixture.producer, self.fixture.preparation_hash)
        receipt, receipt_hash, path = self._publish()
        authority = load_candidate_authority(
            self.fixture.producer, self.fixture.preparation_hash)
        self.assertEqual(authority.alternate_take_selection, receipt)
        self.assertEqual(
            authority.alternate_take_selection_hash, receipt_hash)
        self.assertEqual(authority.alternate_take_selection_path, path)
        self.assertEqual(
            receipt["sourceSampleRange"],
            {**self.fixture.operation["sourceExtension"],
             "sampleRate": 48_000})
        validate_document(_SCHEMA, receipt)

    def test_replay_is_byte_and_hash_deterministic(self) -> None:
        first = self._publish()
        second = self._publish()
        self.assertEqual(first, second)
        with open(first[2], "rb") as stream:
            self.assertEqual(stream.read(), canonical_bytes(first[0]))

    def test_wrong_explicit_id_and_policy_fail_closed(self) -> None:
        with self.assertRaisesRegex(
                AlternateTakeAuthorityError, "violates released policy"):
            publish_alternate_take_selection(
                self.fixture.producer, self.fixture.preparation_hash,
                self.fixture.candidate_set,
                self._decision("take-" + "0" * 24))
        policy = {**released_selection_policy(), "strategy": "caller-choice"}
        with self.assertRaisesRegex(
                AlternateTakeAuthorityError, "not released"):
            publish_alternate_take_selection(
                self.fixture.producer, self.fixture.preparation_hash,
                self.fixture.candidate_set,
                AlternateTakeDecision(
                    self.fixture.selected["candidateId"], policy, _REGION))

    def test_ambiguous_and_tampered_candidate_sets_fail_closed(self) -> None:
        ambiguous = copy.deepcopy(self.fixture.candidate_set)
        for row in ambiguous["candidates"]:
            row["role"] = "later"
        with self.assertRaisesRegex(
                AlternateTakeAuthorityError, "ambiguous"):
            select_candidate(ambiguous, self._decision())
        tampered = copy.deepcopy(self.fixture.candidate_set)
        tampered["candidates"][0]["sourceSampleRange"]["startSample"] += 1
        with self.assertRaisesRegex(
                AlternateTakeAuthorityError, "stale or substituted"):
            publish_alternate_take_selection(
                self.fixture.producer, self.fixture.preparation_hash,
                tampered, self._decision())

    def test_receipt_tamper_is_rejected_on_reopen(self) -> None:
        receipt, _, path = self._publish()
        receipt["operationHash"] = "f" * 64
        with open(path, "wb") as stream:
            stream.write(canonical_bytes(receipt))
        with self.assertRaisesRegex(
                AlternateTakeAuthorityError, "stale|tampered"):
            load_candidate_authority(
                self.fixture.producer, self.fixture.preparation_hash)

    def test_create_once_conflict_rejects_second_roi(self) -> None:
        self._publish()
        changed = {**_REGION, "xPpm": 200_000}
        with self.assertRaisesRegex(
                AlternateTakeAuthorityError, "publication failed closed"):
            publish_alternate_take_selection(
                self.fixture.producer, self.fixture.preparation_hash,
                self.fixture.candidate_set, self._decision(region=changed))

    def test_operator_required_report_is_not_auto_selected(self) -> None:
        report = {
            "retakeDefault": "later", "lookbackUtts": 4, "lookbackS": 60,
            "retakes": [{
                "id": 0, "verdict": "later-wins", "needsOperator": True,
                "longRange": True, "loserIdxs": [0], "winnerIdxs": [1],
                "keepStartS": 2.0,
            }],
        }
        with mock.patch(
                "edit.alternate_take_scan_authority.retake_scan.analyze",
                return_value=report):
            with self.assertRaisesRegex(
                    AlternateTakeAuthorityError, "operator authority"):
                build_alternate_take_candidate_set(CandidateSetInput(
                    self.fixture.context, self.fixture.operation,
                    self.fixture.transcript_path, 0))

    def test_schema_rejects_unknown_fields(self) -> None:
        receipt, _, _ = self._publish()
        receipt["callerCandidateId"] = "invented"
        with self.assertRaises(SchemaValidationError):
            validate_document(_SCHEMA, receipt)

    def test_detector_dependency_drift_is_rejected_on_reobserve(self) -> None:
        with mock.patch(
                "edit.alternate_take_scan_authority.detector_tool_closure",
                return_value=self._drifted_detector_closure()):
            with self.assertRaisesRegex(
                    AlternateTakeAuthorityError, "stale or substituted"):
                publish_alternate_take_selection(
                    self.fixture.producer, self.fixture.preparation_hash,
                    self.fixture.candidate_set, self._decision())

    def test_detector_change_during_scan_fails_closed(self) -> None:
        original = self.fixture.candidate_set["detectorToolClosure"]
        with mock.patch(
                "edit.alternate_take_scan_authority.detector_tool_closure",
                side_effect=[original, self._drifted_detector_closure()]):
            with self.assertRaisesRegex(
                    AlternateTakeAuthorityError, "changed during analysis"):
                build_alternate_take_candidate_set(CandidateSetInput(
                    self.fixture.context, self.fixture.operation,
                    self.fixture.transcript_path, 0))

    def test_terminal_reopen_reobserves_detector_dependency_bytes(self) -> None:
        self._publish()
        with mock.patch(
                "edit.alternate_take_scan_authority.detector_tool_closure",
                return_value=self._drifted_detector_closure()):
            with self.assertRaisesRegex(
                    AlternateTakeAuthorityError, "stale or substituted"):
                load_candidate_authority(
                    self.fixture.producer, self.fixture.preparation_hash)

    def test_transitive_choice_dependency_mutation_changes_closure(self) -> None:
        from edit import alternate_take_detector_closure as closure_module

        original = closure_module.stable_file_digest

        def drift(path: str, role: str) -> str:
            if role == "exact-timing":
                return "0" * 64
            return original(path, role)

        self._publish()
        with mock.patch.object(
                closure_module, "stable_file_digest", side_effect=drift):
            changed = closure_module.detector_tool_closure()
        self.assertNotEqual(
            changed["closureHash"],
            self.fixture.candidate_set["detectorToolClosureHash"])
        with mock.patch(
                "edit.alternate_take_scan_authority.detector_tool_closure",
                return_value=changed):
            with self.assertRaisesRegex(
                    AlternateTakeAuthorityError, "stale or substituted"):
                load_candidate_authority(
                    self.fixture.producer, self.fixture.preparation_hash)

    def test_terminal_reopen_reobserves_transcript_bytes(self) -> None:
        self._publish()
        with open(self.fixture.transcript_path, "ab") as stream:
            stream.write(b"\n")
        with self.assertRaisesRegex(
                AlternateTakeAuthorityError, "timing authority"):
            load_candidate_authority(
                self.fixture.producer, self.fixture.preparation_hash)

    def test_symlinked_receipt_is_rejected(self) -> None:
        _, _, path = self._publish()
        backup = path + ".backup"
        os.rename(path, backup)
        os.symlink(backup, path)
        with self.assertRaisesRegex(
                AlternateTakeAuthorityError, "private regular file"):
            load_candidate_authority(
                self.fixture.producer, self.fixture.preparation_hash)


if __name__ == "__main__":
    unittest.main(verbosity=2)
