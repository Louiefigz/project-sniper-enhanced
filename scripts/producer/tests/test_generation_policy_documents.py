from __future__ import annotations

import hashlib
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from headless.generation_policy_documents import (  # noqa: E402
    EXECUTION_POLICY_CLASS,
    FALLBACK_POLICY_CLASS,
    GENERATION_POLICY_CLASSES,
    QUALITY_POLICY_CLASS,
    REPAIR_POLICY_CLASS,
    GenerationPolicyDocumentError,
    current_execution_policy,
    current_fallback_policy,
    decode_execution_policy,
    decode_fallback_policy,
    validate_generation_policy_documents,
)
from headless.generation_schema import parse_generation_commit  # noqa: E402
from headless.quality_policy import (  # noqa: E402
    current_deterministic_quality_policy,
)
from headless.repair_intent import current_accent_policy  # noqa: E402


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")


def _repair_bytes() -> bytes:
    return _canonical(
        {
            "schemaVersion": 1,
            "effectClass": "SECTION_MARKER_ACCENT_V1",
            "allowedValues": list(current_accent_policy().allowed_values),
        }
    )


def _artifacts() -> dict[str, bytes]:
    return {
        EXECUTION_POLICY_CLASS: current_execution_policy().document_json,
        REPAIR_POLICY_CLASS: _repair_bytes(),
        QUALITY_POLICY_CLASS: current_deterministic_quality_policy().document_json,
        FALLBACK_POLICY_CLASS: current_fallback_policy().document_json,
    }


def _commit_document() -> dict:
    return {
        "schemaVersion": 1,
        "authorityId": "authority-mp4-v1",
        "generationId": "11111111-1111-4111-8111-111111111111",
        "attemptId": "22222222-2222-4222-8222-222222222222",
        "unitId": "33333333-3333-4333-8333-333333333333",
        "requestDigest": "1" * 64,
        "expectedParent": None,
        "executionPolicyId": current_execution_policy().policy_id,
        "repairPolicyId": current_accent_policy().policy_id,
        "qualityPolicyId": current_deterministic_quality_policy().policy_id,
        "fallbackPolicyId": current_fallback_policy().policy_id,
        "approvedParentPath": "authority/approved-parent.json",
        "files": [
            {
                "artifactClass": "approved-parent-v1",
                "path": "authority/approved-parent.json",
                "sizeBytes": 1,
                "sha256": "a" * 64,
            }
        ],
    }


def _commit():
    return parse_generation_commit(_commit_document())


def _changed(raw: bytes, section: str, key: str, value: object) -> bytes:
    document = json.loads(raw)
    document[section][key] = value
    return _canonical(document)


class GenerationPolicyDocumentTests(unittest.TestCase):
    def test_current_documents_bind_to_exact_commit_ids(self) -> None:
        result = validate_generation_policy_documents(_commit(), _artifacts())
        self.assertIs(result.execution, current_execution_policy())
        self.assertEqual(result.repair, current_accent_policy())
        self.assertEqual(result.quality, current_deterministic_quality_policy())
        self.assertIs(result.fallback, current_fallback_policy())

    def test_execution_policy_closes_non_gui_mp4_route(self) -> None:
        policy = current_execution_policy()
        document = policy.decoded_document()
        self.assertEqual(document["executionPath"]["kind"], "code-agent-only")
        self.assertFalse(document["executionPath"]["guiAllowed"])
        self.assertFalse(document["executionPath"]["palmierAllowed"])
        self.assertFalse(document["realization"]["writerRebuildAllowed"])
        self.assertFalse(document["realization"]["baseRebuildAllowed"])
        self.assertEqual(document["realization"]["kind"], "deterministic-mp4")
        self.assertEqual(document["compositor"]["kind"], "prebound-compositor")
        self.assertEqual(document["compositor"]["eofAction"], "pass")
        self.assertEqual(document["compositor"]["audioDisposition"], "copy")
        self.assertEqual(
            document["compositor"]["proxyDisposition"], "omitted-by-policy"
        )
        self.assertFalse(document["publication"]["allowed"])

    def test_execution_and_fallback_ids_are_domain_separated(self) -> None:
        execution = current_execution_policy()
        fallback = current_fallback_policy()
        self.assertEqual(
            execution.policy_id,
            hashlib.sha256(
                b"sniper-execution-policy-v1\0" + execution.document_json
            ).hexdigest(),
        )
        self.assertEqual(
            fallback.policy_id,
            hashlib.sha256(
                b"sniper-fallback-policy-v1\0" + fallback.document_json
            ).hexdigest(),
        )
        self.assertNotEqual(execution.policy_id, fallback.policy_id)

    def test_execution_policy_rejects_every_alternate_route(self) -> None:
        raw = current_execution_policy().document_json
        changes = (
            ("executionPath", "kind", "gui"),
            ("executionPath", "guiAllowed", True),
            ("executionPath", "palmierAllowed", True),
            ("realization", "writerRebuildAllowed", True),
            ("realization", "baseRebuildAllowed", True),
            ("realization", "fallbackPolicy", "best-effort"),
            ("compositor", "eofAction", "repeat"),
            ("compositor", "audioDisposition", "encode"),
            ("compositor", "proxyDisposition", "generated"),
            ("publication", "allowed", True),
        )
        for section, key, value in changes:
            with self.subTest(section=section, key=key):
                with self.assertRaisesRegex(
                    GenerationPolicyDocumentError, "not current"
                ):
                    decode_execution_policy(_changed(raw, section, key, value))

    def test_fallback_policy_is_exact_none_and_nonpublishing(self) -> None:
        policy = current_fallback_policy()
        self.assertEqual(
            policy.decoded_document(),
            {
                "schemaVersion": 1,
                "fallbackPolicy": "none",
                "alternateRealizationAllowed": False,
                "publicationAllowed": False,
            },
        )
        for key, value in (
            ("fallbackPolicy", "semantic"),
            ("alternateRealizationAllowed", True),
            ("publicationAllowed", True),
        ):
            document = policy.decoded_document()
            document[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(
                GenerationPolicyDocumentError, "not current"
            ):
                decode_fallback_policy(_canonical(document))

    def test_repair_policy_must_be_exact_current_derived_catalog(self) -> None:
        cases = []
        wrong_effect = json.loads(_repair_bytes())
        wrong_effect["effectClass"] = "OTHER_EFFECT"
        cases.append(wrong_effect)
        extra_value = json.loads(_repair_bytes())
        extra_value["allowedValues"].append("#FFFFFF")
        cases.append(extra_value)
        reversed_values = json.loads(_repair_bytes())
        reversed_values["allowedValues"].reverse()
        cases.append(reversed_values)
        for document in cases:
            artifacts = _artifacts()
            artifacts[REPAIR_POLICY_CLASS] = _canonical(document)
            with self.subTest(document=document), self.assertRaisesRegex(
                GenerationPolicyDocumentError, "repair policy is not current"
            ):
                validate_generation_policy_documents(_commit(), artifacts)

    def test_quality_policy_must_decode_as_exact_current_policy(self) -> None:
        artifacts = _artifacts()
        document = json.loads(artifacts[QUALITY_POLICY_CLASS])
        document["qualityGates"]["fullDecode"] = False
        artifacts[QUALITY_POLICY_CLASS] = _canonical(document)
        with self.assertRaisesRegex(GenerationPolicyDocumentError, "quality policy"):
            validate_generation_policy_documents(_commit(), artifacts)

    def test_all_four_ids_must_match_commit(self) -> None:
        fields = (
            "executionPolicyId",
            "repairPolicyId",
            "qualityPolicyId",
            "fallbackPolicyId",
        )
        for field in fields:
            document = _commit_document()
            document[field] = "f" * 64
            with self.subTest(field=field), self.assertRaisesRegex(
                GenerationPolicyDocumentError, "IDs do not match"
            ):
                validate_generation_policy_documents(
                    parse_generation_commit(document), _artifacts()
                )

    def test_directly_forged_commit_instance_rejects(self) -> None:
        forged = replace(_commit(), execution_policy_id="f" * 64)
        with self.assertRaisesRegex(GenerationPolicyDocumentError, "wire identity"):
            validate_generation_policy_documents(forged, _artifacts())
        with self.assertRaisesRegex(GenerationPolicyDocumentError, "wire type"):
            validate_generation_policy_documents(object(), _artifacts())

    def test_policy_artifact_mapping_is_an_exact_four_class_closure(self) -> None:
        self.assertEqual(set(_artifacts()), GENERATION_POLICY_CLASSES)
        missing = _artifacts()
        missing.pop(FALLBACK_POLICY_CLASS)
        extra = _artifacts()
        extra["future-policy-v2"] = b"{}"
        for artifacts in (missing, extra, tuple(_artifacts().items())):
            with self.subTest(artifacts=artifacts), self.assertRaisesRegex(
                GenerationPolicyDocumentError, "mapping|closure"
            ):
                validate_generation_policy_documents(_commit(), artifacts)

    def test_policy_documents_require_exact_immutable_canonical_bytes(self) -> None:
        raw = current_execution_policy().document_json
        cases = (
            raw.decode("ascii"),
            raw + b"\n",
            b'{"schemaVersion":NaN}',
            b'{"schemaVersion":1,"schemaVersion":1}',
        )
        for value in cases:
            artifacts = _artifacts()
            artifacts[EXECUTION_POLICY_CLASS] = value
            with self.subTest(value=value), self.assertRaises(
                GenerationPolicyDocumentError
            ):
                validate_generation_policy_documents(_commit(), artifacts)

    def test_current_documents_are_process_stable(self) -> None:
        self.assertIs(current_execution_policy(), current_execution_policy())
        self.assertIs(current_fallback_policy(), current_fallback_policy())


if __name__ == "__main__":
    unittest.main()
