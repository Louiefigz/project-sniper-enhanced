from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from collections.abc import Callable
from pathlib import Path

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from _approved_parent_loader_values import canonical  # noqa: E402
from _quality_evidence_fixture import quality_evidence_fixture  # noqa: E402
from headless.approved_parent_quality_evidence import (  # noqa: E402
    QualityEvidenceSchemaError,
    parse_audit_b_receipt_v1,
    parse_effect_proof_v1,
    parse_full_decode_proof_v1,
    validate_approved_parent_quality_evidence_v1,
    validate_audit_b_receipt_v1,
    validate_effect_proof_v1,
    validate_full_decode_proof_v1,
)


class _AlwaysEqual:
    def __eq__(self, value: object) -> bool:
        return True


def _decoded(raw: bytes) -> dict:
    return json.loads(raw)


def _changed(raw: bytes, callback: Callable[[dict], None]) -> bytes:
    document = _decoded(raw)
    callback(document)
    return canonical(document)


class QualityEvidenceParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = quality_evidence_fixture().binding.evidence

    def test_all_exact_evidence_parses_and_revalidates(self) -> None:
        validate_full_decode_proof_v1(self.evidence.full_decode)
        validate_effect_proof_v1(self.evidence.effect_proof)
        validate_audit_b_receipt_v1(self.evidence.audit)
        validate_approved_parent_quality_evidence_v1(self.evidence)

    def test_full_decode_requires_complete_video_audio_and_packets(self) -> None:
        raw = self.evidence.full_decode.document_json
        cases = (
            _changed(raw, lambda row: row["streams"].update(decodedAudio=0)),
            _changed(raw, lambda row: row["video"].update(decodedFrames=119)),
            _changed(raw, lambda row: row["video"].update(decodedPackets=119)),
            _changed(raw, lambda row: row["audio"].update(decodedPackets=187)),
            _changed(
                raw,
                lambda row: row["audio"].update(decodedSamplesPerChannel=191_999),
            ),
            _changed(raw, lambda row: row["execution"].update(exitCode=1)),
            _changed(raw, lambda row: row["execution"].update(exitCode=False)),
            _changed(raw, lambda row: row.update(method="ffprobe-packets-only")),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                QualityEvidenceSchemaError
            ):
                parse_full_decode_proof_v1(value)

    def test_full_decode_rejects_unknown_missing_and_wrong_exact_types(self) -> None:
        raw = self.evidence.full_decode.document_json
        cases = (
            _changed(raw, lambda row: row.update(legacy=True)),
            _changed(raw, lambda row: row.pop("assemblyReceipt")),
            _changed(raw, lambda row: row["streams"].update(expectedAudio=True)),
            _changed(raw, lambda row: row["audio"].update(channels=0)),
            _changed(raw, lambda row: row.update(schemaVersion=True)),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                QualityEvidenceSchemaError
            ):
                parse_full_decode_proof_v1(value)

    def test_effect_proof_rejects_tolerance_and_coverage_widening(self) -> None:
        raw = self.evidence.effect_proof.document_json
        cases = (
            _changed(raw, lambda row: row["decodedColor"].update(maximumDeltaEMilli=5_001)),
            _changed(raw, lambda row: row["decodedColor"].update(observedRgb=[0, 0, 0])),
            _changed(raw, lambda row: row["decodedColor"].update(matchingFrames=74)),
            _changed(raw, lambda row: row["timing"].update(boundaryToleranceFrames=2)),
            _changed(raw, lambda row: row["timing"].update(sampledFrames=74)),
            _changed(raw, lambda row: row["placement"].update(maxOriginErrorPixels=2)),
            _changed(raw, lambda row: row["contrast"].update(requiredMinimumMilliRatio=2_999)),
            _changed(raw, lambda row: row["contrast"].update(passingFrames=74)),
            _changed(raw, lambda row: row["protectedRegions"].update(collisionFrames=1)),
            _changed(raw, lambda row: row["locality"].update(preencodeOutsideRoiChangedPixels=1)),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                QualityEvidenceSchemaError
            ):
                parse_effect_proof_v1(value)

    def test_effect_proof_rejects_invalid_target_and_nested_shape(self) -> None:
        raw = self.evidence.effect_proof.document_json
        cases = (
            _changed(raw, lambda row: row["target"].update(requestedValue="#054bc9")),
            _changed(raw, lambda row: row["target"].update(brandMembership="unknown")),
            _changed(raw, lambda row: row["preEncode"].update(rasterRgb=[5, 75, True])),
            _changed(raw, lambda row: row["protectedRegions"].update(regionKinds=["title", "caption"])),
            _changed(raw, lambda row: row["placement"].update(method="declared-only")),
            _changed(raw, lambda row: row["locality"].update(extra=True)),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                QualityEvidenceSchemaError
            ):
                parse_effect_proof_v1(value)

    def test_audit_is_terminal_and_requires_all_normalized_domains(self) -> None:
        raw = self.evidence.audit.document_json
        cases = (
            _changed(raw, lambda row: row.update(terminalStage="before-decode")),
            _changed(raw, lambda row: row["domains"].pop()),
            _changed(raw, lambda row: row["domains"][0].update(name="legacy")),
            _changed(raw, lambda row: row["domains"][0].update(warningCount=1)),
            _changed(raw, lambda row: row["summary"].update(failed=1)),
            _changed(raw, lambda row: row["summary"].update(checkCount=7)),
            _changed(raw, lambda row: row["evidence"].update(evidenceSetDigest="0" * 64)),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                QualityEvidenceSchemaError
            ):
                parse_audit_b_receipt_v1(value)

    def test_evidence_artifact_roles_cannot_alias_paths_or_bytes(self) -> None:
        raw = self.evidence.effect_proof.document_json

        def alias_path(row: dict) -> None:
            row["final"] = {**row["final"], "path": row["plan"]["path"]}

        def alias_bytes(row: dict) -> None:
            row["final"] = {**row["final"], "sha256": row["plan"]["sha256"]}

        for value in (_changed(raw, alias_path), _changed(raw, alias_bytes)):
            with self.subTest(value=value), self.assertRaisesRegex(
                QualityEvidenceSchemaError, "alias"
            ):
                parse_effect_proof_v1(value)

    def test_all_parsers_require_exact_canonical_bytes(self) -> None:
        cases = (
            (parse_full_decode_proof_v1, self.evidence.full_decode.document_json, b"120"),
            (parse_effect_proof_v1, self.evidence.effect_proof.document_json, b"75"),
            (parse_audit_b_receipt_v1, self.evidence.audit.document_json, b"8"),
        )
        for parser, raw, numeric in cases:
            self._assert_invalid_encodings(parser, raw, numeric)

    def _assert_invalid_encodings(
        self, parser: Callable[[object], object], raw: bytes, numeric: bytes
    ) -> None:
        duplicate = b'{"schemaVersion":1,' + raw[1:]
        nonfinite = raw.replace(numeric, b"NaN", 1)
        for invalid in (_decoded(raw), raw + b"\n", duplicate, nonfinite):
            with self.subTest(invalid=invalid), self.assertRaises(
                QualityEvidenceSchemaError
            ):
                parser(invalid)

    def test_direct_construction_and_hostile_equality_cannot_forge(self) -> None:
        cases = (
            (
                dataclasses.replace(self.evidence.full_decode, approved_plan_digest=_AlwaysEqual()),
                validate_full_decode_proof_v1,
            ),
            (
                dataclasses.replace(self.evidence.effect_proof, quality_policy_id=_AlwaysEqual()),
                validate_effect_proof_v1,
            ),
            (
                dataclasses.replace(self.evidence.audit, evidence_set_digest=_AlwaysEqual()),
                validate_audit_b_receipt_v1,
            ),
        )
        for forged, validator in cases:
            with self.subTest(value=type(forged).__name__), self.assertRaises(
                QualityEvidenceSchemaError
            ):
                validator(forged)


if __name__ == "__main__":
    unittest.main()
