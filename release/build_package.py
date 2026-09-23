#!/usr/bin/env python3
"""Build the buyer package from the isolated release source.

    python3 -m release.build_package --version 0.1.0-rc1 --out <dir>

Order, so a refused build leaves no new apparent release and never overwrites one:

1. Provenance first: the checkout must be clean; its commit and tree id are read
   from git before anything is written.
2. ``--out`` must not exist yet, or be an empty folder.
3. Everything is built in a fresh hidden staging folder beside ``--out``: the
   staged tree (from ``release/package_spec.py``, inspected), the archive, the
   release/file/withheld manifests and ``SHA256SUMS``.
4. Only when every check has passed is that complete set promoted with one
   directory rename onto ``--out``. Any failure removes the staging folder.

``RELEASE.json`` goes inside the archive with the source identity and
``sellable: false``; the archive's own hash goes only into the external
``SHA256SUMS`` and ``release-manifest.json``. Whether a candidate may be sold is
decided outside the build, by ``python -m release.sale_gate`` against the
qualification matrix — never by a list in this file.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sys
from pathlib import Path

from release import archive, payload
from release.stage import StageReport, StagingError, scan_buyer_text, scan_content, \
    scan_paths, scan_shipped_text, stage_tree

ROOT = Path(__file__).resolve().parents[1]
_TEACHER_RULE = "teacher name in a shipped path"
SALE_READINESS = {
    "decided_by": "python -m release.sale_gate (release/qualification/matrix.json), outside this archive",
    "note": "Every candidate archive says sellable:false. Open items for buyers are listed in "
            "PENDING-OWNER-DECISIONS.txt.",
}


def _partition_pending(report: StageReport, allow_pending: bool) -> list[str]:
    """Move the teacher-name path findings out of the blocking set when allowed.

    Args:
        report: Report whose findings are being classified.
        allow_pending: True to record them as pending instead of blocking.

    Returns:
        The findings recorded as pending; the report keeps the rest.
    """
    if not allow_pending:
        return []
    pending = [row for row in report.findings if _TEACHER_RULE in row]
    report.findings = [row for row in report.findings if _TEACHER_RULE not in row]
    return pending


def _stage(root: Path, stage_dir: Path, allow_pending: bool) -> tuple[StageReport, list[str]]:
    """Stage, inspect and write the buyer-facing payload into the staging tree."""
    report = StageReport()
    stage_tree(root, stage_dir, report)
    payload.write_payload(root, stage_dir, report)
    payload.apply_overrides(stage_dir, report)
    scan_paths(stage_dir, report)
    scan_content(stage_dir, report)
    scan_shipped_text(stage_dir, report)
    scan_buyer_text(stage_dir, "manual", report)
    pending = _partition_pending(report, allow_pending)
    report.fail_if_findings()
    return report, pending


def _release_status(pending: list[str]) -> dict[str, object]:
    """Release status recorded inside and beside the archive: never sellable."""
    status: dict[str, object] = {"sellable": False, "sale_readiness": SALE_READINESS}
    if pending:
        status["pending_rename"] = (f"teacher-named identifiers remain in shipped source ({len(pending)} "
                                    "paths); see PENDING-RENAME.txt")
    return status


def _require_fresh_out(out: Path) -> None:
    """``--out`` must be absent or an empty folder; a release set is never overwritten."""
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise StagingError(f"{out} already exists and is not empty; a build never overwrites or adds to "
                           "an existing release folder. Choose a new --out.")


def _write_set(version: str, work: Path, allow_pending: bool, source: dict[str, str]) -> dict[str, object]:
    """Stage, inspect and write the complete release set into ``work/set``."""
    stage_dir, target_dir = work / "stage", work / "set"
    stage_dir.mkdir()
    target_dir.mkdir()
    report, pending = _stage(ROOT, stage_dir, allow_pending)
    if pending:
        (stage_dir / "PENDING-RENAME.txt").write_text(
            "This candidate still contains teacher-named identifiers in shipped\n"
            "source. It is NOT sellable. Affected paths:\n\n"
            + "\n".join(sorted(pending)) + "\n", encoding="utf-8")
    top = f"project-sniper-{version}"
    components = payload.component_versions(ROOT)
    payload.check_buyer_pages(stage_dir)
    payload.write_release_json(stage_dir, version, components, {"source": source, **_release_status(pending)})
    manifest = archive.file_manifest(stage_dir)
    target = target_dir / f"{top}-mac.zip"
    archive.write_archive(stage_dir, top, target)
    extra: dict[str, object] = {"components": components, "built_at_utc": _now(), "source": source,
                                **_release_status(pending)}
    external = archive.external_records(target, version, manifest, extra)
    archive.write_checksums(target, target_dir / "SHA256SUMS")
    archive.write_json(target_dir / "release-manifest.json", external)
    archive.write_json(target_dir / "file-manifest.json", manifest)
    archive.write_json(target_dir / "withheld.json",
                       payload.withheld_records(ROOT, report.skipped, report.files))
    return external


def build(version: str, out: Path, allow_pending: bool) -> dict[str, object]:
    """Build one candidate and promote its complete record set onto ``out``.

    Args:
        version: Release version string used in the archive name.
        out: Folder that will hold the archive and its external records; must
            not exist yet, or be empty.
        allow_pending: Record teacher-name path findings as pending rather than
            failing the build; the release is then explicitly not sellable.

    Returns:
        The external release manifest mapping.

    Raises:
        StagingError: Provenance, the output folder or an inspection refused the
            build; nothing new is left at ``out``.
    """
    source = payload.source_facts(ROOT)
    out = out.resolve()
    _require_fresh_out(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent / f".{out.name}.build-{os.getpid()}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    try:
        external = _write_set(version, work, allow_pending, source)
        _require_fresh_out(out)
        try:
            if out.exists():
                out.rmdir()  # empty, checked just above; rename cannot replace a non-empty folder
            (work / "set").rename(out)
        except OSError as error:
            raise StagingError(f"could not promote the release set to {out}: {error}") from error
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return external


def _now() -> str:
    """UTC build timestamp (external manifest only; never inside the archive)."""
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Build the Project Sniper buyer package")
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--allow-pending-rename", action="store_true",
                        help="record teacher-named shipped paths as a pending blocker "
                             "instead of failing; the result is not sellable")
    args = parser.parse_args(argv)
    try:
        external = build(args.version, args.out, args.allow_pending_rename)
    except StagingError as error:
        print(f"build refused: {error}", file=sys.stderr)
        return 2
    print(f"archive  {args.out.resolve() / external['archive']}")
    print(f"bytes    {external['bytes']}")
    print(f"sha256   {external['sha256']}")
    print(f"entries  {external['entries']}")
    print(f"commit   {external['source']['release_checkout_commit']}")
    print(f"sellable {external['sellable']}  (sale readiness: python -m release.sale_gate)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
