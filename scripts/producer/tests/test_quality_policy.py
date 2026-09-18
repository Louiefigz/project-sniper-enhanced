"""Closed-policy tests for deterministic private MP4 quality passes."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import unittest

from _common import pl  # noqa: F401
from headless.quality_policy import (
    DeterministicQualityPolicyError,
    DeterministicQualityPolicyV1,
    current_deterministic_quality_policy,
    decode_deterministic_quality_policy,
    parse_deterministic_quality_policy,
    validate_deterministic_quality_policy,
)
from headless.repair_intent import current_accent_policy


def _document() -> dict:
    return current_deterministic_quality_policy().decoded_document()


class DeterministicQualityPolicyTests(unittest.TestCase):
    def test_current_policy_freezes_nonpublishing_lane(self) -> None:
        policy = current_deterministic_quality_policy()
        document = policy.decoded_document()
        self.assertEqual(
            document["realization"],
            {"fallbackPolicy": "none", "kind": "deterministic-mp4"},
        )
        self.assertEqual(
            document["compositor"],
            {
                "audioDisposition": "copy",
                "eofAction": "pass",
                "proxyDisposition": "omitted-by-policy",
            },
        )
        self.assertEqual(
            document["qualityGates"],
            {
                "auditProfile": "B",
                "effectOracle": "SECTION_MARKER_ACCENT_V1",
                "fullDecode": True,
            },
        )
        critics = document["renderedCritics"]
        self.assertEqual(critics, ["composition", "editorial"])
        publication = {
            "allowed": False,
            "candidateDisposition": "private-counterfactual",
        }
        self.assertEqual(
            document["publication"],
            publication,
        )

    def test_current_policy_is_cached_and_domain_separated(self) -> None:
        first = current_deterministic_quality_policy()
        second = current_deterministic_quality_policy()
        expected = hashlib.sha256(
            b"sniper-deterministic-quality-policy-v1\0" + first.document_json
        ).hexdigest()
        self.assertIs(first, second)
        self.assertEqual(first.policy_id, expected)
        self.assertNotEqual(
            first.policy_id, hashlib.sha256(first.document_json).hexdigest()
        )
        self.assertNotEqual(first.policy_id, current_accent_policy().policy_id)

    def test_canonical_bytes_round_trip_without_exposing_mutable_authority(
        self,
    ) -> None:
        policy = current_deterministic_quality_policy()
        self.assertEqual(
            decode_deterministic_quality_policy(policy.document_json), policy
        )
        disposable = policy.decoded_document()
        disposable["publication"]["allowed"] = True
        self.assertFalse(policy.decoded_document()["publication"]["allowed"])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            policy.policy_id = "0" * 64  # type: ignore[misc]

    def test_unknown_root_and_nested_fields_are_rejected(self) -> None:
        current = _document()
        root_extra = _document()
        root_extra["unexpected"] = True
        nested_extra = _document()
        nested_extra["compositor"]["unexpected"] = True
        missing = _document()
        missing["qualityGates"].pop("fullDecode")
        for document in (root_extra, nested_extra, missing):
            with self.subTest(document=document), self.assertRaises(
                DeterministicQualityPolicyError
            ):
                parse_deterministic_quality_policy(document)
        self.assertEqual(
            parse_deterministic_quality_policy(current),
            current_deterministic_quality_policy(),
        )

    def test_policy_values_and_critic_order_are_closed(self) -> None:
        changes = (
            ("realization", "fallbackPolicy", "best-effort"),
            ("compositor", "eofAction", "repeat"),
            ("compositor", "audioDisposition", "replace"),
            ("compositor", "proxyDisposition", "generated"),
            ("qualityGates", "auditProfile", "A"),
            ("qualityGates", "fullDecode", False),
            ("qualityGates", "effectOracle", "generic"),
            ("publication", "allowed", True),
            ("publication", "candidateDisposition", "published"),
        )
        for section, field, replacement in changes:
            document = _document()
            document[section][field] = replacement
            with self.subTest(section=section, field=field), self.assertRaises(
                DeterministicQualityPolicyError
            ):
                parse_deterministic_quality_policy(document)
        for critics in (
            ["editorial", "composition"],
            ["composition"],
            ["composition", "editorial", "style"],
        ):
            document = _document()
            document["renderedCritics"] = critics
            with self.subTest(critics=critics), self.assertRaises(
                DeterministicQualityPolicyError
            ):
                parse_deterministic_quality_policy(document)

    def test_boolean_integer_coercion_is_rejected(self) -> None:
        for section, field, replacement in (
            ("qualityGates", "fullDecode", 1),
            ("publication", "allowed", 0),
        ):
            document = _document()
            document[section][field] = replacement
            with self.subTest(section=section), self.assertRaises(
                DeterministicQualityPolicyError
            ):
                parse_deterministic_quality_policy(document)

    def test_noncanonical_bytes_are_rejected(self) -> None:
        document = current_deterministic_quality_policy().decoded_document()
        variants = (
            json.dumps(document, indent=2, sort_keys=True).encode("ascii"),
            current_deterministic_quality_policy().document_json + b"\n",
            bytearray(current_deterministic_quality_policy().document_json),
        )
        for raw in variants:
            with self.subTest(raw_type=type(raw)), self.assertRaises(
                DeterministicQualityPolicyError
            ):
                decode_deterministic_quality_policy(raw)

    def test_direct_forged_dataclass_cannot_pass_self_validation(self) -> None:
        policy = current_deterministic_quality_policy()
        forged_id = dataclasses.replace(policy, policy_id="0" * 64)
        forged_bytes = DeterministicQualityPolicyV1(
            policy.document_json.replace(b"false", b"true"), policy.policy_id
        )
        forged_id_type = DeterministicQualityPolicyV1(
            policy.document_json, None
        )  # type: ignore[arg-type]
        for forged in (forged_id, forged_bytes, forged_id_type):
            with self.subTest(forged=forged), self.assertRaises(
                DeterministicQualityPolicyError
            ):
                validate_deterministic_quality_policy(forged)
        validate_deterministic_quality_policy(policy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
