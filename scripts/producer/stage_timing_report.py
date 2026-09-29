"""Pair timing spans by identity; inclusive work is never request elapsed time.

Process spans pair on their writer's monotonic clock. Manual markers (separate command
invocations, ``clock: wall-epoch``) pair by exact span id on the wall clock. Handoff
events and activity attribution are summarized by ``stage_timing_attribution``.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from stage_timing_attribution import (  # noqa: F401  (union_seconds re-exported for callers)
    attribute, consume_handoff, new_handoff_state, span_interval, summarize_handoffs, union_seconds,
)

_CLOCK_FIELDS = {"process-monotonic": "mono", "wall-epoch": "ts"}
# Overlapping spans reported beside, never inside, a production window's coverage.
_APART = {"unparented": "unparentedSameRun", "foreign": "foreignRun", "unknownLineage": "unknownLineage"}


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
    same = ("stage", "clock", "writerPid", "parentSpanId", "attemptNo",
            "taskId", "claimEpoch", "hostTurnId")
    if any(start.get(k) != end.get(k) for k in same):
        return None
    field = _CLOCK_FIELDS[start["clock"]]
    if not _number(start.get(field)) or not _number(end.get(field)):
        return None
    elapsed = (end[field] - start[field]) * 1000
    reported = end.get("elapsedMs")
    if elapsed < 0 or not _number(reported) or abs(reported - elapsed) > 0.1:
        return None
    if end.get("status") not in ("completed", "failed", "interrupted"):
        return None
    return {**start, "event": "span", "elapsedMs": elapsed,
            "status": end["status"], "endTs": end.get("ts"),
            "attribution": "exact-span-identity" if field == "mono" else "manual-wall-clock"}


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
    if isinstance(row, dict) and row.get("event") == "handoff":
        consume_handoff(row, state["handoffs"])
        return
    if (not isinstance(row, dict) or not isinstance(row.get("stage"), str)
            or row.get("event") not in ("start", "end") or not _number(row.get("mono"))):
        state["issues"].append({"kind": "malformed-row"})
        return
    if row.get("schemaVersion", 1) == 1:
        _legacy(row, state)
        return
    key = _key(row)
    if row.get("schemaVersion") != 2 or key is None or row.get("clock") not in _CLOCK_FIELDS:
        state["issues"].append({"kind": "invalid-v2-identity", "stage": row["stage"]})
        return
    identity = (*key, row["event"])
    if identity in state["seen"]:
        state["issues"].append({"kind": "duplicate-row", "spanId": row["spanId"]})
        return
    state["seen"].add(identity)
    if row["event"] == "start":
        state["starts"][key] = row
        state["lineageRejected"] += bool(row.get("lineageRejected"))
        return
    start = state["starts"].pop(key, None)
    span = _paired(start, row) if start is not None else None
    if span is None:
        state["issues"].append({"kind": "unmatched-or-invalid-end", "spanId": row["spanId"]})
        return
    state["spans"].append(span)


def summarize_timings(rows: list[dict], run_id: str | None = None) -> dict:
    """Summarize all recorded work without claiming complete workflow coverage.

    Args:
        rows: Ordered journal events; each writer's append order must be retained.
        run_id: The production run whose window and attribution to report; None means the
            journal's only production run (several runs make the window unavailable).

    Returns:
        Paired spans, inclusive stage costs, incomplete work and telemetry issues.
        Nested/concurrent stage durations are never summed as request elapsed time.
    """
    state = {"starts": {}, "legacyStarts": defaultdict(list), "seen": set(),
             "spans": [], "issues": [], "handoffs": new_handoff_state(), "lineageRejected": 0}
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
    handoffs = summarize_handoffs(state["handoffs"])
    return {
        "schemaVersion": 2, "spans": state["spans"],
        "stagesInclusiveMs": {k: round(v, 3) for k, v in sorted(totals.items())},
        "incompleteSpans": incomplete, "issues": state["issues"],
        "legacySpanCount": legacy,
        "executionStatusCounts": statuses,
        "allRecordedSpansPaired": not incomplete and not state["issues"],
        "workflowCoverage": "not-established-by-telemetry-alone",
        "recordedWindow": workflow_coverage(state["spans"], run_id, tuple(incomplete)),
        "lineageRejectedSpans": state["lineageRejected"],
        "handoffs": handoffs,
        "attribution": _run_attribution(state["spans"], incomplete, handoffs, run_id),
    }


def _run_attribution(spans: list[dict], incomplete: list[dict], handoffs: dict, run_id: str | None) -> dict:
    """Attribution for the chosen run, or explicitly across every run in the journal."""
    def mine(row: dict) -> bool:
        """Every row when no run is chosen; otherwise only that run's rows."""
        return run_id is None or row.get("runId") == run_id
    scoped = {**handoffs, "publications": [row for row in handoffs["publications"] if mine(row)]}
    result = attribute([s for s in spans if mine(s)], [r for r in incomplete if mine(r)], scoped)
    return {**result, "runScope": run_id or "all-runs-in-journal"}


def _descends(span: dict, window_ids: set, by_key: dict) -> bool:
    """True when the parent chain reaches a window within the span's own run.

    Spans are keyed by (runId, spanId), so every hop stays in that run; a gap, a cycle or a
    parent recorded only in another run ends the walk.
    """
    run_id, seen = span.get('runId'), {span.get('spanId')}
    parent = span.get('parentSpanId')
    while isinstance(parent, str) and parent not in seen:
        if parent in window_ids:
            return True
        seen.add(parent)
        parent = by_key.get((run_id, parent), {}).get('parentSpanId')
    return False


def _coverage_class(span: dict, run_id: str | None, window_ids: set, by_key: dict) -> str:
    """Counted work descends from the window in its run; everything else is reported apart.

    A span with no run identity next to a versioned window, or a versioned span next to a
    legacy (run-less) window, has unknown lineage: it is neither counted nor called foreign.
    A legacy window counts only legacy spans.
    """
    if run_id is None or span.get('runId') is None:
        return 'counted' if run_id is None and span.get('runId') is None else 'unknownLineage'
    if span.get('runId') != run_id:
        return 'foreign'
    return 'counted' if _descends(span, window_ids, by_key) else 'unparented'


def _window(spans: list[dict], run_id: str | None, open_rows: tuple) -> tuple[dict | None, dict]:
    """The chosen run's closed production_total window, widened to any earlier open start.

    A crashed first window never hides behind a later one: elapsed runs from the earliest
    start. An open window without a wall time, or opened after the closed window ended,
    makes the window unavailable instead of shortening it.
    """
    closed = [row for row in spans if row.get('stage') == 'production_total' and run_id in (None, row.get('runId'))]
    opened = [row for row in open_rows if row.get('stage') == 'production_total' and run_id in (None, row.get('runId'))]
    runs = sorted({str(row.get('runId')) for row in [*closed, *opened]})
    unavailable = {'status': 'unavailable', 'productionRuns': runs, 'openWindows': len(opened)}
    if len(runs) > 1:
        return None, {**unavailable, 'reason': 'several production runs share this journal; choose one with --run-id'}
    if len(closed) != 1 or span_interval(closed[0]) is None:
        return None, {**unavailable, 'reason': 'one complete stable production_total span required'}
    start, end = span_interval(closed[0])
    if not all(_number(row.get('ts')) and row['ts'] < end for row in opened):
        return None, {**unavailable, 'reason': 'a production_total start is still open with no earlier wall time'}
    ids = {row.get('spanId') for row in [closed[0], *opened] if isinstance(row.get('spanId'), str)}
    return {'row': closed[0], 'start': min([start, *(row['ts'] for row in opened)]), 'end': end,
            'closedStart': start, 'ids': ids, 'open': len(opened)}, {}


def workflow_coverage(spans: list[dict], run_id: str | None = None, open_rows: tuple = ()) -> dict:
    """Report one production run's window and the recorded work that descends from it.

    Only spans of the window's run whose parent chain reaches one of its production_total
    starts count; other runs, same-run spans without that ancestry (unparented, another
    attempt's unlinked work) and spans of unknown lineage are reported separately and never
    fill this run's coverage. This quantifies telemetry coverage, not idle time, editorial
    completion or quality. ``handover`` repeats the identities recorded at its start.
    """
    window, unavailable = _window(spans, run_id, open_rows)
    if window is None:
        return unavailable
    start, end, row = window['start'], window['end'], window['row']
    by_key = {(item.get('runId'), item['spanId']): item for item in [*spans, *open_rows]
              if isinstance(item.get('spanId'), str)}
    groups: dict[str, list] = {'counted': [], 'unparented': [], 'foreign': [], 'unknownLineage': []}
    intervals = [(span, span_interval(span)) for span in spans if span is not row]
    for span, item in intervals:
        if item is not None and item[0] < end and item[1] > start:
            kind = _coverage_class(span, row.get('runId'), window['ids'], by_key)
            groups[kind].append((max(start, item[0]), min(end, item[1])))
    covered = union_seconds(groups['counted'])
    return {'status': 'recorded-window', 'runId': row.get('runId'),
            'lineageScope': 'run-descendants' if row.get('runId') else 'legacy-run-less-spans-only',
            'startedAtEpoch': start, 'endedAtEpoch': end, 'closedWindowStartedAtEpoch': window['closedStart'],
            'openWindows': window['open'], 'handover': row.get('handover', []),
            'elapsedSeconds': end - start, 'recordedSubstageSeconds': covered,
            'outsideRecordedSubstagesSeconds': max(0.0, end - start - covered),
            **{f'{label}Seconds': union_seconds(groups[name]) for name, label in _APART.items()},
            **{f'{label}Spans': len(groups[name]) for name, label in _APART.items()},
            'excludedInvalidIntervals': sum(item is None for _span, item in intervals),
            'qualityApproved': False, 'outsideScope': 'unattributed, not proven idle or removable'}


def _row(line: str) -> dict:
    """One journal line; a malformed line stays an explicit malformed row."""
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {"malformed": True}


def read_journals(journals: list[Path]) -> list[dict]:
    """Every row of the journals in order; each writer's append order is retained."""
    return [_row(line) for journal in journals for line in journal.read_text(encoding="utf-8").splitlines()]


def main() -> None:
    """Print a report, preserving malformed lines as explicit telemetry issues."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("journals", nargs="+", type=Path)
    parser.add_argument("--run-id", help="report this production run's window and attribution")
    args = parser.parse_args()
    print(json.dumps(summarize_timings(read_journals(args.journals), args.run_id), indent=2))


if __name__ == "__main__":
    main()
