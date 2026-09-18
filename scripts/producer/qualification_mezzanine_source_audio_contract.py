"""Source-audio program-clock validation for qualification evidence."""
from __future__ import annotations


def _rate(value: object) -> tuple[int, int]:
    parts = value.split("/") if type(value) is str else []
    if (len(parts) != 2 or not all(part.isdigit() for part in parts)
            or int(parts[0]) <= 0 or int(parts[1]) <= 0):
        raise RuntimeError("qualification source rate is malformed")
    return int(parts[0]), int(parts[1])


def _integer(value: object, label: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise RuntimeError(f"qualification {label} is malformed")
    return value


def validate_source_audio(facts: dict) -> None:
    """Require contiguous decoded PCM coverage from the zero epoch."""
    audio = facts.get("sourceAudio")
    if type(audio) is not dict:
        raise RuntimeError("qualification source audio authority is missing")
    keys = {
        "codec", "sampleRate", "channels", "timeBase", "firstPts",
        "lastPts", "lastEndPts", "timelineSamplesPerChannel",
        "decodedSamplesPerChannel", "durationSeconds",
        "videoDurationDeltaSeconds",
        "absoluteVideoDeltaWithinOneSourceFrame", "contiguousFromZero",
    }
    if set(audio) != keys:
        raise RuntimeError("qualification source audio authority is malformed")
    samples = _integer(
        audio.get("timelineSamplesPerChannel"), "source audio samples")
    decoded = _integer(
        audio.get("decodedSamplesPerChannel"), "decoded source audio samples")
    last_pts = _integer(audio.get("lastPts"), "source audio last PTS")
    last_end = _integer(audio.get("lastEndPts"), "source audio end PTS")
    rate_num, rate_den = _rate(facts.get("rate"))
    video_duration = facts["frames"] * rate_den / rate_num
    duration, delta = samples / 48000, samples / 48000 - video_duration
    maximum = rate_den / rate_num
    valid = (
        str(audio.get("codec", "")).startswith("pcm_")
        and audio.get("codec") == facts.get("audioCodec")
        and audio.get("sampleRate") == 48000
        and str(audio.get("sampleRate")) == facts.get("audioSampleRate")
        and audio.get("channels") == 2
        and audio.get("channels") == facts.get("audioChannels")
        and audio.get("timeBase") == "1/48000"
        and audio.get("firstPts") == 0
        and 0 <= last_pts < last_end == samples
        and decoded == samples
        and abs(audio.get("durationSeconds", -1) - duration) < 1e-9
        and abs(audio.get("videoDurationDeltaSeconds", 1e9) - delta) < 1e-9
        and abs(delta) <= maximum
        and audio.get("absoluteVideoDeltaWithinOneSourceFrame") is True
        and audio.get("contiguousFromZero") is True
    )
    if not valid:
        raise RuntimeError("qualification source audio clock is inconsistent")
