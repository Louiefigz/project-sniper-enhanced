"""Time-stratified samples over kept source/lighting groups, including late clips."""
from __future__ import annotations

import math

from compile_timeline import Segment, compile_plan
from color.model import MAX_GROUPS, context, finite, unknown_context


def _pieces(segment: Segment, groups: list[dict], fps: float) -> list[dict]:
    """Split kept picture only, retaining unclassified gaps instead of guessing."""
    points = {segment.src_start, segment.src_end}
    for group in groups:
        points.update(max(segment.src_start, min(segment.src_end, group[key]))
                      for key in ("start", "end"))
    ordered, result = sorted(points), []
    for start, end in zip(ordered, ordered[1:]):
        if end <= start:
            continue
        group = next((row for row in groups if row["start"] <= start and end <= row["end"]), None)
        result.append({"cutIndex": segment.index, "sourceStart": start, "sourceEnd": end,
                       "outStart": segment.src_to_out(start), "outEnd": segment.src_to_out(end),
                       "sourceFrameDurationS": 1 / fps,
                       "samplingInsetOutS": max(0.05, 1 / fps / segment.speed),
                       "groupId": group["id"] if group else "unclassified",
                       "intent": group["intent"] if group else "unknown"})
    return result


def _collect(plan: dict, sources: list[dict], contexts: list[dict]) -> list[dict]:
    """Collect compiler-bound source pieces, retaining unclassified gaps."""
    available = {row["id"]: row for row in sources}
    supplied = {row.get("sourceId"): row for row in contexts if type(row) is dict}
    if len(supplied) != len(contexts) or set(supplied) - set(available):
        raise ValueError("color contexts repeat or name unavailable sources")
    declared = {key: context(supplied[key], row) if key in supplied else unknown_context(row)
                for key, row in available.items()}
    groups = {}
    for segment in compile_plan(plan).segments:
        source = available.get(segment.source_id)
        if source is None or not finite(source.get("duration")) \
                or not finite(source.get("fps")) or source["fps"] <= 0 \
                or not 0 <= segment.src_start < segment.src_end <= source["duration"]:
            raise ValueError("color retained interval exceeds its admitted source")
        for piece in _pieces(segment, declared[source["id"]]["lightingGroups"], source["fps"]):
            key = (source["id"], piece["groupId"])
            row = groups.setdefault(key, {"sourceId": key[0], "groupId": key[1],
                                         "context": declared[key[0]], "intent": piece["intent"],
                                         "retainedIntervals": []})
            row["retainedIntervals"].append(piece)
    return list(groups.values())


def _point(pieces: list[dict], kept_time: float) -> tuple[int, float, float]:
    """Map cumulative kept time via the compiler-derived affine segment."""
    for index, row in enumerate(pieces):
        length = row["outEnd"] - row["outStart"]
        if kept_time < length or index == len(pieces) - 1:
            inset = min(row["samplingInsetOutS"], length / 4)
            local = max(inset, min(length - inset, kept_time))
            ratio = local / length
            source = row["sourceStart"] + ratio * (row["sourceEnd"] - row["sourceStart"])
            return index, source, row["outStart"] + local
        kept_time -= length
    raise ValueError("color sample has no retained interval")


def _sample_group(group: dict, count: int) -> dict:
    """Distribute samples over the whole kept group and expose missed shots."""
    pieces = group["retainedIntervals"]
    duration = sum(row["outEnd"] - row["outStart"] for row in pieces)
    samples = []
    for index in range(count):
        interval, source, output = _point(pieces, duration * index / (count - 1))
        row = pieces[interval]
        samples.append({"id": f"{group['sourceId']}:{group['groupId']}:{index}",
                        "sourceId": group["sourceId"], "groupId": group["groupId"],
                        "sourceTime": round(source, 6), "outputTime": round(output, 6),
                        "sourceStart": row["sourceStart"], "sourceEnd": row["sourceEnd"],
                        "maximumSeekDeltaS": max(0.05, row["sourceFrameDurationS"] + 0.001),
                        "intervalIndex": interval})
    visited = {row["intervalIndex"] for row in samples}
    return {**group, "samples": samples, "retainedDurationS": round(duration, 6),
            "unsampledIntervalIndices": sorted(set(range(len(pieces))) - visited),
            "coverageClaim": "time-stratified samples; not every frame or every shot"}


def build_sample_plan(plan: dict, sources: list[dict], contexts: list[dict], budget: int) -> dict:
    """Guarantee first/middle/late group samples or reject an insufficient budget."""
    groups = _collect(plan, sources, contexts)
    if not groups or len(groups) > MAX_GROUPS or len(groups) * 5 > budget:
        raise ValueError("color sample budget cannot cover all source/lighting groups with five strata")
    durations = [sum(row["outEnd"] - row["outStart"] for row in group["retainedIntervals"])
                 for group in groups]
    counts = [5] * len(groups)
    targets = [max(5, math.ceil(duration / 30) + 1) for duration in durations]
    while sum(counts) < budget and any(a < b for a, b in zip(counts, targets)):
        index = max((i for i in range(len(groups)) if counts[i] < targets[i]),
                    key=lambda i: durations[i] / counts[i])
        counts[index] += 1
    rows = [_sample_group(group, count) for group, count in zip(groups, counts)]
    return {"strategy": "retained-time-stratified-v1", "sampleBudget": budget,
            "plannedSamples": sum(counts), "groups": rows,
            "brollPolicy": "primary retained source footage only; b-roll not diagnosed"}
