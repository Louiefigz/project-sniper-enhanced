"""Freshness and completeness gate for retained P0 hostile-byte evidence."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from headless.native_media_runtime import POLICY as JAIL_POLICY
from live_p0_adversarial_ingress_acceptance import CASES, CLOSURE

REPO = Path(__file__).parents[3]
ARTIFACT = REPO / (
    "docs/producer/command-driven-editing/contracts/"
    "p0-adversarial-ingress-v1.json")
ERROR_PATTERNS = {
    "malformed-codec": r"(Decoder .* not found|no decoder found)",
    "huge-dimensions": r"DIMENSION_LIMIT",
    "huge-frame-count": r"FRAME_LIMIT",
    "truncated-stream": r"(moov atom not found|Invalid data)",
    "decoder-timeout": r"DECODE_TIMEOUT",
    "archive-bomb": r"manifest closure is invalid",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class P0AdversarialIngressArtifactTests(unittest.TestCase):
    def test_retained_cohort_is_complete_fresh_and_fail_closed(self) -> None:
        value = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(
            set(value),
            {
                "schemaVersion", "kind", "generatedAt", "nativeRuntime",
                "sourceClosure", "cases", "passed",
            },
        )
        self.assertEqual(value["schemaVersion"], 2)
        self.assertEqual(value["nativeRuntime"]["policy"], JAIL_POLICY)  # regenerate the cohort when the jail changes
        self.assertEqual(
            value["kind"], "p0-adversarial-ingress-acceptance")
        self.assertTrue(value["passed"])
        self.assertEqual(
            value["sourceClosure"],
            {name: _sha(REPO / name) for name in CLOSURE},
        )
        rows = value["cases"]
        self.assertEqual(
            [row["caseId"] for row in rows], list(CASES))
        for row in rows:
            with self.subTest(case=row["caseId"]):
                self.assertEqual(
                    set(row),
                    {
                        "caseId", "inputSha256", "status", "error",
                        "admissionReceiptPublished",
                        "processCleanupProved",
                    },
                )
                self.assertEqual(row["status"], "rejected")
                self.assertRegex(row["inputSha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(row["error"])
                self.assertRegex(
                    row["error"], ERROR_PATTERNS[row["caseId"]])
                self.assertFalse(row["admissionReceiptPublished"])
                self.assertTrue(row["processCleanupProved"])


if __name__ == "__main__":
    unittest.main()
