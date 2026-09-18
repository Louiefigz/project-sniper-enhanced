#!/usr/bin/env python3
"""Sale-readiness gate: is THIS archive qualified for sale by recorded evidence?

    python -m release.sale_gate --archive <zip> --evidence-root <dir>
                                [--matrix release/qualification/matrix.json]

Separate from the build gate (``release.build_package``), which only decides that
an archive may exist. This reads the qualification matrix and answers
``sellable: true`` only if every required row

* has status ``PASS`` (``FAIL``, ``NOT RUN`` and ``BLOCKED`` never count),
* names this archive's exact SHA-256 in ``archive_sha256``,
* lists at least one evidence file, each present under ``--evidence-root`` with
  the recorded SHA-256, and
* lists the SHA-256 of every file its evidence depends on (``depends_on``), each
  still matching. A path written ``archive:<member>`` is read from inside the
  archive (e.g. ``archive:project-sniper-x/install/install.command``); any other
  path is under ``--evidence-root``.

Otherwise it lists exactly what is missing. Prints one JSON object; exit 0 only
when sellable, 1 when not, 2 when the matrix itself is malformed. RELEASE.json
inside every archive says ``sellable: false`` regardless; this gate is the only
place the answer can become true.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

MATRIX = Path(__file__).resolve().parent / "qualification/matrix.json"
STATUSES = ("PASS", "FAIL", "NOT RUN", "BLOCKED")
ROW_KEYS = ("id", "requirement", "scope", "required", "status", "archive_sha256", "evidence", "depends_on")


class MatrixError(ValueError):
    """The matrix is not in the documented shape."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    """SHA-256 of a file, streamed."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def load_matrix(path: Path) -> list[dict]:
    """Rows of a matrix file, validated.

    Raises:
        MatrixError: Missing keys, an unknown status, or a malformed file entry.
    """
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise MatrixError(f"cannot read {path}: {error}") from error
    seen: set[str] = set()
    for row in rows:
        missing = [key for key in ROW_KEYS if key not in row]
        if missing or row.get("status") not in STATUSES or row["id"] in seen:
            raise MatrixError(f"row {row.get('id', '?')}: missing {missing}, duplicate id, or status "
                              f"{row.get('status')!r} not one of {STATUSES}")
        for entry in [*row["evidence"], *row["depends_on"]]:
            if not isinstance(entry, dict) or not entry.get("path") or not isinstance(entry.get("sha256"), str):
                raise MatrixError(f"row {row['id']}: every evidence/depends_on entry needs path and sha256")
        seen.add(row["id"])
    return rows


def _member_sha(archive: Path, member: str) -> str | None:
    """SHA-256 of one archive member, or None when absent."""
    with zipfile.ZipFile(archive) as bundle:
        try:
            return _sha(bundle.read(member))
        except KeyError:
            return None


def _entry_problem(entry: dict, archive: Path, evidence_root: Path) -> str | None:
    """Why one recorded file does not match, or None."""
    path = entry["path"]
    if path.startswith("archive:"):
        actual = _member_sha(archive, path[len("archive:"):])
    else:
        target = (evidence_root / path).resolve()
        actual = file_sha256(target) if target.is_file() else None
    if actual is None:
        return f"{path}: missing"
    return None if actual == entry["sha256"] else f"{path}: sha256 differs"


def row_problems(row: dict, archive: Path, archive_sha: str, evidence_root: Path) -> list[str]:
    """Everything that keeps one row from qualifying this archive."""
    problems = []
    if row["status"] != "PASS":
        problems.append(f"status {row['status']}")
    if row["archive_sha256"] != archive_sha:
        problems.append(f"recorded for archive {row['archive_sha256'] or 'none'}, not this one")
    if not row["evidence"]:
        problems.append("no evidence listed")
    for entry in [*row["evidence"], *row["depends_on"]]:
        problem = _entry_problem(entry, archive, evidence_root)
        if problem:
            problems.append(problem)
    return problems


def evaluate(matrix: Path, archive: Path, evidence_root: Path) -> dict[str, object]:
    """The gate's verdict for one archive."""
    rows = load_matrix(matrix)
    archive_sha = file_sha256(archive)
    required = [row for row in rows if row["required"]]
    missing = [{"id": row["id"], "requirement": row["requirement"],
                "problems": row_problems(row, archive, archive_sha, evidence_root)} for row in required]
    missing = [row for row in missing if row["problems"]]
    return {"archive": archive.name, "archive_sha256": archive_sha, "rows": len(rows),
            "required": len(required), "sellable": bool(required) and not missing, "missing": missing}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    args = parser.parse_args(argv)
    try:
        verdict = evaluate(args.matrix, args.archive, args.evidence_root)
    except MatrixError as error:
        print(json.dumps({"sellable": False, "error": str(error)}))
        return 2
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["sellable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
