#!/usr/bin/env python3
"""plan_refit — remap output-time tracks after a cutTrack edit (deterministic).

A cut edit changes the OUTPUT TIMEBASE: every downstream moment shifts, and
content inside the newly-cut span is simply gone. The graphics / motion /
treatment / audio tracks all carry output-time windows, so a bare cutTrack edit
leaves them pointing at the wrong (or nonexistent) moments — plan_lint then
rightly fails the render. Remapping them is pure arithmetic through the
source↔output map, so CODE owns it (the brain decides WHAT to cut, never does
timeline math — see docs: no LLM arithmetic on pipeline identifiers/timing).

    refit_plan(old_plan, new_plan) -> (refitted_plan, report)

For every entry: old output time → source time (via the OLD cutTrack) → new
output time (via the NEW cutTrack). A window whose start or end fell inside
removed content shrinks to the surviving overlap; an entry whose content is
entirely gone is DROPPED and reported (loudly — nothing disappears silently).

Used by assemble.py --auto-base when a stale base has a base_plan.json snapshot
(the plan the base was rendered from = the old timebase). Also a CLI:

    plan_refit.py <old_plan.json> <new_plan.json> [--write]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys

from compile_timeline import Segment, TimelineMap, compile_plan

_EPS = 1e-3
_MIN_WINDOW_S = 0.15   # a remapped window thinner than this lost its content

# Tracks carrying [outStart, outEnd] windows vs single output-time points.
_WINDOW_TRACKS = ("punchIns", "graphicsTrack", "treatmentMap",
                  "titleCards", "brollTrack", "audioGain", "sfxTrack")
_POINT_TRACKS = {"transitions": "outTime", "chapters": "outStart"}


def emit(**fields) -> None:
    """One NDJSON status line on stdout (matches the render stages)."""
    print(json.dumps(fields), flush=True)


def bump_plan_version(plan: dict) -> dict:
    """Return a copy of ``plan`` with ``planVersion`` incremented.

    The bump is owned by whichever seam WRITES the plan, exactly once per
    write (stale-plan detection: save-plan
    409s, editor reloads, base staleness). The counter is bookkeeping only —
    it is excluded from every base fingerprint (fingerprints._NON_BASE_KEYS)
    and from plan_content_hash, so a bump can never invalidate a base or a
    reviewed-plan authority.
    """
    try:
        current = int(plan.get("planVersion") or 0)
    except (TypeError, ValueError):
        current = 0
    return {**plan, "planVersion": current + 1}


def _mapped_overlap_edge(old_seg: Segment, bounds: tuple[float, float],
                         new: TimelineMap, forward: bool) -> float | None:
    """Map the nearest surviving content within one OLD output segment."""
    src_lo, src_hi = bounds
    best: tuple[float, float] | None = None
    new_segments = new.segments if forward else reversed(new.segments)
    for new_seg in new_segments:
        if new_seg.source_id != old_seg.source_id:
            continue
        overlap_lo = max(src_lo, new_seg.src_start)
        overlap_hi = min(src_hi, new_seg.src_end)
        if overlap_hi <= overlap_lo:
            continue
        t_src = overlap_lo if forward else overlap_hi
        old_out = old_seg.src_to_out(t_src)
        new_out = new_seg.src_to_out(t_src)
        if best is None:
            best = old_out, new_out
            continue
        nearer = ((forward and old_out < best[0]) or
                  (not forward and old_out > best[0]))
        if nearer:
            best = old_out, new_out
    return None if best is None else best[1]


def _walk_kept(t_old: float, old: TimelineMap, new: TimelineMap,
               forward: bool) -> float | None:
    """Walk OLD output order to the next/previous span retained by NEW."""
    origin = next(((i, seg) for i, seg in enumerate(old.segments)
                   if seg.contains_out(t_old)), None)
    if origin is None:
        return None
    origin_i, origin_seg = origin
    origin_src = origin_seg.out_to_src(t_old)
    indices = (range(origin_i, len(old.segments)) if forward
               else range(origin_i, -1, -1))
    for i in indices:
        seg = old.segments[i]
        src_lo = origin_src if forward and i == origin_i else seg.src_start
        src_hi = origin_src if not forward and i == origin_i else seg.src_end
        mapped = _mapped_overlap_edge(seg, (src_lo, src_hi), new, forward)
        if mapped is not None:
            return round(mapped, 4)
    return None


def _next_kept(t_old: float, old: TimelineMap, new: TimelineMap) -> float | None:
    """First kept moment after a removed start, in OLD output order."""
    return _walk_kept(t_old, old, new, True)


def _prev_kept(t_old: float, old: TimelineMap, new: TimelineMap) -> float | None:
    """Last kept moment before a removed end, in OLD output order."""
    return _walk_kept(t_old, old, new, False)


def _remap_start(t: float, old: TimelineMap, new: TimelineMap) -> float | None:
    """Old-output start → new-output start (walks forward over removed spans)."""
    q = min(max(t, 0.0), old.output_duration - _EPS)
    src = old.to_source(q)
    if src is None:
        return None
    mapped = new.to_output(*src)
    return mapped if mapped is not None else _next_kept(q, old, new)


def _remap_end(t: float, old: TimelineMap, new: TimelineMap) -> float | None:
    """Old-output end → new-output end (walks backward over removed spans).

    The query point sits ``_EPS`` inside the window and is NOT compensated on
    the way out: adding ``_EPS`` back would push an end remapped via
    ``_prev_kept`` PAST the next window's ``_next_kept`` start when both
    straddle one removed span (overlapping windows → lint hard-reject). Ends
    may shrink by ≤1ms instead — harmless at 24fps; touching windows stay
    non-overlapping.
    """
    q = min(max(t - _EPS, 0.0), old.output_duration - _EPS)
    src = old.to_source(q)
    if src is None:
        return None
    mapped = new.to_output(*src)
    if mapped is not None:
        # Direct map: restore the queried epsilon so an untouched window is a
        # byte-identical no-op — repeated refits must not shave 1ms per rebuild
        # (observed compounding: every window end drifted x.999 → x.998 → …).
        return min(round(mapped + _EPS, 4), round(new.output_duration, 4))
    out = _prev_kept(q, old, new)   # seam walk: NO eps back (overlap safety)
    return None if out is None else min(round(out, 4), round(new.output_duration, 4))


def _refit_window(entry: dict, old: TimelineMap, new: TimelineMap) -> bool:
    """Rewrite outStart/outEnd in place; False = content gone, drop the entry."""
    s = _remap_start(float(entry["outStart"]), old, new)
    e = _remap_end(float(entry["outEnd"]), old, new)
    if s is None or e is None or e - s < _MIN_WINDOW_S:
        return False
    entry["outStart"], entry["outEnd"] = round(s, 3), round(e, 3)
    return True


def _element_ref(track: str, index: int, entry: dict) -> dict:
    ident = entry.get("id")
    return {"track": track, "index": index,
            **({"elementId": ident} if isinstance(ident, str) else {})}


def refit_plan(old_plan: dict, new_plan: dict) -> tuple[dict, list[dict]]:
    """Remap every output-time track of new_plan from old→new cutTrack timebase.

    Returns the refitted plan (a copy) and a report of changes: one row per
    dropped entry plus a summary row per touched track.
    """
    old, new = compile_plan(old_plan), compile_plan(new_plan)
    plan = copy.deepcopy(new_plan)
    report: list[dict] = []
    for track in _WINDOW_TRACKS:
        entries = plan.get(track) or []
        kept: list[dict] = []
        for i, entry in enumerate(entries):
            if "outStart" not in entry or "outEnd" not in entry:
                kept.append(entry)
                continue
            before = [entry.get("outStart"), entry.get("outEnd")]
            if not _refit_window(entry, old, new):
                report.append({**_element_ref(track, i, entry), "dropped": True,
                               "window": before,
                               "reason": "content removed by the cut edit"})
                continue
            kept.append(entry)
            after = [entry["outStart"], entry["outEnd"]]
            if after != before:
                report.append({**_element_ref(track, i, entry), "remapped": True,
                               "from": before, "to": after})
        if track in plan:
            plan[track] = kept
    for track, field in _POINT_TRACKS.items():
        entries = plan.get(track) or []
        kept = []
        for i, entry in enumerate(entries):
            before_t = entry.get(field)
            t = _remap_start(float(entry.get(field, -1)), old, new)
            if t is None or t >= new.output_duration - _EPS:
                report.append({**_element_ref(track, i, entry), "dropped": True,
                               "at": before_t,
                               "reason": "moment removed by the cut edit"})
                continue
            entry[field] = round(t, 3)
            kept.append(entry)
            if entry[field] != before_t:
                report.append({**_element_ref(track, i, entry), "remapped": True,
                               "from": before_t, "to": entry[field]})
        if track in plan:
            plan[track] = kept
    return plan, report


def main() -> None:
    ap = argparse.ArgumentParser(description="refit output-time tracks after a cut edit")
    ap.add_argument("old_plan", help="plan the current base/render was built from")
    ap.add_argument("new_plan", help="edited plan (new cutTrack, old window times)")
    ap.add_argument("--write", action="store_true",
                    help="write the refitted plan back over new_plan")
    args = ap.parse_args()
    try:
        with open(args.old_plan) as f:
            old_plan = json.load(f)
        with open(args.new_plan) as f:
            new_plan = json.load(f)
        plan, report = refit_plan(old_plan, new_plan)
        for row in report:
            emit(status="refit", **row)
        if args.write:
            # NO version bump here: every CLI caller (save-plan cut-only saves,
            # ai-edit finalize) already bumped planVersion before staging the
            # refit input — a second bump here double-counted (planVersion 1→3
            # on one save). Python callers that own the write bump explicitly
            # via bump_plan_version (assemble._refit_for_rebuild).
            with open(args.new_plan, "w") as f:
                json.dump(plan, f, indent=1)
        emit(status="done", changes=len(report), written=bool(args.write))
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        emit(error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
