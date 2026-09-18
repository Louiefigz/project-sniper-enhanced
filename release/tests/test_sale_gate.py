"""Item 10: the sale gate answers for one exact archive from recorded, hash-bound evidence.

Run: .venv/bin/python -m unittest release.tests.test_sale_gate
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from release import sale_gate


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SaleGate(unittest.TestCase):
    """A synthetic archive, evidence folder and matrix per test."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-gate-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.archive = self.base / "project-sniper-x-mac.zip"
        with zipfile.ZipFile(self.archive, "w") as bundle:
            bundle.writestr("project-sniper-x/install/install.command", "#!/bin/bash\necho install\n")
        self.evidence = self.base / "evidence"
        self.evidence.mkdir()
        (self.evidence / "01-run.log").write_text("PASS\n")
        self.archive_sha = sale_gate.file_sha256(self.archive)

    def _row(self, **changes: object) -> dict:
        row = {"id": "R1", "requirement": "installs", "scope": "test", "required": True, "status": "PASS",
               "archive_sha256": self.archive_sha,
               "evidence": [{"path": "01-run.log", "sha256": _sha(b"PASS\n")}],
               "depends_on": [{"path": "archive:project-sniper-x/install/install.command",
                               "sha256": _sha(b"#!/bin/bash\necho install\n")}]}
        row.update(changes)
        return row

    def _gate(self, *rows: dict) -> dict:
        matrix = self.base / "matrix.json"
        matrix.write_text(json.dumps({"schema": "sniper-qualification-matrix-v1", "rows": list(rows)}))
        return sale_gate.evaluate(matrix, self.archive, self.evidence)

    def test_every_required_row_passing_for_this_archive_is_sellable(self) -> None:
        verdict = self._gate(self._row(), self._row(id="OPT", required=False, status="NOT RUN"))
        self.assertTrue(verdict["sellable"], verdict)

    def test_any_status_but_pass_is_not_sellable(self) -> None:
        for status in ("FAIL", "NOT RUN", "BLOCKED"):
            with self.subTest(status):
                verdict = self._gate(self._row(status=status))
                self.assertFalse(verdict["sellable"])
                self.assertIn(f"status {status}", verdict["missing"][0]["problems"])

    def test_evidence_for_another_archive_does_not_count(self) -> None:
        verdict = self._gate(self._row(archive_sha256="0" * 64))
        self.assertFalse(verdict["sellable"])

    def test_changed_or_missing_evidence_does_not_count(self) -> None:
        (self.evidence / "01-run.log").write_text("PASS (edited)\n")
        self.assertFalse(self._gate(self._row())["sellable"])
        (self.evidence / "01-run.log").unlink()
        self.assertIn("01-run.log: missing", self._gate(self._row())["missing"][0]["problems"])

    def test_a_row_without_evidence_does_not_count(self) -> None:
        self.assertFalse(self._gate(self._row(evidence=[]))["sellable"])

    def test_a_dependency_inside_the_archive_must_still_match(self) -> None:
        row = self._row(depends_on=[{"path": "archive:project-sniper-x/install/install.command", "sha256": "0" * 64}])
        verdict = self._gate(row)
        self.assertFalse(verdict["sellable"])
        self.assertIn("sha256 differs", verdict["missing"][0]["problems"][0])

    def test_malformed_matrix_is_an_error_not_a_verdict(self) -> None:
        with self.assertRaises(sale_gate.MatrixError):
            self._gate(self._row(status="PASS-ish"))

    def test_the_seeded_matrix_marks_nothing_pass_and_is_not_sellable(self) -> None:
        rows = sale_gate.load_matrix(sale_gate.MATRIX)
        self.assertTrue(rows)
        self.assertEqual({row["status"] for row in rows} - {"NOT RUN", "BLOCKED"}, set())
        verdict = sale_gate.evaluate(sale_gate.MATRIX, self.archive, self.evidence)
        self.assertFalse(verdict["sellable"])
        self.assertEqual(len(verdict["missing"]), len(rows))


if __name__ == "__main__":
    unittest.main()
