"""Bounded ordinary-plan context coverage, original clocks and local reuse keys."""
from __future__ import annotations

from fractions import Fraction

from cut_preview_io import digest

MAX_SECONDS = 12
CONTEXT_SECONDS = 2


def preparation_key(request: dict) -> str:
    """Only graphic spec/placement revisions may reuse the full prepared base."""
    plan = dict(request["plan"])
    plan.pop("planVersion", None)
    plan["graphicsTrack"] = [{key: value for key, value in row.items()
                              if key not in {"spec", "placement"}}
                             for row in plan.get("graphicsTrack", [])]
    authority = {key: value for key, value in request["packet"]["authority"].items()
                 if key not in {"planHash", "planContentHash", "digest"}}
    return digest({"plan": plan, "authority": authority, "dependencies": request["packet"]["dependenciesHash"],
                   "manifest": request["manifest"],
                   "implementation": request["pins"]})


def _pieces(start: int, end: int, maximum: int) -> list[tuple[int, int]]:
    """Cover the entire requested interval; bounded chunks overlap at boundaries."""
    result = []
    while start < end:
        stop = min(end, start + maximum)
        result.append((start, stop))
        if stop == end:
            break
        start = stop - min(maximum // 4, 30)
    return result


def preview_windows(plan: dict, packet: dict, clock: tuple[str, int]) -> list[dict]:
    """Include start/middle/end plus every graphic with preceding/following context."""
    rate, total = Fraction(clock[0]), clock[1]
    if rate <= 0 or type(total) is not int or total < 2:
        raise ValueError("Ordinary previews need a positive exact frame clock")
    maximum, margin = max(2, int(rate * MAX_SECONDS)), max(1, int(rate * CONTEXT_SECONDS))
    entries, spans = plan.get("graphicsTrack", []), []
    hashes = {unit["id"]: unit["hash"] for unit in packet["units"]}
    for center in (0, total // 2, total):
        spans.append((max(0, center - margin), min(total, center + margin), "plan"))
    for index, row in enumerate(entries):
        start = int(Fraction(str(row["outStart"])) * rate)
        end = -int(-Fraction(str(row["outEnd"])) * rate // 1)
        spans.append((max(0, start - margin), min(total, end + margin), f"graphicsTrack/{index}"))
    combined: dict[tuple[int, int], set[str]] = {}
    for start, end, unit in spans:
        if not 0 <= start < end <= total or unit not in hashes:
            raise ValueError("Ordinary preview coverage has an invalid plan unit")
        for window in _pieces(start, end, maximum):
            combined.setdefault(window, set()).add(unit)
    if len(combined) > 4096:
        raise ValueError("Ordinary preview coverage exceeds its bounded inventory")
    return [{"startFrame": start, "endFrameExclusive": end,
             "units": {unit: hashes[unit] for unit in sorted(units)}}
            for (start, end), units in sorted(combined.items())]


def window_key(window: dict, request: dict, prepared: dict) -> str:
    """Bind media dependencies separately from refreshed whole-plan assessments."""
    rate = Fraction(prepared["frameRate"])
    start, end = window["startFrame"], window["endFrameExclusive"]
    track = [row for row in request["plan"].get("graphicsTrack", [])
             if Fraction(str(row["outStart"])) * rate <= end
             and Fraction(str(row["outEnd"])) * rate >= start]
    # The full base/master key includes all other plan fields and global code/intent.
    return digest({"preparation": prepared["key"], "range": [start, end],
                   "graphics": track, "frameRate": str(rate)})
