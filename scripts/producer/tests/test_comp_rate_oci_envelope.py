"""Whole OCI receipt corruption and post-audit input race regression tests."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from cut_preview_io import digest, file_hash, write_new
from graphics.comp_rate_oci_artifact import CHECKS, CLAIM, RELEASED_RATES, SCOPE, validate_oci_receipt
from graphics.comp_rate_oci_export import export_receipt
from tests.test_comp_rate_oci_artifact import rows


def envelope() -> dict:
    """Build inert closed data; no synthetic row is exported as real evidence."""
    return {"schemaVersion": 2, "kind": "hyperframes-oci-released-rate-matrix", "runtimeScope": SCOPE,
            "passed": True, "qualityClaim": CLAIM, "sourceDigest": "source", "capabilityDigest": "capability",
            "compositionCount": 1, "rates": list(RELEASED_RATES), "probeFrames": 4, "imageId": "image",
            "renderToolClosure": {"node": "inert"}, "proofTools": {name: {"path": "/inert/" + name, "sha256": "a" * 64}
                                                                      for name in ("ffmpeg", "ffprobe")},
            "executionSources": [], "rawEvidence": {"receiptHash": "b" * 64, "inputsSha256": "c" * 64,
                                                      "auditSources": [], "checks": CHECKS,
                                                      "privateEvidenceRequiredForDeepRevalidation": True},
            "runnerObservation": {"startupCapture": "unavailable", "observedAfterStartSha256": "d" * 64},
            "probes": rows(), "elapsedMs": 100}


def validate(value: dict, expected: str | None = None) -> str:
    """Mock only local current identities; exercise the full receipt shape checks."""
    value["receiptHash"] = digest({key: item for key, item in value.items() if key != "receiptHash"})
    current = envelope()
    with ExitStack() as stack:
        replacements = {"_current_capabilities": {"inert": {"canvas": [16, 16]}}, "current_source_digest": "source",
                        "capability_digest": "capability", "_source_rows": None,
                        "bound_json": {"imageId": "image", "probedClosure": current["renderToolClosure"]}}
        for name, result in replacements.items():
            stack.enter_context(patch("graphics.comp_rate_oci_artifact." + name, return_value=result))
        return validate_oci_receipt(value, expected or value["receiptHash"], current["proofTools"])


class CompRateOciEnvelopeTests(unittest.TestCase):
    def test_closed_compact_header_runtime_sources_pairs_and_claims(self) -> None:
        self.assertEqual(validate(envelope()), "")
        mutations = {
            "unknown": lambda value: value.update(extra=True),
            "schema": lambda value: value.update(schemaVersion=1),
            "scope": lambda value: value.update(runtimeScope="host"),
            "quality": lambda value: value.update(qualityClaim="visually approved"),
            "source": lambda value: value.update(sourceDigest="other"),
            "image": lambda value: value.update(imageId="other"),
            "render-tools": lambda value: value.update(renderToolClosure={"node": "other"}),
            "proof-tools": lambda value: value["proofTools"]["ffmpeg"].update(sha256="e" * 64),
            "pairs": lambda value: value["probes"].__setitem__(-1, value["probes"][0]),
            "deep": lambda value: value["rawEvidence"].update(privateEvidenceRequiredForDeepRevalidation=False),
            "runner": lambda value: value["runnerObservation"].update(startupCapture="captured"),
        }
        for name, mutate in mutations.items():
            changed = copy.deepcopy(envelope())
            mutate(changed)
            with self.subTest(name=name):
                self.assertNotEqual(validate(changed), "")
        self.assertNotEqual(validate(envelope(), "f" * 64), "")

    def test_inputs_changed_after_deep_audit_cannot_be_exported(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            write_new(root / "matrix.json", {"receiptHash": "inert"})
            write_new(root / "inputs.json", {"requests": [{"specHash": "before"}]})
            audited = {"rawReceiptHash": "inert", "rawFileSha256": file_hash(root / "matrix.json"),
                       "inputsFileSha256": file_hash(root / "inputs.json")}

            def changed_after_audit(_root: Path) -> dict:
                (root / "inputs.json").write_text(json.dumps({"requests": [{"specHash": "after"}]}))
                return audited

            with patch("graphics.comp_rate_oci_export.audit", side_effect=changed_after_audit), \
                    patch("graphics.comp_rate_oci_export._audit_sources", return_value=[]), \
                    self.assertRaisesRegex(RuntimeError, "hash changed"):
                export_receipt(root, root / "compact.json")
            self.assertFalse((root / "compact.json").exists())


if __name__ == "__main__":
    unittest.main()
