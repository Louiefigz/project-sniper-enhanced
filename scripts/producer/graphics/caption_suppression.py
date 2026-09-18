#!/usr/bin/env python3
"""Caption-window suppression owned by the graphics composite stage."""

from __future__ import annotations


def _ass_time_to_s(stamp: str) -> float:
    """ASS ``H:MM:SS.cc`` timestamp to seconds."""
    hours, minutes, seconds = stamp.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _overlaps(start: float, end: float,
              windows: list[tuple[float, float]]) -> bool:
    """Whether ``[start, end)`` intersects any suppression window."""
    return any(start < win_end and end > win_start
               for win_start, win_end in windows)


def suppress_captions(ass_in: str, ass_out: str,
                      windows: list[tuple[float, float]]) -> int:
    """Copy ASS while dropping dialogue events overlapping ``windows``."""
    with open(ass_in, encoding="utf-8") as handle:
        lines = handle.readlines()
    kept: list[str] = []
    dropped = 0
    for line in lines:
        if line.startswith("Dialogue:") and windows:
            fields = line.split(":", 1)[1].split(",")
            start = _ass_time_to_s(fields[1])
            end = _ass_time_to_s(fields[2])
            if _overlaps(start, end, windows):
                dropped += 1
                continue
        kept.append(line)
    with open(ass_out, "w", encoding="utf-8") as handle:
        handle.writelines(kept)
    return dropped
