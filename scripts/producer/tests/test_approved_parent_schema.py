from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from headless.approved_parent_schema import (  # noqa: E402
    ApprovedParentDescriptorV1,
    ApprovedParentSchemaError,
    ArtifactRefV1,
    GraphicAssetRefV1,
    MediaRefV1,
    parse_approved_parent_descriptor,
    validate_approved_parent_descriptor,
)
from _approved_parent_schema_fixture import (  # noqa: E402
    ATTEMPT,
    _artifact,
    _canonical,
    _descriptor,
)


class ApprovedParentSchemaTests(unittest.TestCase):
    def test_exact_nested_card_parses_and_revalidates(self) -> None:
        document = _descriptor()
        parsed = parse_approved_parent_descriptor(_canonical(document))
        validate_approved_parent_descriptor(parsed)
        self.assertIs(type(parsed), ApprovedParentDescriptorV1)
        self.assertEqual(parsed.status, "approved-private-generation")
        self.assertEqual(parsed.realization_kind, "deterministic-mp4")
        self.assertIs(type(parsed.plan.artifact), ArtifactRefV1)
        self.assertIs(type(parsed.base.media), MediaRefV1)
        self.assertIs(type(parsed.graphics.assets[0]), GraphicAssetRefV1)
        self.assertEqual(parsed.identity.attempt_id, ATTEMPT)
        self.assertEqual(parse_approved_parent_descriptor(document), parsed)

    def test_publication_verification_and_self_reference_are_excluded(self) -> None:
        cases = []
        for key, value in (("commitDigest", "a" * 64), ("publicationSeq", 1)):
            changed = _descriptor()
            changed[key] = value
            cases.append(changed)
        verification = _descriptor()
        verification["quality"]["generationVerification"] = _artifact(
            "generation-verification.json", "a"
        )
        cases.append(verification)
        self_ref = _descriptor()
        self_ref["provenance"]["approvedParentDescriptor"] = _artifact(
            "approved-parent.json", "b"
        )
        cases.append(self_ref)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                ApprovedParentSchemaError
            ):
                parse_approved_parent_descriptor(value)

    def test_fixed_envelope_and_exact_top_keys_reject(self) -> None:
        cases = []
        for key, value in (
            ("schemaVersion", True),
            ("status", "approved"),
            ("realizationKind", "gui"),
        ):
            changed = _descriptor()
            changed[key] = value
            cases.append(changed)
        missing = _descriptor()
        missing.pop("base")
        cases.append(missing)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                ApprovedParentSchemaError
            ):
                parse_approved_parent_descriptor(value)

    def test_identity_is_exact_and_canonical(self) -> None:
        cases = []
        for key, value in (
            ("authorityId", "bad authority"),
            ("generationId", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
            ("attemptId", "bad"),
            ("unitId", None),
            ("requestDigest", "A" * 64),
        ):
            changed = _descriptor()
            changed["identity"][key] = value
            cases.append(changed)
        extra = _descriptor()
        extra["identity"]["publicationSeq"] = 1
        cases.append(extra)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                ApprovedParentSchemaError
            ):
                parse_approved_parent_descriptor(value)

    def test_all_policy_ids_are_exact_lowercase_digests(self) -> None:
        for key in tuple(_descriptor()["policies"]):
            changed = _descriptor()
            changed["policies"][key] = "A" * 64
            with self.subTest(key=key), self.assertRaises(ApprovedParentSchemaError):
                parse_approved_parent_descriptor(changed)
        extra = _descriptor()
        extra["policies"]["legacyPolicyId"] = "0" * 64
        with self.assertRaises(ApprovedParentSchemaError):
            parse_approved_parent_descriptor(extra)

    def test_provenance_is_complete_exact_and_typed(self) -> None:
        parsed = parse_approved_parent_descriptor(_descriptor())
        self.assertEqual(
            parsed.provenance.base_fingerprint.relative_path,
            "provenance/baseFingerprint.json",
        )
        missing = _descriptor()
        missing["provenance"].pop("cutApproval")
        legacy = _descriptor()
        legacy["provenance"]["sourceFingerprint"] = legacy["provenance"].pop(
            "baseFingerprint"
        )
        extra = _descriptor()
        extra["provenance"]["legacyState"] = _artifact("legacy.json", "a")
        invalid = _descriptor()
        invalid["provenance"]["repairState"] = "repair-state.json"
        escaped = _descriptor()
        escaped["provenance"]["operatorIntent"]["path"] = "../intent.json"
        for value in (missing, legacy, extra, invalid, escaped):
            with self.subTest(value=value), self.assertRaises(
                ApprovedParentSchemaError
            ):
                parse_approved_parent_descriptor(value)

    def test_nested_cards_and_proxy_disposition_are_closed(self) -> None:
        cases = []
        for section in ("plan", "base", "graphics", "output", "quality"):
            changed = _descriptor()
            changed[section]["legacy"] = True
            cases.append(changed)
        proxy = _descriptor()
        proxy["output"]["proxyDisposition"] = "generated"
        cases.append(proxy)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                ApprovedParentSchemaError
            ):
                parse_approved_parent_descriptor(value)

    def test_canonical_duplicate_and_nonfinite_bytes_reject(self) -> None:
        raw = _canonical(_descriptor())
        with self.assertRaisesRegex(ApprovedParentSchemaError, "canonical"):
            parse_approved_parent_descriptor(raw + b"\n")
        duplicate = raw.replace(b'{"base":', b'{"schemaVersion":1,"base":', 1)
        with self.assertRaisesRegex(ApprovedParentSchemaError, "duplicate"):
            parse_approved_parent_descriptor(duplicate)
        nonfinite = raw.replace(b'"durationSeconds":4.0', b'"durationSeconds":NaN')
        with self.assertRaisesRegex(ApprovedParentSchemaError, "invalid JSON"):
            parse_approved_parent_descriptor(nonfinite)

    def test_ordered_graphics_and_critics_are_exact(self) -> None:
        duplicate = _descriptor()
        duplicate["graphics"]["assets"][1]["graphicId"] = "g-00000001"
        critics = _descriptor()
        critics["quality"]["critics"].reverse()
        missing = _descriptor()
        missing["quality"]["critics"].pop()
        for value in (duplicate, critics, missing):
            with self.subTest(value=value), self.assertRaises(
                ApprovedParentSchemaError
            ):
                parse_approved_parent_descriptor(value)

    def test_referenced_paths_are_globally_unique(self) -> None:
        changed = _descriptor()
        changed["quality"]["finalApproval"]["path"] = "base/receipt.json"
        with self.assertRaisesRegex(ApprovedParentSchemaError, "alias"):
            parse_approved_parent_descriptor(changed)

    def test_media_facts_are_bound_to_exact_artifact(self) -> None:
        changed = _descriptor()
        changed["output"]["final"]["facts"]["sizeBytes"] = 99
        with self.assertRaises(ApprovedParentSchemaError):
            parse_approved_parent_descriptor(changed)

    def test_direct_construction_cannot_bypass_canonical_card(self) -> None:
        parsed = parse_approved_parent_descriptor(_descriptor())
        policies = dataclasses.replace(parsed.policies, repair_policy_id="0" * 64)
        forged = dataclasses.replace(parsed, policies=policies)
        with self.assertRaisesRegex(ApprovedParentSchemaError, "identity"):
            validate_approved_parent_descriptor(forged)
        provenance = dataclasses.replace(
            parsed.provenance,
            cut_approval=parsed.provenance.operator_intent,
        )
        forged = dataclasses.replace(parsed, provenance=provenance)
        with self.assertRaisesRegex(ApprovedParentSchemaError, "identity"):
            validate_approved_parent_descriptor(forged)


if __name__ == "__main__":
    unittest.main()
