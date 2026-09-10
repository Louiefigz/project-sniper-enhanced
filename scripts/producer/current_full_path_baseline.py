#!/usr/bin/env python3
"""Run one cold/warm observation of the current canonical render path."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from stage_timing_report import summarize_timings

SCRIPT_DIR = Path(__file__).resolve().parent


def _events(stdout: str) -> list[dict]:
    rows = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _journal_rows(path: Path, offset: int) -> list[dict]:
    if not path.is_file():
        return []
    with path.open("rb") as handle:
        handle.seek(offset)
        payload = handle.read().decode("utf-8", errors="replace")
    rows = []
    for line in payload.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            rows.append({"malformed": True})
            continue
        rows.append(value if isinstance(value, dict) else {"malformed": True})
    return rows


def _stage_durations(rows: list[dict]) -> dict[str, int]:
    """Inclusive recorded work per stage, not a sum of elapsed request time."""
    totals = summarize_timings(rows)["stagesInclusiveMs"]
    return {stage: round(value) for stage, value in totals.items()}


def _cache_state(label: str, rows: list[dict]) -> str:
    skipped = any(
        row.get("status") == "stage_skipped" and row.get("stage") == "cut_speed"
        for row in rows
    )
    rendered = any(
        row.get("status") == "stage_done" and row.get("stage") == "cut_speed"
        for row in rows
    )
    if label == "first-run" and rendered and not skipped:
        return "cold"
    if label == "immediate-repeat" and skipped and not rendered:
        return "warm"
    return "unproved"


def _invoke(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        cwd=SCRIPT_DIR, check=False,
    )


def _render_command(plan: Path, manifest: Path, out: Path,
                    work: Path) -> list[str]:
    return [
        sys.executable, str(SCRIPT_DIR / "render.py"),
        str(plan), str(manifest), str(out),
        "--workdir", str(work), "--resume", "--skip-graphics",
        "--require-source-set-admission",
    ]


def _assemble_command(plan: Path, manifest: Path, out: Path) -> list[str]:
    return [
        sys.executable, str(SCRIPT_DIR / "assemble.py"),
        str(out / "base_final.mp4"), str(plan), str(out / "final.mp4"),
        "--fingerprint", str(out / "base.fingerprint.json"),
        "--auto-base", "--manifest", str(manifest),
        "--require-source-set-admission",
    ]


def _audit(out: Path) -> subprocess.CompletedProcess[str]:
    began = time.monotonic_ns()
    result = _invoke([
        sys.executable, str(SCRIPT_DIR / "audit" / "audit_render.py"), str(out),
    ])
    print(json.dumps({
        "event": "baseline_stage",
        "stage": "audit",
        "wallMs": (time.monotonic_ns() - began) // 1_000_000,
    }), flush=True)
    return result


def _failure(results: list[subprocess.CompletedProcess[str]]) -> int:
    failed = next((result for result in results if result.returncode), None)
    if failed is None:
        return 0
    detail = (failed.stdout + "\n" + failed.stderr).strip()[-4_000:]
    print(detail, file=sys.stderr)
    return failed.returncode or 1


def run(project: Path) -> int:
    """Run the incremental canonical path and emit baseline evidence."""
    label = os.environ.get("SNIPER_BASELINE_RUN_LABEL", "")
    plan = project / "edit_plan.json"
    manifest = project / "asset_manifest.json"
    out = project / "render"
    work = project / "work"
    if not plan.is_file() or not manifest.is_file():
        raise RuntimeError("baseline project lacks edit_plan.json or asset_manifest.json")
    out.mkdir(mode=0o700, exist_ok=True)
    work.mkdir(mode=0o700, exist_ok=True)
    journal = out / "stage_timings.jsonl"
    offset = journal.stat().st_size if journal.exists() else 0
    render_result = _invoke(_render_command(plan, manifest, out, work))
    if render_result.returncode == 0:
        rendered_base = out / "final.mp4"
        if not rendered_base.is_file():
            raise RuntimeError("base render reported success without final.mp4")
        os.replace(rendered_base, out / "base_final.mp4")
    assemble_result = (
        _invoke(_assemble_command(plan, manifest, out))
        if render_result.returncode == 0 else None
    )
    audit_result = (
        _audit(out)
        if assemble_result is not None and assemble_result.returncode == 0 else None
    )
    results = [result for result in (
        render_result, assemble_result, audit_result) if result is not None]
    parsed = _events("".join(result.stdout for result in results))
    timing = summarize_timings(_journal_rows(journal, offset))
    print(json.dumps({"event": "baseline_timing_coverage",
                      "incompleteSpans": len(timing["incompleteSpans"]),
                      "issues": timing["issues"],
                      "executionStatusCounts": timing["executionStatusCounts"],
                      "legacySpanCount": timing["legacySpanCount"]}), flush=True)
    for stage, elapsed in timing["stagesInclusiveMs"].items():
        print(json.dumps({
            "event": "baseline_stage",
            "stage": stage,
            "wallMs": elapsed,
            "measurement": "inclusive-stage-time",
        }), flush=True)
    state = _cache_state(label, parsed)
    print(json.dumps({
        "event": "baseline_cache_state",
        "state": state,
        "label": label,
    }), flush=True)
    failure = _failure(results)
    if failure:
        return failure
    if not (out / "final.mp4").is_file():
        print("current path reported success without final.mp4", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    args = parser.parse_args(argv)
    return run(args.project.resolve(strict=True))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
