"""Exact original-picture authority for audio-only delivery publication."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction

from audio.channel_normalization import ChannelNormalizationError
from fingerprints import file_sha256


@dataclass(frozen=True)
class PictureSource:
    """One zero-based CFR source and exact coded-packet presentation evidence."""

    path: str
    sha256: str
    time_base: Fraction
    packets: tuple[tuple, ...]


def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def packet_signature(path: str, selector: str) -> tuple[tuple, ...]:
    """Bind integer PTS and rational time base, not rounded printed seconds."""
    entries = "stream=time_base:packet=pts,duration,data_hash"
    if selector == "a:0":
        entries += ":packet_side_data=side_data_type,skip_samples,discard_padding"
    result = _run(["ffprobe", "-v", "error", "-select_streams", selector,
                   "-show_packets", "-show_data_hash", "sha256",
                   "-show_entries", entries, "-of", "json", path])
    try:
        observed = json.loads(result.stdout)
        time_base = Fraction(observed["streams"][0]["time_base"])
        if time_base <= 0:
            raise ValueError("nonpositive packet time base")
        rows = tuple((int(row["pts"]) * time_base,
                      int(row["duration"]) * time_base if selector == "a:0" else None,
                      row["data_hash"], json.dumps(row.get("side_data_list", []), sort_keys=True))
                     for row in observed["packets"])
    except (IndexError, KeyError, TypeError, ValueError, ZeroDivisionError,
            json.JSONDecodeError) as exc:
        raise ChannelNormalizationError("audio-only packet timeline is unproved") from exc
    if result.returncode or not rows:
        raise ChannelNormalizationError("audio-only packet probe failed")
    return rows


def _video_clock(path: str) -> tuple[Fraction, Fraction]:
    result = _run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                   "-show_streams", "-of", "json", path])
    try:
        row = json.loads(result.stdout)["streams"][0]
        time_base = Fraction(row["time_base"])
        rate, average = Fraction(row["r_frame_rate"]), Fraction(row["avg_frame_rate"])
    except (IndexError, KeyError, TypeError, ValueError, ZeroDivisionError,
            json.JSONDecodeError) as exc:
        raise ChannelNormalizationError("music picture clock is unproved") from exc
    if result.returncode or time_base <= 0 or rate <= 0 or rate != average:
        raise ChannelNormalizationError("music picture must have a proved CFR clock")
    return time_base, rate


def observe_picture_source(path: str, duration: float,
                            sha256: str | None = None) -> PictureSource:
    """Reject unsupported offset/VFR rather than retime to force equality."""
    time_base, rate = _video_clock(path)
    packets = packet_signature(path, "v:0")
    presented = sorted(row[0] for row in packets)
    if presented != [Fraction(index, 1) / rate for index in range(len(packets))]:
        raise ChannelNormalizationError("music picture is nonzero-start or variable-frame-rate")
    if abs(float(len(packets) / rate) - duration) > 0.5 / 48_000:
        raise ChannelNormalizationError("music picture duration does not match its exact frame clock")
    return PictureSource(path, sha256 or file_sha256(path), time_base, packets)


def assert_picture_stable(source: PictureSource) -> None:
    """Ensure the held original picture was not changed during audio work."""
    if file_sha256(source.path) != source.sha256:
        raise ChannelNormalizationError("music original picture bytes changed")


def verify_picture_copy(source: PictureSource, candidate: str) -> dict:
    """Prove native-clock packet identity before the encoded audio can publish."""
    assert_picture_stable(source)
    if packet_signature(candidate, "v:0") != source.packets:
        raise ChannelNormalizationError("music picture packets or exact PTS drifted")
    return {"picturePacketsIdentical": True, "picturePackets": len(source.packets),
            "pictureTimeBase": str(source.time_base), "pictureSourceSha256": source.sha256}
