from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from _approved_parent_loader_values import canonical  # noqa: E402
from _quality_evidence_fixture import quality_evidence_fixture  # noqa: E402
from headless.approved_parent_quality_evidence_binding import (  # noqa: E402
    ApprovedParentQualityEvidenceBindingError,
    validate_approved_parent_quality_evidence_binding,
)
from headless.artifact_contract import ArtifactRefV1  # noqa: E402
from headless.approved_parent_schema import parse_approved_parent_descriptor  # noqa: E402
from headless.generation_schema import parse_generation_commit  # noqa: E402
from headless.quality_audit_evidence_wire import (  # noqa: E402
    quality_evidence_set_digest,
)


class _AlwaysEqual:
    def __eq__(self, value: object) -> bool:
        return True


def _fake(path: str, marker: str) -> dict:
    return {"path": path, "sha256": marker * 64, "sizeBytes": 50}


class QualityEvidenceBindingTests(unittest.TestCase):
    def test_complete_42_row_generation_cross_binds(self) -> None:
        fixture = quality_evidence_fixture()
        validate_approved_parent_quality_evidence_binding(fixture.binding)

    def test_decode_expected_frame_count_must_equal_final_facts(self) -> None:
        def mutate(stage: str, document: dict) -> None:
            if stage == "full-decode":
                for key in (
                    "expectedFrames",
                    "decodedFrames",
                    "expectedPackets",
                    "decodedPackets",
                ):
                    document["video"][key] = 121

        fixture = quality_evidence_fixture(mutate)
        with self.assertRaisesRegex(
            ApprovedParentQualityEvidenceBindingError, "media coverage"
        ):
            validate_approved_parent_quality_evidence_binding(fixture.binding)

    def test_decode_audio_samples_must_cover_final_duration(self) -> None:
        def mutate(stage: str, document: dict) -> None:
            if stage == "full-decode":
                document["audio"]["expectedSamplesPerChannel"] = 180_000
                document["audio"]["decodedSamplesPerChannel"] = 180_000

        fixture = quality_evidence_fixture(mutate)
        with self.assertRaisesRegex(
            ApprovedParentQualityEvidenceBindingError, "audio duration"
        ):
            validate_approved_parent_quality_evidence_binding(fixture.binding)

    def test_decode_audio_packet_count_cannot_be_self_consistent_but_partial(self) -> None:
        def mutate(stage: str, document: dict) -> None:
            if stage == "full-decode":
                document["audio"]["expectedPackets"] = 1
                document["audio"]["decodedPackets"] = 1

        fixture = quality_evidence_fixture(mutate)
        with self.assertRaisesRegex(
            ApprovedParentQualityEvidenceBindingError, "AAC packet coverage"
        ):
            validate_approved_parent_quality_evidence_binding(fixture.binding)

    def test_effect_requested_value_must_equal_exact_plan_value(self) -> None:
        def mutate(stage: str, document: dict) -> None:
            if stage != "effect-proof":
                return
            document["target"]["requestedValue"] = "#FFD400"
            document["preEncode"]["rasterRgb"] = [255, 212, 0]
            document["decodedColor"].update(
                requestedRgb=[255, 212, 0],
                observedRgb=[255, 212, 0],
                observedDeltaEMilli=0,
            )

        fixture = quality_evidence_fixture(mutate)
        with self.assertRaisesRegex(
            ApprovedParentQualityEvidenceBindingError, "requested effect"
        ):
            validate_approved_parent_quality_evidence_binding(fixture.binding)

    def test_off_brand_color_cannot_self_attest_membership(self) -> None:
        def mutate(stage: str, document: dict) -> None:
            if stage != "effect-proof":
                return
            document["target"]["requestedValue"] = "#123456"
            document["preEncode"]["rasterRgb"] = [18, 52, 86]
            document["decodedColor"].update(
                requestedRgb=[18, 52, 86],
                observedRgb=[18, 52, 86],
                observedDeltaEMilli=0,
            )

        fixture = quality_evidence_fixture(mutate)
        with self.assertRaisesRegex(
            ApprovedParentQualityEvidenceBindingError, "brand binding"
        ):
            validate_approved_parent_quality_evidence_binding(fixture.binding)

    def test_effect_proof_must_bind_the_generation_request(self) -> None:
        def mutate(stage: str, document: dict) -> None:
            if stage == "effect-proof":
                document["requestDigest"] = "7" * 64

        fixture = quality_evidence_fixture(mutate)
        with self.assertRaisesRegex(
            ApprovedParentQualityEvidenceBindingError, "requested effect"
        ):
            validate_approved_parent_quality_evidence_binding(fixture.binding)

    def test_effect_timing_cannot_be_internally_consistent_but_stale(self) -> None:
        def mutate(stage: str, document: dict) -> None:
            if stage != "effect-proof":
                return
            document["timing"].update(
                outStart=1.1,
                expectedFirstFrame=33,
                observedFirstFrame=33,
                sampledFrames=72,
            )
            document["decodedColor"].update(sampledFrames=72, matchingFrames=72)
            document["contrast"].update(sampledFrames=72, passingFrames=72)
            document["protectedRegions"]["sampledFrames"] = 72

        fixture = quality_evidence_fixture(mutate)
        with self.assertRaisesRegex(
            ApprovedParentQualityEvidenceBindingError, "timing differs"
        ):
            validate_approved_parent_quality_evidence_binding(fixture.binding)

    def test_effect_placement_must_equal_plan_and_media_facts(self) -> None:
        def mutate(stage: str, document: dict) -> None:
            if stage == "effect-proof":
                document["placement"].update(expectedX=52, observedX=52)

        fixture = quality_evidence_fixture(mutate)
        with self.assertRaisesRegex(
            ApprovedParentQualityEvidenceBindingError, "placement differs"
        ):
            validate_approved_parent_quality_evidence_binding(fixture.binding)

    def test_final_plan_and_assembly_refs_are_semantically_bound(self) -> None:
        cases = (
            ("full-decode", "final", _fake("wrong/final.mp4", "7")),
            ("effect-proof", "plan", _fake("wrong/plan.json", "8")),
            ("audit-b", "assemblyReceipt", _fake("wrong/assembly.json", "9")),
        )
        for selected_stage, key, replacement in cases:
            def mutate(stage: str, document: dict) -> None:
                if stage == selected_stage:
                    document[key] = replacement

            fixture = quality_evidence_fixture(mutate)
            with self.subTest(stage=selected_stage, key=key), self.assertRaises(
                ApprovedParentQualityEvidenceBindingError
            ):
                validate_approved_parent_quality_evidence_binding(fixture.binding)

    def test_terminal_audit_cannot_reference_stale_independent_evidence(self) -> None:
        def mutate(stage: str, document: dict) -> None:
            if stage != "audit-b":
                return
            stale = _fake("quality/stale-decode.json", "7")
            document["evidence"]["fullDecode"] = stale
            full = ArtifactRefV1(stale["path"], stale["sha256"], stale["sizeBytes"])
            effect = document["evidence"]["effectProof"]
            effect_ref = ArtifactRefV1(
                effect["path"], effect["sha256"], effect["sizeBytes"]
            )
            document["evidence"]["evidenceSetDigest"] = quality_evidence_set_digest(
                full, effect_ref
            )

        fixture = quality_evidence_fixture(mutate)
        with self.assertRaisesRegex(
            ApprovedParentQualityEvidenceBindingError, "evidence refs are stale"
        ):
            validate_approved_parent_quality_evidence_binding(fixture.binding)

    def test_manifest_artifact_classes_cannot_swap_evidence_roles(self) -> None:
        fixture = quality_evidence_fixture()
        binding = fixture.binding
        document = json.loads(binding.commit.document_json)
        full = next(
            row for row in document["files"] if row["artifactClass"] == "full-decode-proof-v1"
        )
        effect = next(
            row for row in document["files"] if row["artifactClass"] == "effect-proof-v1"
        )
        full["artifactClass"], effect["artifactClass"] = (
            effect["artifactClass"],
            full["artifactClass"],
        )
        changed = dataclasses.replace(
            binding, commit=parse_generation_commit(canonical(document))
        )
        with self.assertRaisesRegex(
            ApprovedParentQualityEvidenceBindingError, "artifact role"
        ):
            validate_approved_parent_quality_evidence_binding(changed)

    def test_descriptor_bytes_must_be_the_manifested_authority_card(self) -> None:
        binding = quality_evidence_fixture().binding
        document = json.loads(binding.descriptor.document_json)
        document["base"]["receipt"]["sha256"] = "7" * 64
        changed = dataclasses.replace(
            binding, descriptor=parse_approved_parent_descriptor(canonical(document))
        )
        with self.assertRaisesRegex(
            ApprovedParentQualityEvidenceBindingError, "approved-parent-v1"
        ):
            validate_approved_parent_quality_evidence_binding(changed)

    def test_manifest_same_bytes_under_unrelated_role_rejects(self) -> None:
        fixture = quality_evidence_fixture()
        binding = fixture.binding
        document = json.loads(binding.commit.document_json)
        full = next(
            row for row in document["files"] if row["artifactClass"] == "full-decode-proof-v1"
        )
        unrelated = next(
            row for row in document["files"] if row["artifactClass"] == "admission-inputs-v1"
        )
        unrelated["sha256"] = full["sha256"]
        unrelated["sizeBytes"] = full["sizeBytes"]
        changed = dataclasses.replace(
            binding, commit=parse_generation_commit(canonical(document))
        )
        with self.assertRaisesRegex(
            ApprovedParentQualityEvidenceBindingError, "role bytes alias"
        ):
            validate_approved_parent_quality_evidence_binding(changed)

    def test_forged_direct_instances_and_hostile_equality_reject(self) -> None:
        binding = quality_evidence_fixture().binding
        forged_identity = dataclasses.replace(
            binding.descriptor.identity, request_digest=_AlwaysEqual()
        )
        forged_descriptor = dataclasses.replace(
            binding.descriptor, identity=forged_identity
        )
        forged_qc = dataclasses.replace(binding.qc_receipt, plan_digest=_AlwaysEqual())
        cases = (
            dataclasses.replace(binding, descriptor=forged_descriptor),
            dataclasses.replace(binding, qc_receipt=forged_qc),
            dataclasses.replace(binding, plan_json=binding.plan_json + b"\n"),
        )
        for changed in cases:
            with self.subTest(value=changed), self.assertRaises(
                ApprovedParentQualityEvidenceBindingError
            ):
                validate_approved_parent_quality_evidence_binding(changed)


if __name__ == "__main__":
    unittest.main()
