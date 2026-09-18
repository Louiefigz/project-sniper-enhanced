"""Frame-clock and scan validation for qualification evidence."""
from __future__ import annotations


def _rate(value: object, label: str) -> tuple[int, int]:
    if type(value) is not str or "/" not in value:
        raise RuntimeError(f"qualification {label} is malformed")
    parts = value.split("/")
    if (len(parts) != 2 or not all(part.isdigit() for part in parts)
            or int(parts[0]) <= 0 or int(parts[1]) <= 0):
        raise RuntimeError(f"qualification {label} is malformed")
    return int(parts[0]), int(parts[1])


def validate_source_clock(facts: dict) -> None:
    """Require a decoded, zero-based, progressive exact-CFR source clock."""
    frames = facts.get("frames")
    if type(frames) is not int or isinstance(frames, bool) or frames <= 0:
        raise RuntimeError("qualification source frame clock is malformed")
    rate_num, rate_den = _rate(facts.get("rate"), "source rate")
    time_num, time_den = _rate(facts.get("timeBase"), "source time base")
    step_num, step_den = rate_den * time_den, rate_num * time_num
    if step_num % step_den:
        raise RuntimeError("qualification source frame step is not integral")
    step = step_num // step_den
    exact = {
        "firstPts": 0,
        "lastPts": (frames - 1) * step,
        "frameStepPts": step,
        "zeroBasedEpoch": True,
        "progressive": True,
        "decodedProgressiveFrames": frames,
        "rotationDegrees": 0,
    }
    if any(facts.get(key) != value for key, value in exact.items()):
        raise RuntimeError("qualification source frame clock is inconsistent")
    if facts.get("streamFieldOrder") not in {
            "progressive", "unknown", "not-reported"}:
        raise RuntimeError("qualification source scan declaration is inconsistent")


def validate_output_clock(
    video: dict,
    target_frames: int,
    target_fps: int,
) -> None:
    """Require the normalized asset's exact integer frame epoch."""
    exact = {
        "rate": f"{target_fps}/1",
        "timeBase": f"1/{target_fps}",
        "startPts": 0,
        "durationFrames": target_frames,
        "frames": target_frames,
        "firstPts": 0,
        "lastPts": target_frames - 1,
        "frameStepPts": 1,
        "zeroBasedEpoch": True,
        "progressive": True,
        "rotationDegrees": 0,
    }
    if any(video.get(key) != value for key, value in exact.items()):
        raise RuntimeError("qualification output frame clock is inconsistent")
