"""Pure timeline placement and punch-keyframe math for Palmier translation."""
from __future__ import annotations

from dataclasses import dataclass
from math import floor
from motion.punch_in import parse_windows, push_scale_at, ramp_scale_at


class TranslateError(ValueError):
    """The plan uses vocabulary this translator cannot express in Palmier."""


@dataclass(frozen=True)
class Placement:
    """One cutTrack segment on the output timeline (seconds + frames)."""

    index: int
    out_start_s: float
    out_end_s: float
    start_frame: int
    end_frame: int
    source: tuple[float, float]
    speed: float


def build_placements(cut_track: list[dict], fps: float) -> list[Placement]:
    """Map the cutTrack to output-timeline placements (speed-aware)."""
    placements, out_s = [], 0.0
    for index, segment in enumerate(cut_track):
        speed = float(segment.get("speed", 1.0))
        if speed <= 0:
            raise TranslateError(
                f"cutTrack[{index}]: non-positive speed {speed}")
        duration = (float(segment["end"]) - float(segment["start"])) / speed
        if duration <= 0:
            raise TranslateError(f"cutTrack[{index}]: non-positive duration")
        placements.append(Placement(
            index=index, out_start_s=out_s, out_end_s=out_s + duration,
            start_frame=round(out_s * fps),
            end_frame=round((out_s + duration) * fps),
            source=(float(segment["start"]), float(segment["end"])),
            speed=speed))
        out_s += duration
    return placements


def clip_windows(placements: list[Placement], start_s: float,
                 end_s: float) -> list[tuple[int, float, float]]:
    """Intersect an output window with placements into clip-relative spans."""
    spans = []
    for placement in placements:
        lower = max(start_s, placement.out_start_s)
        upper = min(end_s, placement.out_end_s)
        if upper - lower > 1e-9:
            spans.append((placement.index,
                          lower - placement.out_start_s,
                          upper - placement.out_start_s))
    return spans


def top_left(zoom: float, center_x: float,
             center_y: float) -> tuple[float, float]:
    """Return normalized top-left position centering a source point at zoom."""
    def clamp(value: float) -> float:
        return min(0.0, max(1.0 - zoom, value)) if zoom >= 1.0 else value

    return (round(clamp(0.5 - zoom * center_x), 4),
            round(clamp(0.5 - zoom * center_y), 4))


def _composed_state(base: tuple, zoom: float,
                    center_x: float, center_y: float) -> tuple:
    """Compose a punch after the already-applied baseline affine transform."""
    base_zoom, base_cx, base_cy = base
    base_x, base_y = top_left(base_zoom, base_cx, base_cy)
    punch_x, punch_y = top_left(zoom, center_x, center_y)
    return (round(base_zoom * zoom, 4),
            round(zoom * base_x + punch_x, 4),
            round(zoom * base_y + punch_y, 4))


def _envelope_anchors(punch: dict, base: tuple,
                      fps: float) -> list[tuple[float, tuple]]:
    """Global output-time anchors for one complete punch envelope."""
    if punch.get("ramp") is not None:
        return _ramp_anchors(punch, base)
    start, end = float(punch["outStart"]), float(punch["outEnd"])
    attack = max(float(punch.get("attackS", 0.0)), 1.0 / fps)
    release = max(float(punch.get("releaseS", 0.0)), 1.0 / fps)
    release_start = max(start, end - release)
    attack_end = min(start + attack, release_start)
    base_zoom, base_cx, base_cy = base
    zoom = float(punch["zoom"])
    target_cx = float(punch.get("centerX", 0.5))
    target_cy = float(punch.get("centerY", 0.5))
    base_state = (base_zoom, *top_left(base_zoom, base_cx, base_cy))
    target = _composed_state(base, zoom, target_cx, target_cy)
    anchors = [(start, base_state), (attack_end, target)]
    if release_start > attack_end:
        anchors.append((release_start, target))
    if end > release_start:
        anchors.append((end, base_state))
    return anchors


def _ramp_anchors(punch: dict, base: tuple) -> list[tuple[float, tuple]]:
    """Palmier endpoints for a validated smooth aliveness ramp."""
    try:
        (window,) = parse_windows([punch])
    except ValueError as exc:
        raise TranslateError(f"invalid Palmier ramp: {exc}") from exc
    if not window.is_ramp or window.ease != "smooth":
        raise TranslateError(
            "ramp motion requires ease:'smooth' for faithful Palmier keyframes")
    base_zoom, base_cx, base_cy = base
    base_state = (base_zoom, *top_left(base_zoom, base_cx, base_cy))
    peak = max(ramp_scale_at(window, window.out_start),
               ramp_scale_at(window, window.out_end))
    target = _composed_state(
        base, peak, float(punch.get("centerX", 0.5)),
        float(punch.get("centerY", 0.5)))
    states = ((target, base_state) if window.ramp_dir == "out"
              else (base_state, target))
    return [(window.out_start, states[0]), (window.out_end, states[1])]


def _state_at(anchors: list[tuple[float, tuple]], when: float) -> tuple:
    """Smoothly interpolate a punch's property state at one output time."""
    if when <= anchors[0][0]:
        return anchors[0][1]
    for (left_t, left), (right_t, right) in zip(anchors, anchors[1:]):
        if when > right_t:
            continue
        width = right_t - left_t
        progress = 1.0 if width <= 1e-9 else (when - left_t) / width
        eased = progress * progress * (3.0 - 2.0 * progress)
        return tuple(round(a + (b - a) * eased, 4)
                     for a, b in zip(left, right))
    return anchors[-1][1]


def _boundary_rows(punch: dict, base: tuple, fps: float,
                   span: tuple[Placement, float, float]) -> list[tuple]:
    """Slice one global punch envelope into clip-relative keyframe rows."""
    if punch.get("ramp") is not None or punch.get("attackS") is not None:
        return _animated_rows(punch, base, fps, span)
    placement, lower, upper = span
    first = placement.out_start_s + lower
    last = placement.out_start_s + upper
    anchors = _envelope_anchors(punch, base, fps)
    times = [first, *(time for time, _state in anchors
                      if first < time < last), last]
    return [(round((time - placement.out_start_s) * fps),
             *_state_at(anchors, time)) for time in times]


def _animated_rows(punch: dict, base: tuple, fps: float,
                   span: tuple[Placement, float, float]) -> list[tuple]:
    """Sample renderer-equivalent motion at every project frame."""
    try:
        (window,) = parse_windows([punch])
    except (KeyError, TypeError, ValueError) as exc:
        raise TranslateError(f"invalid Palmier motion: {exc}") from exc
    if window.is_ramp and window.ease != "smooth":
        raise TranslateError(
            "ramp motion requires ease:'smooth' for faithful Palmier keyframes")
    placement, lower, upper = span
    first = round((placement.out_start_s + lower) * fps)
    last = round((placement.out_start_s + upper) * fps)
    span_end = placement.out_start_s + upper
    if abs(span_end - window.out_end) <= 1e-6:
        last = max(last, floor(window.out_end * fps) + 1)
    last = min(last, placement.end_frame)
    base_state = (base[0], *top_left(base[0], base[1], base[2]))
    rows = []
    for frame in range(first, last + 1):
        when = frame / fps
        if when > window.out_end + 1e-9:
            state = base_state
        else:
            zoom = (ramp_scale_at(window, when) if window.is_ramp
                    else push_scale_at(window, when))
            state = _composed_state(
                base, zoom, window.center_x, window.center_y)
        rows.append((frame - placement.start_frame, *state))
    return rows


def _validate_nonoverlap(intervals: list[tuple], clip_index: int) -> None:
    """Reject overlapping punch intervals on one clip."""
    for (_, upper, first), (lower, _, second) in zip(intervals, intervals[1:]):
        if upper - lower > 1e-9:
            raise TranslateError(
                f"clip {clip_index}: punchIns[{first}] and "
                f"punchIns[{second}] overlap — resolve in the plan")


def _property_tracks(anchors: list[tuple]) -> dict[str, list[list]]:
    """Convert ordered anchors into Palmier scale and position rows."""
    scale, position, unique = [], [], {}
    for frame, zoom, x, y in sorted(anchors, key=lambda row: row[0]):
        unique[frame] = (zoom, x, y)
    rows = _compact_constant_runs(sorted(unique.items()))
    for frame, (zoom, x, y) in rows:
        scale.append([frame, zoom, zoom, "smooth"])
        position.append([frame, x, y, "smooth"])
    tracks = {"scale": scale}
    if len({tuple(row[1:3]) for row in position}) > 1:
        tracks["position"] = position
    return tracks


def _compact_constant_runs(rows: list[tuple]) -> list[tuple]:
    """Drop redundant hold samples while retaining both hold boundaries."""
    if len(rows) < 3:
        return rows
    kept = [rows[0]]
    for previous, current, following in zip(rows, rows[1:], rows[2:]):
        if current[1] != previous[1] or current[1] != following[1]:
            kept.append(current)
    kept.append(rows[-1])
    return kept


def punch_keyframes(punch_ins: list[dict], placements: list[Placement],
                    base: tuple, fps: float) -> dict[int, dict]:
    """Merge all punches into per-clip scale and position keyframe tracks."""
    per_clip: dict[int, list[tuple]] = {}
    intervals: dict[int, list[tuple]] = {}
    ordered_punches = sorted(enumerate(punch_ins),
                             key=lambda item: float(item[1]["outStart"]))
    for index, punch in ordered_punches:
        unsupported = next((key for key in ("ratePctPerS", "direction", "bracket")
                            if key in punch), None)
        if unsupported:
            raise TranslateError(
                f"punchIns[{index}]: legacy '{unsupported}' motion vocabulary "
                "is not translatable")
        if "zoom" not in punch and "ramp" not in punch:
            raise TranslateError(f"punchIns[{index}]: no zoom — unknown kind")
        if "ramp" not in punch and "attackS" not in punch:
            raise TranslateError(
                f"punchIns[{index}]: static punch hold semantics are not "
                "proven by Palmier readback")
        spans = clip_windows(placements, float(punch["outStart"]),
                             float(punch["outEnd"]))
        if not spans:
            raise TranslateError(
                f"punchIns[{index}]: window {punch['outStart']}→"
                f"{punch['outEnd']} is outside the cut timeline")
        witnessed = False
        for clip_index, lower, upper in spans:
            intervals.setdefault(clip_index, []).append((lower, upper, index))
            placement = placements[clip_index]
            rows = _boundary_rows(
                punch, base, fps, (placement, lower, upper))
            witnessed = witnessed or any(
                abs(row[1] - float(base[0])) > 1e-4 for row in rows)
            per_clip.setdefault(clip_index, []).extend(rows)
        if not witnessed:
            raise TranslateError(
                f"punchIns[{index}]: requested motion has no visible frame")
    result = {}
    for clip_index, anchors in per_clip.items():
        ordered = sorted(intervals[clip_index])
        _validate_nonoverlap(ordered, clip_index)
        result[clip_index] = _property_tracks(anchors)
    return result
