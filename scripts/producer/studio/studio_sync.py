#!/usr/bin/env python3
"""studio_sync — map Studio operator edits back into ``edit_plan.json``.

CLI::

    studio_sync.py <studio_dir> [--apply] [--json] [--plan P] [--manifest M]

Default is a DRY RUN: a structured diff report of what the operator changed
in HyperFrames Studio (per-entry timing/value changes, deletions, view-only
layout moves, unsupported additions, instance-file findings). ``--apply``
gates the updated plan through ``plan_lint`` + the template contract, backs
the current plan up into ``plan-history/``, writes the plan, and rebaselines
``studio.manifest.json`` + ``view.fingerprint.json`` so the generator's
unsynced-edit guard and the next sync see a clean baseline.

Saved composition declaration defaults must match the authoritative host-slot
values. Unmatched or conflicting panel edits remain pending and block apply;
they are never silently rebaselined as a successful plan edit.

The plan resolves to ``edit_plan.json`` beside the manifest's recorded base
video (``--plan`` overrides); lint reads ``asset_manifest.json`` from the
same directory (``--manifest`` overrides).

Gating is baseline-diffed: changed-entry template-contract violations and
lint failures the edit INTRODUCED block; baseline lint failures that predate
the edit are reported (``preexistingGateFailures``) but never block, so a
small edit still syncs on a legacy plan.

Exit codes: 0 = report printed / applied clean; 1 = the edit introduced new
gate failures (nothing written); 2 = the directory cannot be synced.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path

from studio.sync_apply import PREEXISTING_NOTE, apply_sync
from studio.sync_diff import SyncState, compute_report, load_state
from studio.sync_model import (
    StudioSyncError,
    StudioSyncGateFailure,
    SyncReport,
)


def _entry_lines(report: SyncReport) -> list[str]:
    lines = []
    for diff in report.entry_diffs:
        lines.append(f"~ {diff.label} ({diff.kind}, {diff.slot})")
        if diff.timing_new is not None:
            lines.append(f"    window {diff.timing_old[0]}-"
                         f"{diff.timing_old[1]}s -> {diff.timing_new[0]}-"
                         f"{diff.timing_new[1]}s")
        for change in diff.value_changes:
            lines.append(f"    spec.{change.key}: {change.old!r} -> "
                         f"{change.new!r}")
        lines.extend(f"    [layout] {note}" for note in diff.layout_notes)
    return lines


def _section(title: str, rows: list[str]) -> list[str]:
    return [f"{title}:"] + [f"  {row}" for row in rows] if rows else []


def render_text(report: SyncReport) -> str:
    """Human-readable dry-run report."""
    if report.clean:
        return "clean — the studio project matches its generation state"
    lines = _section("Plan-facing changes", _entry_lines(report))
    lines += _section("Deletions", [
        f"- {d.label} ({d.kind}, {d.slot}) — entry will be removed from "
        "graphicsTrack" for d in report.deletions])
    lines += _section("UNSUPPORTED ADDITIONS (will not survive re-render)",
                      report.additions)
    lines += _section("File findings", report.file_notes)
    lines += _section("Informational", report.informational)
    lines += _section("BLOCKERS (apply will refuse)", report.blockers)
    return "\n".join(lines)


def _resolve_manifest(state: SyncState, override: str | None) -> str:
    path = os.path.abspath(override) if override else os.path.join(
        os.path.dirname(state.plan_path), "asset_manifest.json")
    if not os.path.isfile(path):
        raise StudioSyncError(
            f"asset manifest not found at {path} — plan_lint cannot run; "
            "pass --manifest")
    return path


def _run_apply(state: SyncState, report: SyncReport,
               manifest: str | None) -> int:
    if report.blockers:
        print(json.dumps({"status": "refused",
                          "blockers": report.blockers}, indent=1))
        return 2
    if report.clean:
        print(json.dumps({"status": "clean", "planPath": state.plan_path}))
        return 0
    try:
        summary = apply_sync(state, report, _resolve_manifest(state, manifest))
    except StudioSyncGateFailure as exc:
        print(json.dumps({"status": "rejected", "written": False,
                          "newGateFailures": exc.failures,
                          "preexistingGateFailures": exc.preexisting,
                          "preexistingNote": PREEXISTING_NOTE
                          if exc.preexisting else ""}, indent=1))
        return 1
    except StudioSyncError as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}))
        return 2
    print(json.dumps(summary, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("studio_dir", help="generated studio project dir")
    parser.add_argument("--apply", action="store_true",
                        help="write the plan (default: dry-run report)")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable dry-run report")
    parser.add_argument("--plan", help="edit_plan.json override")
    parser.add_argument("--manifest", help="asset_manifest.json override")
    args = parser.parse_args(argv)
    try:
        state = load_state(args.studio_dir, args.plan)
    except StudioSyncError as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}))
        return 2
    report = compute_report(state)
    if args.apply:
        return _run_apply(state, report, args.manifest)
    print(json.dumps(report.to_json(), indent=1) if args.json
          else render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
