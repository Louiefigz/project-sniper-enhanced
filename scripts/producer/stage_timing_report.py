"""Pair timing spans by identity; inclusive work is never request elapsed time."""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


def _number(value: object) -> bool:
    """Accept finite telemetry numbers, not booleans or string coercions."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and abs(value) <= 2**53 - 1)


def _key(row: dict) -> tuple | None:
    """Resolve one process incarnation and span without mixing resume clocks."""
    names = ("runId", "attemptId", "writerId", "spanId")
    if not all(isinstance(row.get(k), str) and row[k] for k in names):
        return None
    return tuple(row[k] for k in names)


def _paired(start: dict, end: dict) -> dict | None:
    """Validate an exact pair; execution completion does not imply content approval."""
    same = ("stage", "clock", "writerPid", "parentSpanId", "attemptNo")
    if any(start.get(k) != end.get(k) for k in same):
        return None
    elapsed = (end["mono"] - start["mono"]) * 1000
    reported = end.get("elapsedMs")
    if elapsed < 0 or not _number(reported) or abs(reported - elapsed) > 0.1:
        return None
    if end.get("status") not in ("completed", "failed", "interrupted"):
        return None
    return {**start, "event": "span", "elapsedMs": elapsed,
            "status": end["status"], "endTs": end.get("ts"),
            "attribution": "exact-span-identity"}


def _legacy(row: dict, state: dict) -> None:
    """Retain old sequential parsing while explicitly flagging weaker attribution."""
    stage = row["stage"]
    starts = state["legacyStarts"][stage]
    if row["event"] == "start":
        starts.append(row)
        return
    if not starts:
        state["issues"].append({"kind": "legacy-orphan-end", "stage": stage})
        return
    start = starts.pop()
    elapsed = (row["mono"] - start["mono"]) * 1000
    if elapsed < 0:
        state["issues"].append({"kind": "legacy-clock-regression", "stage": stage})
        return
    span = {"stage": stage, "elapsedMs": elapsed,
            "status": "unknown", "attribution": "legacy-stage-stack"}
    if _number(start.get("ts")) and _number(row.get("ts")):
        span.update(ts=start["ts"], endTs=row["ts"])
    state["spans"].append(span)


def _consume(row: dict, state: dict) -> None:
    """Record one row; malformed, duplicate and orphan records stay observable."""
    if (not isinstance(row, dict) or not isinstance(row.get("stage"), str)
            or row.get("event") not in ("start", "end") or not _number(row.get("mono"))):
        state["issues"].append({"kind": "malformed-row"})
        return
    if row.get("schemaVersion", 1) == 1:
        _legacy(row, state)
        return
    key = _key(row)
    if row.get("schemaVersion") != 2 or key is None or row.get("clock") != "process-monotonic":
        state["issues"].append({"kind": "invalid-v2-identity", "stage": row["stage"]})
        return
    identity = (*key, row["event"])
    if identity in state["seen"]:
        state["issues"].append({"kind": "duplicate-row", "spanId": row["spanId"]})
        return
    state["seen"].add(identity)
    if row["event"] == "start":
        state["starts"][key] = row
        return
    start = state["starts"].pop(key, None)
    span = _paired(start, row) if start is not None else None
    if span is None:
        state["issues"].append({"kind": "unmatched-or-invalid-end", "spanId": row["spanId"]})
        return
    state["spans"].append(span)


def summarize_timings(rows: list[dict]) -> dict:
    """Summarize all recorded work without claiming complete workflow coverage.

    Args:
        rows: Ordered journal events; each writer's append order must be retained.

    Returns:
        Paired spans, inclusive stage costs, incomplete work and telemetry issues.
        Nested/concurrent stage durations are never summed as request elapsed time.
    """
    state = {"starts": {}, "legacyStarts": defaultdict(list), "seen": set(),
             "spans": [], "issues": []}
    for row in rows:
        _consume(row, state)
    totals: dict[str, float] = defaultdict(float)
    for span in state["spans"]:
        totals[span["stage"]] += span["elapsedMs"]
    incomplete = list(state["starts"].values())
    incomplete.extend(row for group in state["legacyStarts"].values() for row in group)
    legacy = sum(s["attribution"] == "legacy-stage-stack" for s in state["spans"])
    statuses = {status: sum(s["status"] == status for s in state["spans"])
                for status in ("completed", "failed", "interrupted", "unknown")}
    return {
        "schemaVersion": 2, "spans": state["spans"],
        "stagesInclusiveMs": {k: round(v, 3) for k, v in sorted(totals.items())},
        "incompleteSpans": incomplete, "issues": state["issues"],
        "legacySpanCount": legacy,
        "executionStatusCounts": statuses,
        "allRecordedSpansPaired": not incomplete and not state["issues"],
        "workflowCoverage": "not-established-by-telemetry-alone",
        "recordedWindow": workflow_coverage(state["spans"]),
    }


def _interval(span: dict) -> tuple[float, float] | None:
    """Reject wall-clock steps and absent timestamps instead of estimating gaps."""
    values = (span.get('ts'), span.get('endTs'), span.get('elapsedMs'))
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) for value in values):
        return None
    start, end, elapsed = values
    if end < start or abs((end - start) * 1000 - elapsed) > 2000:
        return None
    return start, end


def union_seconds(intervals: list[tuple[float, float]]) -> float:
    """Count overlapping/nested intervals once, including touching boundaries."""
    total, end = 0.0, -math.inf
    for start, stop in sorted(intervals):
        total += max(0.0, stop - max(start, end))
        end = max(end, stop)
    return total


def workflow_coverage(spans: list[dict]) -> dict:
    """Report a declared production_total window and its recorded substage coverage.

    This quantifies telemetry coverage, not idle time, editorial completion or
    quality. Multiple windows need separate reports to avoid mixing productions.
    """
    windows = [span for span in spans if span.get('stage') == 'production_total']
    if len(windows) != 1 or _interval(windows[0]) is None:
        return {'status': 'unavailable', 'reason': 'one complete stable production_total span required'}
    start, end = _interval(windows[0])
    children = [span for span in spans if span is not windows[0]]
    intervals = [_interval(span) for span in children]
    valid = [(max(start, item[0]), min(end, item[1])) for item in intervals
             if item and item[0] < end and item[1] > start]
    covered = union_seconds(valid)
    return {'status': 'recorded-window', 'startedAtEpoch': start, 'endedAtEpoch': end,
            'elapsedSeconds': end - start, 'recordedSubstageSeconds': covered,
            'outsideRecordedSubstagesSeconds': max(0.0, end - start - covered),
            'excludedInvalidIntervals': sum(item is None for item in intervals),
            'qualityApproved': False, 'outsideScope': 'unattributed, not proven idle or removable'}


def main() -> None:
    """Print a report, preserving malformed lines as explicit telemetry issues."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("journals", nargs="+", type=Path)
    args = parser.parse_args()
    rows = []
    for journal in args.journals:
        for line in journal.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append({"malformed": True})
    print(json.dumps(summarize_timings(rows), indent=2))


if __name__ == "__main__":
    main()
