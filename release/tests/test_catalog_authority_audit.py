"""The release audit re-derives the complete registered catalog authority."""
from __future__ import annotations

import unittest
from pathlib import Path

from release.audit_catalog_authority import audit_catalog_authority


class CatalogAuthorityAuditTests(unittest.TestCase):
    """Exercise the archive-facing trust chain against the maintained source."""

    def test_current_tree_resolves_all_372_rows_and_reports_gaps(self) -> None:
        root = Path(__file__).resolve().parents[2]
        findings: list[tuple[bool, str, str]] = []
        audit_catalog_authority(root, lambda ok, name, detail: findings.append(
            (ok, name, detail)))
        self.assertTrue(all(row[0] for row in findings), findings)
        self.assertIn("372 records", " ".join(row[2] for row in findings))
        self.assertIn("known gaps:", " ".join(row[2] for row in findings))


if __name__ == "__main__":
    unittest.main()
