#!/usr/bin/env python3
"""Build the buyer package from the isolated release source.

    python3 -m release.build_package --version 0.1.0-rc1 --out <dir>

The staged tree is assembled from `release/package_spec.py`, inspected, then
archived deterministically. Nothing is archived from the development folder.
`RELEASE.json` goes inside the archive; the archive's own hash goes only into
the external `SHA256SUMS` and `release-manifest.json`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

from release import archive, payload
from release import package_spec as spec
from release.stage import StageReport, StagingError, scan_buyer_text, scan_content, \
    scan_paths, scan_shipped_text, stage_tree

ROOT = Path(__file__).resolve().parents[1]
_TEACHER_RULE = "teacher name in a shipped path"


def _components(root: Path) -> dict[str, object]:
    """Exact component versions recorded for this release."""
    return payload.component_versions(root)


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


# Mirrors PENDING-OWNER-DECISIONS.txt and the qualification report; every entry
# must be closed by evidence, not by editing this list.
OPEN_BLOCKERS = (
    "licence wording not final or reviewed; refund effect on the grant and governing law unsettled (input D)",
    "no support route or response commitment (input D)",
    "supported platform boundary unproven: no clean-Mac install run (Z2, input R)",
    "outside-operator install and edit not run (Z10)",
    "authenticated delivery of these exact bytes not run (Z11)",
    "Claude route not exercised for real: the Claude CLI on the build Mac is not signed in",
)


def _release_status(pending: list[str]) -> dict[str, object]:
    """Release status recorded inside and beside the archive."""
    if pending:
        return {"sellable": False,
                "blockers": ["teacher-named identifiers remain in shipped source "
                             f"({len(pending)} paths); see PENDING-RENAME.txt"]}
    return {"sellable": False, "blockers": list(OPEN_BLOCKERS)}


def build(version: str, out: Path, allow_pending: bool) -> dict[str, object]:
    """Build one candidate archive and its external records.

    Args:
        version: Release version string used in the archive name.
        out: Output directory for the archive and external records.
        allow_pending: Record teacher-name path findings as pending rather than
            failing the build; the release is then explicitly not sellable.

    Returns:
        The external release manifest mapping.
    """
    stage_dir = out / "stage"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    report, pending = _stage(ROOT, stage_dir, allow_pending)
    if pending:
        (stage_dir / "PENDING-RENAME.txt").write_text(
            "This candidate still contains teacher-named identifiers in shipped\n"
            "source. It is NOT sellable. Affected paths:\n\n"
            + "\n".join(sorted(pending)) + "\n", encoding="utf-8")
    top = f"project-sniper-{version}"
    components = _components(ROOT)
    payload.write_release_json(stage_dir, version, components, _release_status(pending))
    manifest = archive.file_manifest(stage_dir)
    target = out / f"{top}-mac.zip"
    archive.write_archive(stage_dir, top, target)
    extra: dict[str, object] = {"components": components, "built_at_utc": _now(),
                                "source": payload.source_facts(ROOT),
                                **_release_status(pending)}
    external = archive.external_records(target, version, manifest, extra)
    archive.write_checksums(target, out / "SHA256SUMS")
    archive.write_json(out / "release-manifest.json", external)
    archive.write_json(out / "file-manifest.json", manifest)
    archive.write_json(out / "withheld.json",
                       [{"path": p, "reason": r} for p, r in sorted(report.skipped)])
    return external


def _now() -> str:
    """UTC build timestamp."""
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
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        external = build(args.version, args.out, args.allow_pending_rename)
    except StagingError as error:
        print(f"build refused: {error}", file=sys.stderr)
        return 2
    print(f"archive  {external['archive']}")
    print(f"bytes    {external['bytes']}")
    print(f"sha256   {external['sha256']}")
    print(f"entries  {external['entries']}")
    print(f"sellable {external['sellable']}")
    for blocker in external["blockers"]:
        print(f"blocker  {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
