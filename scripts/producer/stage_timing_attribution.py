"""Separate recorded waiting, execution and handoff delay; absent attribution stays unknown.

Categories come only from explicit evidence: a span's closed ``metadata.activity`` or a
matched artifact-published → consumer-accepted handoff pair. Each category is an
interval union, so concurrent work counts once; categories may overlap one another and
are never summed into elapsed time. Nothing is inferred from a stage name, an
idle-looking gap or a missing event. Diagnostics only: no safety decision reads this.
"""
from __future__ import annotations

import math

from stage_timing_context import CLAIM_PHASES, HANDOFF_PHASES, bounded_id, handoff_problem

CATEGORIES = {"modelExecution": "model", "toolExecution": "tool",
              "hostSlotWaiting": "host-slot-wait", "nativeQueueWaiting": "native-queue-wait",
              "pressureWaiting": "pressure-wait"}
_PRE_CLAIM = ("dependencies-satisfied", "ready")


def span_interval(span: dict) -> tuple[float, float] | None:
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


def new_handoff_state() -> dict:
    """Accumulator for one report; events keep journal order."""
    return {"seen": set(), "logical": set(), "events": [], "issues": []}


def event_identity_problem(row: dict) -> str | None:
    """Every accepted event carries version-2 run identity, an event id and a wall time."""
    if row.get("schemaVersion") != 2 or not bounded_id(row.get("runId")) \
            or not bounded_id(row.get("eventId")):
        return "invalid-event-identity"
    ts = row.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts):
        return "invalid-event-identity"
    return None


def consume_handoff(row: dict, state: dict) -> None:
    """Keep the first of each event; replays and malformed events stay observable."""
    problem = handoff_problem(row) or event_identity_problem(row)
    if problem:
        state["issues"].append({"kind": problem, "eventId": row.get("eventId")})
        return
    if row["eventId"] in state["seen"]:
        state["issues"].append({"kind": "duplicate-handoff-event", "eventId": row["eventId"]})
        return
    state["seen"].add(row["eventId"])
    logical = None if row["handoffPhase"] in _PRE_CLAIM else tuple(
        row.get(key) for key in ("runId", "taskId", "claimEpoch", "handoffPhase",
                                 "artifactSha256", "consumerId"))
    if logical in state["logical"]:
        state["issues"].append({"kind": "replayed-handoff", "eventId": row["eventId"],
                                "handoffPhase": row["handoffPhase"]})
        return
    if logical is not None:
        state["logical"].add(logical)
    state["events"].append(row)


def _publication_key(row: dict) -> tuple:
    """An exact artifact publication: run, task, claim epoch and artifact hash."""
    return tuple(row[key] for key in ("runId", "taskId", "claimEpoch", "artifactSha256"))


def _acceptance(row: dict, published: float, issues: list) -> dict:
    """One consumer's acceptance; a clock-reversed pair keeps an unknown delay."""
    delay = row["ts"] - published
    if delay < 0:
        issues.append({"kind": "acceptance-before-publication", "eventId": row["eventId"]})
    return {"consumerId": row.get("consumerId"), "acceptedAt": row["ts"],
            "delaySeconds": delay if delay >= 0 else None}


def publications(events: list[dict], issues: list) -> list[dict]:
    """Pair each exact artifact publication with its consumers' acceptances."""
    accepted: dict[tuple, list[dict]] = {}
    for row in events:
        if row["handoffPhase"] == "consumer-accepted":
            accepted.setdefault(_publication_key(row), []).append(row)
    result = []
    for row in (item for item in events if item["handoffPhase"] == "artifact-published"):
        key = _publication_key(row)
        rows = accepted.pop(key, [])
        result.append({"runId": key[0], "taskId": key[1], "claimEpoch": key[2],
                       "artifactSha256": key[3], "publishedAt": row["ts"],
                       "acceptances": [_acceptance(item, row["ts"], issues) for item in rows],
                       "status": "accepted" if rows else "awaiting-acceptance"})
    for rows in accepted.values():
        issues.extend({"kind": "acceptance-without-publication", "eventId": item["eventId"]}
                      for item in rows)
    return result


def _claim_timeline(key: tuple, rows: list[dict], pre_claim: list[dict], issues: list) -> dict:
    """First observation of each phase for one claim; only adjacent observed phases form gaps."""
    phases: dict[str, float] = {}
    for row in sorted(rows, key=lambda item: item["ts"]):
        phases.setdefault(row["handoffPhase"], row["ts"])
    anchor = phases.get("claim-requested", min(phases.values()))
    for row in sorted(pre_claim, key=lambda item: item["ts"]):
        if row["ts"] <= anchor:
            phases[row["handoffPhase"]] = row["ts"]  # latest readiness before this claim
    gaps = {}
    for before, after in zip(HANDOFF_PHASES, HANDOFF_PHASES[1:]):
        gap = phases[after] - phases[before] if before in phases and after in phases else None
        if gap is not None and gap < 0:
            issues.append({"kind": "handoff-phase-order", "taskId": key[1], "phases": [before, after]})
            gap = None
        gaps[f"{before}→{after}"] = gap
    return {"runId": key[0], "taskId": key[1], "claimEpoch": key[2],
            "phasesAt": {phase: phases[phase] for phase in HANDOFF_PHASES if phase in phases},
            "gapsSeconds": gaps,
            "unobservedPhases": [phase for phase in HANDOFF_PHASES if phase not in phases]}


def summarize_handoffs(state: dict) -> dict:
    """Per-claim timelines, publication delays, ready-but-unclaimed tasks and issues."""
    issues = list(state["issues"])
    claims: dict[tuple, list[dict]] = {}
    ready: dict[tuple, list[dict]] = {}
    for row in state["events"]:
        task = (row["runId"], row["taskId"])
        if row["handoffPhase"] in CLAIM_PHASES:
            claims.setdefault((*task, row["claimEpoch"]), []).append(row)
        else:
            ready.setdefault(task, []).append(row)
    timelines = [_claim_timeline(key, rows, ready.get(key[:2], []), issues)
                 for key, rows in claims.items()]
    claimed = {key[:2] for key in claims}
    unclaimed = [{"runId": task[0], "taskId": task[1],
                  "lastObservedAt": max(row["ts"] for row in rows)}
                 for task, rows in ready.items() if task not in claimed]
    return {"events": len(state["events"]), "claims": timelines,
            "publications": publications(state["events"], issues),
            "readyWithoutObservedClaim": unclaimed, "issues": issues}


def _valid(intervals: list) -> list[tuple[float, float]]:
    """Drop intervals that failed validation (they are counted, never estimated)."""
    return [item for item in intervals if item is not None]


def _category(matched: list, parts: dict, open_count: int, source: str) -> dict:
    """Inclusive union, exclusive union and summed work; nothing observed is unknown, not zero."""
    valid = _valid(matched)
    if not valid:
        return {"status": "unknown", "source": source, "unionSeconds": None, "exclusiveSeconds": None,
                "summedSeconds": None, "intervals": 0, "invalidIntervals": len(matched),
                "openIntervals": open_count}
    return {"status": "measured", "source": source, "unionSeconds": union_seconds(valid),
            "exclusiveSeconds": union_seconds(parts["exclusive"]),
            "summedSeconds": sum(end - start for start, end in _valid(parts["outermost"])),
            "intervals": len(valid), "invalidIntervals": len(matched) - len(valid),
            "openIntervals": open_count}


def _activity(row: dict) -> str | None:
    """The span's declared activity; an undeclared span belongs to no category."""
    metadata = row.get("metadata")
    return metadata.get("activity") if isinstance(metadata, dict) else None


def _chain(span: dict, by_key: dict) -> list[dict]:
    """Completed ancestors in the span's own run, nearest first; self-parenting and cycles stop."""
    run_id, seen, chain = span.get("runId"), {span.get("spanId")}, []
    parent = by_key.get((run_id, span.get("parentSpanId")))
    while parent is not None and parent["spanId"] not in seen:
        seen.add(parent["spanId"])
        chain.append(parent)
        parent = by_key.get((run_id, parent.get("parentSpanId")))
    return chain


def _subtract(interval: tuple[float, float], cuts: list) -> list[tuple[float, float]]:
    """The parts of one interval covered by none of the cuts."""
    start, end = interval
    pieces, cursor = [], start
    for low, high in sorted(cuts):
        if low > cursor:
            pieces.append((cursor, min(low, end)))
        cursor = max(cursor, high)
    pieces.append((cursor, end))
    return [(low, high) for low, high in pieces if high > low]


def _span_parts(spans: list[dict]) -> list[dict]:
    """Per categorized span: its interval, whether it is outermost in its category, and own time.

    Only completed ancestors of the same run count (an open or foreign parent never hides a
    span). Own time is the span minus its nearest categorized descendants, so each instant of
    a nested chain belongs to exactly one category: the innermost active one.
    """
    by_key = {(span.get("runId"), span["spanId"]): span for span in spans if isinstance(span.get("spanId"), str)}
    rows = [(span, span_interval(span), _chain(span, by_key)) for span in spans if _activity(span)]
    inner: dict[int, list] = {}
    for _span, interval, chain in rows:
        nearest = next((item for item in chain if _activity(item)), None)
        if nearest is not None and interval is not None:
            inner.setdefault(id(nearest), []).append(interval)
    return [{"activity": _activity(span), "interval": interval,
             "outermost": _activity(span) not in {_activity(item) for item in chain},
             "own": _subtract(interval, inner.get(id(span), [])) if interval else []}
            for span, interval, chain in rows]


def attribute(spans: list[dict], incomplete: list[dict], handoffs: dict) -> dict:
    """Separate model, tool, host-slot, native queue, pressure and publication delays."""
    parts = _span_parts(spans)
    categories, every = {}, []
    for name, activity in CATEGORIES.items():
        mine = [part for part in parts if part["activity"] == activity]
        pieces = {"exclusive": [piece for part in mine for piece in part["own"]],
                  "outermost": [part["interval"] for part in mine if part["outermost"]]}
        open_count = sum(_activity(row) == activity for row in incomplete)
        categories[name] = _category([part["interval"] for part in mine], pieces, open_count, "activity-spans")
        every.extend(_valid([part["interval"] for part in mine]))
    delays = [(item["publishedAt"], row["acceptedAt"]) for item in handoffs["publications"]
              for row in item["acceptances"] if row["delaySeconds"] is not None]
    pending = sum(item["status"] == "awaiting-acceptance" for item in handoffs["publications"])
    categories["publicationToAcceptance"] = _category(
        delays, {"exclusive": delays, "outermost": delays}, pending, "handoff-events")
    union = union_seconds(every + delays)
    exclusive = sum(item["exclusiveSeconds"] or 0.0 for item in categories.values())
    return {"categories": categories, "categorizedUnionSeconds": union,
            "concurrentOverlapSeconds": max(0.0, exclusive - union),
            "scope": "unionSeconds is wall time including nested spans of other categories. "
                     "exclusiveSeconds gives each instant of a nested chain to its innermost "
                     "category, so exclusive times sum to categorizedUnionSeconds plus "
                     "concurrentOverlapSeconds (unrelated categories active at once, counted in "
                     "each). summedSeconds adds concurrent outermost spans (work, not elapsed "
                     "time). Uncategorized time is unattributed, not idle"}
