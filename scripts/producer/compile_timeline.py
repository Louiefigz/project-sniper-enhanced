#!/usr/bin/env python3
"""compile_timeline — the source↔output time map (the correctness keystone).

Word timestamps live in SOURCE time; captions, title cards, b-roll windows and
operator feedback live in OUTPUT time — after cuts AND per-range speed changes.
This module compiles ``edit_plan.cutTrack`` into an ordered list of render
segments plus a piecewise-linear bidirectional map between the two timelines.
Everything downstream (caption placement, overlay enable windows, audit
reporting, feedback resolution) MUST go through this map — never hand-derived
offsets. See docs/producer/PRODUCER_PLAN.md §4.1.

CLI: compile_timeline.py <edit_plan.json> <timeline_map.json-out>
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass

from producer_config import AUDIO

_JCUT = AUDIO["jcut"]


@dataclass(frozen=True)
class Segment:
    """One kept range of one source, placed on the output timeline.

    Within a segment the mapping is linear:
    ``t_out = out_start + (t_src - src_start) / speed``.

    ``audio_lead_s`` (J-cut, LIAM move 2 — additive, default 0 = today's
    joins): this segment's audio PRE-ROLL (source audio from before
    ``src_start``) begins this many OUTPUT seconds before its picture cut.
    It does NOT affect the source↔output picture map — cut_speed bakes the
    lead into the previous part's audio tail.
    """

    index: int
    source_id: str
    src_start: float
    src_end: float
    speed: float
    out_start: float
    out_end: float
    audio_lead_s: float = 0.0

    def src_to_out(self, t_src: float) -> float:
        """Map a source-time instant inside this segment to output time."""
        return self.out_start + (t_src - self.src_start) / self.speed

    def out_to_src(self, t_out: float) -> float:
        """Map an output-time instant inside this segment back to source time."""
        return self.src_start + (t_out - self.out_start) * self.speed

    def contains_src(self, source_id: str, t_src: float) -> bool:
        """True if ``t_src`` of ``source_id`` lies in this segment's source range."""
        return source_id == self.source_id and self.src_start <= t_src <= self.src_end

    def contains_out(self, t_out: float) -> bool:
        """True if ``t_out`` lies in this segment's output range."""
        return self.out_start <= t_out <= self.out_end


class TimelineMap:
    """Piecewise-linear bidirectional source↔output time mapping."""

    def __init__(self, segments: list[Segment]) -> None:
        self.segments = segments

    @property
    def output_duration(self) -> float:
        """Total output length: the last segment's ``out_end`` (0.0 if empty)."""
        return self.segments[-1].out_end if self.segments else 0.0

    def to_output(self, source_id: str, t_src: float) -> float | None:
        """Map a source-time instant to output time.

        Returns None when the instant was cut out (falls in no kept range).
        On boundaries the earliest containing segment wins.
        """
        for seg in self.segments:
            if seg.contains_src(source_id, t_src):
                return round(seg.src_to_out(t_src), 4)
        return None

    def to_source(self, t_out: float) -> tuple[str, float] | None:
        """Map an output-time instant back to ``(source_id, source_time)``.

        This is what turns operator feedback ("at 0:14...") into the source
        range the brain must revise. Returns None past the end of the video.
        """
        for seg in self.segments:
            if seg.contains_out(t_out):
                return seg.source_id, round(seg.out_to_src(t_out), 4)
        return None

    def to_dict(self) -> dict:
        """Serialize the map (output duration + segments) to a plain dict."""
        return {
            "outputDuration": round(self.output_duration, 4),
            "segments": [asdict(s) for s in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TimelineMap":
        """Rebuild a ``TimelineMap`` from :meth:`to_dict` output.

        ``audio_lead_s`` is additive: maps serialized before the J-cut field
        existed rebuild with 0.0 (today's joins).
        """
        segs = [Segment(**{k: s[k] for k in (
            "index", "source_id", "src_start", "src_end",
            "speed", "out_start", "out_end")},
            audio_lead_s=float(s.get("audio_lead_s", 0.0)))
            for s in data["segments"]]
        return cls(segs)


def parse_audio_lead(i: int, rng: dict, geom: tuple[float, float],
                     prev_out_len: float) -> float:
    """Validate ``cutTrack[i].audioLeadMs`` → lead SECONDS (0.0 when absent).

    The J-cut contract (LIAM move 2; bands in ``AUDIO["jcut"]``): a lead is
    only legal on a segment with an incoming seam (never the first), within
    (0, ``lead_max_ms``], with real source audio before the in-point
    (``start >= lead_s * speed``) and enough previous-part audio to give up
    (``prev_out_len - lead_s >= prev_min_residual_s``). This is the SINGLE
    validator — plan_lint calls it too, so lint and renderer cannot drift.
    """
    ms = rng.get("audioLeadMs")
    if ms is None:
        return 0.0
    if isinstance(ms, bool) or not isinstance(ms, (int, float)):
        raise ValueError(f"cutTrack[{i}]: audioLeadMs must be a number in "
                         f"(0,{_JCUT['lead_max_ms']}]")
    if i == 0:
        raise ValueError("cutTrack[0]: audioLeadMs on the first segment — "
                         "there is no incoming seam for its audio to lead")
    if not (0.0 < float(ms) <= _JCUT["lead_max_ms"]):
        raise ValueError(f"cutTrack[{i}]: audioLeadMs {ms} outside "
                         f"(0,{_JCUT['lead_max_ms']}]ms (measured hard edge "
                         "~300ms onset lag)")
    lead_s = float(ms) / 1000.0
    start, speed = geom
    if start - lead_s * speed < 0.0:
        raise ValueError(f"cutTrack[{i}]: audioLeadMs {ms} needs "
                         f"{lead_s * speed:.3f}s of source audio before the "
                         f"in-point {start:.3f}s — none exists")
    if prev_out_len - lead_s < _JCUT["prev_min_residual_s"]:
        raise ValueError(f"cutTrack[{i}]: audioLeadMs {ms} leaves the "
                         f"previous {prev_out_len:.2f}s part under "
                         f"{_JCUT['prev_min_residual_s']}s of its own audio")
    return lead_s


def compile_plan(plan: dict) -> TimelineMap:
    """Compile ``plan.cutTrack`` (ordered, multi-source) into a TimelineMap.

    The cut track's order IS the output order. Raises ValueError on malformed
    ranges (incl. an illegal ``audioLeadMs`` J-cut lead) — but plans are
    expected to have passed plan_lint first.
    """
    segments: list[Segment] = []
    cursor = 0.0
    prev_out_len = 0.0
    for i, r in enumerate(plan.get("cutTrack") or []):
        start, end = float(r["start"]), float(r["end"])
        speed = float(r.get("speed", 1.0)) or 1.0
        if end <= start:
            raise ValueError(f"cutTrack[{i}]: end <= start")
        out_len = (end - start) / speed
        segments.append(Segment(
            index=i,
            source_id=str(r["sourceId"]),
            src_start=start,
            src_end=end,
            speed=speed,
            out_start=round(cursor, 4),
            out_end=round(cursor + out_len, 4),
            audio_lead_s=parse_audio_lead(i, r, (start, speed), prev_out_len),
        ))
        cursor += out_len
        prev_out_len = out_len
    return TimelineMap(segments)


def predicted_duration_s(plan: dict) -> float:
    """Self-check value: renderer output must match this within ±1 frame."""
    return compile_plan(plan).output_duration


def remap_words(words: list[dict], source_id: str, tmap: TimelineMap) -> list[dict]:
    """Remap word timings from one source into output time.

    Words cut out of the edit are dropped. A word whose start survives but
    whose end crosses a cut boundary is clamped to its segment's end — that
    word IS audible until the cut. A word whose KEPT span is zero is dropped:
    ``contains_src`` is edge-inclusive, so a word cut out EXACTLY at its own
    boundaries still "starts" on a seam — without this check it ghosts into
    the captions as a zero-length word (found via the editor's strike-to-cut).
    Duplicate-safe: purely functional.
    """
    out: list[dict] = []
    for w in words:
        seg = next((s for s in tmap.segments
                    if s.contains_src(source_id, float(w["start"]))), None)
        if seg is None:
            continue
        start_out = seg.src_to_out(float(w["start"]))
        end_src = min(float(w["end"]), seg.src_end)
        if end_src <= float(w["start"]) + 1e-6:   # nothing of it is audible
            continue
        out.append({**w,
                    "start": round(start_out, 4),
                    "end": round(seg.src_to_out(end_src), 4)})
    return out


def main() -> None:
    if len(sys.argv) != 3:
        print(json.dumps({"error": "Usage: compile_timeline.py <edit_plan.json> <out.json>"}))
        sys.exit(1)
    try:
        with open(sys.argv[1]) as f:
            plan = json.load(f)
        tmap = compile_plan(plan)
        with open(sys.argv[2], "w") as f:
            json.dump(tmap.to_dict(), f, indent=2)
        print(json.dumps({"status": "done",
                          "segments": len(tmap.segments),
                          "outputDuration": round(tmap.output_duration, 3)}))
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
