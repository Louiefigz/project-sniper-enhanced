"""Separate immutable historical evidence from current source inventory checks."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from current_system_inventory_check import validate_inventory


class CurrentSystemInventoryRevisionTests(unittest.TestCase):
    """Verify historical identity and the dated current source audit."""

    def test_historical_inventory_evidence_is_immutable(self) -> None:
        """Retain original receipts without treating them as current qualification."""
        repo = Path(__file__).resolve().parents[3]
        contracts = repo / "docs/producer/command-driven-editing/contracts"
        expected = {
            "current-system-inventory-v1.json":
                "38c0f81c2bd8c62c53b3815b710d3ea80a3d2db2762d9056b15910cb9792d0a5",
            "p0-authority-path-boundary-evidence-v1.json":
                "f23c02abd971950287a1a37af5d4c8b96eebd6b5d1de13c5252ba2435861fa54",
            "p0-persistence-call-dispositions-v1.json":
                "6ebe9bab8f45c82d5d28ad49ee2657b599fc3870e485af310d9c99ddf82f7bf4",
            "p0-current-short-baseline-v1.json":
                "39801b7b4eed0ee6a4a0f0cf070f8906a5e096a7ccb876c317f6666bedd03245",
            "p0-current-lf14-baseline-v1.json":
                "0fa4eccbea33ee04593876b34ad37da1efbf6842917394e6c26475fda5929f2e",
        }
        for name, digest in expected.items():
            with self.subTest(name=name):
                self.assertEqual(
                    hashlib.sha256((contracts / name).read_bytes()).hexdigest(),
                    digest,
                )

    def test_current_repository_inventory_records_pending_qualification(self) -> None:
        """Audit current source while keeping unmeasured baseline status explicit."""
        repo = Path(__file__).resolve().parents[3]
        path = (repo / "docs/producer/command-driven-editing/contracts/"
                "current-system-inventory-2026-09-22.json")
        inventory = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(inventory["phaseExit"], "blocked")
        self.assertEqual(inventory["baseline"]["status"], "required-unmeasured")
        self.assertEqual(inventory["baseline"]["evidencePaths"], [])
        result = validate_inventory(repo, path)
        self.assertEqual(result["baselineEvidence"], 0)
        self.assertTrue(result["ok"])
        if result["discoveryBacklog"] or result["persistenceDispositions"]["blockingSites"]:
            self.assertEqual(inventory["completeness"], "partial")
            self.assertTrue(inventory["inventoryGaps"])


if __name__ == "__main__":
    unittest.main()
