#!/usr/bin/env python3
"""Print local Sniper capabilities, applicable read paths and explicit project context."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from context_inventory import codex_root, file_record, inventory, json_record
from context_routes import BASE_READS, COMMANDS, PROJECT_FILES, REVIEW_REQUIREMENTS, ROUTE_READS

REPO = Path(__file__).resolve().parents[2]
RECORDED_VERDICTS = {"pass", "fail", "failed", "pending", "ready-for-user-review",
                     "native-short-checked-for-review", "native-long-checked-for-review",
                     "running", "interrupted", "completed", "blocked"}
MAX_CHILD_ENTRIES = 64


def instruction_chain(directory: Path) -> list[dict[str, Any]]:
    """List scoped instruction files in ancestor order; do not claim they were read."""
    paths = [codex_root() / "AGENTS.md"]
    paths.extend(parent / "AGENTS.md" for parent in reversed((directory, *directory.parents)))
    rows = [file_record(path) for path in dict.fromkeys(paths)]
    return [row for row in rows if row["status"] != "missing"]


def project_route(project: Path, rows: dict[str, dict]) -> str:
    """Use the shared native selector; incomplete or conflicting manifests remain explicit."""
    native_names = ("LONG-PROJECT.json", "SHORT-PROJECT.json")
    if any(rows[name]["status"] != "missing" for name in native_names):
        from studio.native_export import export_adapter
        try:
            route = export_adapter(project)
        except (OSError, ValueError, RuntimeError):
            return "native-manifest-conflict"
        states = {rows[name]["status"] for name in native_names}
        if states & {"invalid-json", "too-large"}:
            return "native-manifest-invalid"
        if states - {"readable", "missing"}:
            return "native-manifest-unreadable"
        return route
    if rows["index.html"]["status"] != "missing":
        return "native-undeclared"
    if any(rows[name]["status"] != "missing" for name in
           ("edit_plan.json", "producer/edit_plan.json")):
        return "producer"
    return "undetermined"


def native_candidate(child: Path) -> dict[str, Any] | None:
    """Inspect immediate real directories for declared native manifest paths only."""
    if child.is_symlink() or not child.is_dir():
        return None
    rows = {name: file_record(child / name) for name in ("LONG-PROJECT.json", "SHORT-PROJECT.json")}
    if all(row["status"] == "missing" for row in rows.values()):
        return None
    return {"path": str(child), "declaredRoute": project_route(child, rows),
            "manifests": [row for row in rows.values() if row["status"] != "missing"],
            "qualification": "manifest-presence-only; not selected or validated"}


def native_candidates(project: Path) -> dict[str, Any]:
    """Offer bounded immediate-child candidates without selecting or ranking latest edits."""
    try:
        entries = list(islice(project.iterdir(), MAX_CHILD_ENTRIES + 1))
        candidates = [native_candidate(child) for child in entries[:MAX_CHILD_ENTRIES]]
    except OSError as error:
        return {"status": "unreadable", "errorType": type(error).__name__, "candidates": []}
    return {"status": "read", "entriesInspected": min(len(entries), MAX_CHILD_ENTRIES),
            "truncated": len(entries) > MAX_CHILD_ENTRIES,
            "candidates": sorted((row for row in candidates if row), key=lambda row: row["path"]),
            "scope": "first 64 immediate entries; no recursion or symlink traversal",
            "nextStep": "Pass --project with the chosen declared composition directory; no candidate was selected."}


def project_context(project: Path | None) -> dict[str, Any]:
    """Inspect only an explicitly selected directory and known state markers."""
    if project is None:
        return {"selection": "none", "route": "undetermined",
                "note": "Pass --project; no latest-directory or active-project assumption."}
    rows = {name: file_record(project / name) for name in PROJECT_FILES}
    for name in PROJECT_FILES:
        if not name.endswith(".json") or rows[name]["status"] == "missing":
            continue
        row, data = json_record(project / name)
        recorded = data.get("status") if isinstance(data, dict) else None
        if isinstance(recorded, str) and recorded in RECORDED_VERDICTS:
            row["recordedStatus"] = recorded
        rows[name] = row
    route = project_route(project, rows)
    report = {"selection": "explicit", "path": str(project), "route": route,
              "instructions": instruction_chain(project),
              "files": {key: row for key, row in rows.items() if row["status"] != "missing"},
              "reviewQualification": "not-checked; recorded status is not current approval",
              "discoveryScope": "selected directory, known markers and bounded child candidates; no recursive selection"}
    if route in {"native-undeclared", "undetermined"} and rows["BRIEF.md"]["status"] == "readable":
        report["nativeCandidates"] = native_candidates(project)
    return report


def build_context(args: argparse.Namespace) -> dict[str, Any]:
    """Collect a report without launching setup, preview, rendering or authentication."""
    project = Path(args.project).expanduser().resolve(strict=True) if args.project else None
    if project is not None and not project.is_dir():
        raise NotADirectoryError("Selected project is not a directory")
    if project is not None:
        next(project.iterdir(), None)  # Distinguish unreadable directory from empty/missing markers.
    selected = project_context(project)
    detected = selected["route"]
    workflow = args.workflow if args.workflow != "auto" else detected
    if workflow.startswith("native-") and workflow not in ROUTE_READS:
        workflow = "native"
    workflow = workflow if workflow in ROUTE_READS else "overview"
    reads = [file_record(REPO / name) for name in (*BASE_READS, *ROUTE_READS[workflow])]
    return {"schemaVersion": 1, "observedAt": datetime.now(timezone.utc).isoformat(),
            "repository": str(REPO), "mode": "read-only-offline-discovery",
            "instructions": instruction_chain(REPO), "workflow": workflow,
            "requiredReads": reads, "inventory": inventory(REPO, args.probe_tools),
            "project": selected, "commands": COMMANDS,
            "reviewRequirements": list(REVIEW_REQUIREMENTS),
            "limits": ["Discovery is not completed instruction reading, setup or production approval.",
                       "No secrets/config contents, provider auth, network, installs, media or servers are requested.",
                       "Installed domain skills and native PIPELINE routes supersede the old graphics-only boundary.",
                       "Version probes are optional fixed local subprocesses; default discovery executes none."]}


def catalog_lines(catalog: dict[str, Any]) -> list[str]:
    """Separate historical counts from current readable catalog source observations."""
    lines = [f"Catalog: {catalog['status']}; {catalog.get('items', '?')} recorded items; "
             f"source states {catalog.get('sourceStates', {})}; native execution not approved"]
    if "mirrorSnapshot" not in catalog:
        return lines
    snapshot = catalog["mirrorSnapshot"]
    lines.append(f"Mirror historical lock: {snapshot.get('itemsInstalled', '?')} installed / "
                 f"{snapshot.get('itemsListed', '?')} listed on {snapshot.get('mirroredAt', '?')}")
    lines.append(f"Mirror source files now: {catalog['currentMirrorSourceStates']} "
                 f"of {catalog['currentMirrorSourceCount']} indexed; no upstream refresh")
    lines.extend(f"  [{row['status']}] {row['ref']} — {row['path']}"
                 for row in catalog["unavailableMirrorSources"])
    return lines


def render_text(report: dict[str, Any]) -> str:
    """Present a compact report while leaving full structured evidence in JSON output."""
    inv, project = report["inventory"], report["project"]
    runtime, catalog = inv["hyperframes"], inv["catalog"]
    stock = runtime["stock"]
    lines = ["PROJECT SNIPER context — read-only, offline", f"Repository: {report['repository']}",
             f"Project: {project.get('path', 'not selected')} | route: {project['route']}",
             f"HyperFrames: {stock['status']} {stock.get('version') or '(version unknown)'} — {stock['path']}",
             f"Adapted runtime metadata: {len(runtime['adaptedRuntimes'])} entries; none selected/qualified",
             f"Python: {inv['python']['version']} — {inv['python']['path']}"]
    lines.extend(f"Tool {row['name']}: {row['status']} {row['version'] or ''} — {row['path'] or '(not on PATH)'}"
                 for row in inv["tools"])
    lines.extend(catalog_lines(catalog))
    lines.append("Installed domain skill paths (read SKILL.md before use):")
    skills = {row["name"]: row for row in reversed(inv["skills"])
              if row["origin"] == "installed" and row["status"] == "readable"}
    lines.extend(f"  {name}: {row['path']}" for name, row in sorted(skills.items()))
    lines.append(f"Required reads for {report['workflow']} (presence is not reading):")
    paths = [*report["instructions"], *report["requiredReads"], *project.get("instructions", [])]
    unique = {row["path"]: row for row in paths}
    lines.extend(f"  [{row['status']}] {row['path']}" for row in unique.values())
    if project.get("files"):
        lines.append("Selected project artifacts (historical statuses are unverified):")
        lines.extend(f"  [{row['status']}] {name}" +
                     (f" | recorded: {row['recordedStatus']}" if "recordedStatus" in row else "")
                     for name, row in project["files"].items())
    candidates = project.get("nativeCandidates")
    if candidates:
        lines.extend(candidate_lines(candidates))
    lines.extend(["Review requirements:", *(f"  {item}" for item in report["reviewRequirements"]),
                  "Existing entry commands (not executed):",
                  *(f"  {key}: {value}" for key, value in report["commands"].items()),
                  "No active project was inferred. JSON output includes paths and unavailable-source details."])
    return "\n".join(lines)


def candidate_lines(scan: dict[str, Any]) -> list[str]:
    """Explain container selection without implying that a declared child is active."""
    lines = [f"Immediate native composition candidates: {scan['status']} "
             f"(scan truncated: {scan.get('truncated', 'unknown')}; none selected)"]
    lines.extend(f"  {row['declaredRoute']}: {row['path']}" for row in scan["candidates"])
    lines.append(scan.get("nextStep", "Child scan unavailable; select a known composition explicitly."))
    return lines


def main(argv: list[str] | None = None) -> int:
    """Return 2 for an inaccessible selected project; capability gaps remain inventory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Explicit artifact/native/Producer directory; never guessed")
    parser.add_argument("--workflow", choices=("auto", *ROUTE_READS), default="auto")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--probe-tools", action="store_true", help="Run bounded local version probes; no installs")
    args = parser.parse_args(argv)
    try:
        report = build_context(args)
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "context-unavailable", "errorType": type(error).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.format == "json" else render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
