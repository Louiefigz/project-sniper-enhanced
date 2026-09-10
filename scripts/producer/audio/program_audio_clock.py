"""Exact float-program and AAC presentation clocks, separate from loudness.

The source bus owns the cumulative executed-frame-to-sample mapping. These
checks observe that existing mapping; they never round each cut independently
or infer edit boundaries from codec/container duration. PCM has no tolerated
sample debt. AAC presentation must be exact, while decoded trailing padding
is reported separately and bounded to one encoder frame.
"""
from __future__ import annotations

import json
import re
from fractions import Fraction

from audio.render_audio_authority import run_audio
from audio.render_audio_bus import SourceAudioBus


def float_audio_clock(path: str, bus: SourceAudioBus) -> dict:
    """Reject integer PCM, missing audio or any departure from executed samples."""
    return exact_float_audio_clock(path, bus.admission.tools["ffprobe"]["path"], bus.samples)


def exact_float_audio_clock(path: str, probe: str, samples: int) -> dict:
    """Observe a proved sample-count requirement without inventing source authority."""
    if type(samples) is not int or samples < 1:
        raise RuntimeError("float audio expected sample count must be positive")
    document = json.loads(run_audio([probe, "-v", "error",
        "-show_streams", "-of", "json", path]))
    streams = document.get("streams", [])
    if len(streams) != 1:
        raise RuntimeError("full-program master must have exactly one float audio stream")
    row = streams[0]
    count = Fraction(row["duration_ts"]) * Fraction(row["time_base"]) * 48000
    if row.get("codec_name") != "pcm_f32le" or row.get("sample_fmt") != "flt" \
            or row.get("sample_rate") != "48000" or row.get("channels") != 2 \
            or row.get("time_base") != "1/48000" or count != samples \
            or row.get("start_pts", 0) != 0:
        raise RuntimeError("full-program float format or exact sample count differs")
    return {"codec": "pcm_f32le", "sampleFormat": "flt", "sampleRate": 48000,
        "channels": 2, "startPts": 0, "timeBase": "1/48000", "samples": int(count)}


def aac_audio_clock(path: str, bus: SourceAudioBus) -> dict:
    """Prove AAC presentation separately from explicitly bounded decoded padding."""
    return exact_aac_audio_clock(path, bus.admission.tools["ffprobe"]["path"], bus.samples)


def exact_aac_audio_clock(path: str, probe: str, expected_samples: int) -> dict:
    """Check actual presentation of an independently proved absolute PCM range."""
    if type(expected_samples) is not int or expected_samples < 1:
        raise RuntimeError("AAC expected sample count must be positive")
    document = json.loads(run_audio([probe, "-v", "error", "-select_streams", "a",
        "-show_streams", "-show_packets", "-show_entries",
        "packet=pts,dts,duration,side_data_list:packet_side_data=side_data_type,skip_samples,discard_padding",
        "-of", "json", path]))
    audios = [row for row in document["streams"] if row.get("codec_type") == "audio"]
    if len(audios) != 1:
        raise RuntimeError("source-float final is missing its one delivery audio stream")
    audio = audios[0]
    count = Fraction(audio["duration_ts"]) * Fraction(audio["time_base"]) * 48000
    if audio.get("codec_name") != "aac" or audio.get("sample_rate") != "48000" \
            or audio.get("channels") != 2 or int(audio.get("start_pts", -1)) != 0 \
            or audio.get("time_base") != "1/48000" or count != expected_samples:
        raise RuntimeError(f"source-float AAC presentation differs from retained samples: {count} vs {expected_samples}")
    packets = aac_packet_clock(document.get("packets"), expected_samples)
    decoded = run_audio([probe, "-v", "error", "-select_streams", "a:0", "-show_frames",
                         "-show_entries", "frame=nb_samples", "-of", "csv=p=0", path])
    samples = sum(int(line) for line in decoded.decode().splitlines() if line.strip())
    if not 0 <= samples - expected_samples <= 1023:
        raise RuntimeError("source-float final AAC decoded padding exceeds one codec frame")
    return {"sampleRate": 48000, "channels": 2, "codec": "aac", "startPts": 0,
            "timeBase": audio["time_base"], "presentedSamples": int(count),
            "decodedSamples": samples, "trailingPaddingSamples": samples - expected_samples,
            "packetClock": packets}


def _packet_integer(row: dict, key: str) -> int:
    """Accept only explicit integer probe facts, never booleans or rounded floats."""
    value = row.get(key)
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    raise RuntimeError(f"AAC packet has no exact integer {key}")


def _packet_skip(row: dict) -> int:
    """Require bounded, unambiguous AAC priming metadata without hidden discard."""
    sides = row.get("side_data_list", [])
    if not isinstance(sides, list) or any(not isinstance(side, dict) for side in sides):
        raise RuntimeError("AAC packet side-data is malformed")
    skip_rows = [side for side in sides if side.get("side_data_type") == "Skip Samples"
                 or "skip_samples" in side or "discard_padding" in side]
    if len(skip_rows) > 1:
        raise RuntimeError("AAC packet has ambiguous duplicate priming metadata")
    if not skip_rows:
        return 0
    side = skip_rows[0]
    skip, discard = _packet_integer(side, "skip_samples"), _packet_integer(side, "discard_padding")
    if not 0 <= skip <= 1024 or discard != 0:
        raise RuntimeError("AAC priming/discard metadata is unsupported")
    return skip


def aac_packet_clock(packets: list[dict] | None, expected_samples: int) -> dict:
    """Prove every AAC packet's clock before ordinary delivery can be promoted."""
    if type(expected_samples) is not int or expected_samples < 1:
        raise RuntimeError("AAC expected sample count must be positive")
    if not isinstance(packets, list) or not packets or any(not isinstance(row, dict) for row in packets):
        raise RuntimeError("AAC packet clock evidence is missing")
    first = _packet_integer(packets[0], "pts")
    if not -1024 <= first <= 0:
        raise RuntimeError("AAC coded start is outside the supported priming range")
    expected_pts = first
    for index, row in enumerate(packets):
        pts, duration = _packet_integer(row, "pts"), _packet_integer(row, "duration")
        if pts != expected_pts or _packet_integer(row, "dts") != pts:
            raise RuntimeError("AAC packet gap, overlap or decode-clock mismatch")
        if not 0 < duration <= 1024:
            raise RuntimeError("AAC packet duration is outside one codec frame")
        if index < len(packets) - 1 and duration != 1024:
            raise RuntimeError("AAC interior packet must span its full1024-sample codec frame")
        if _packet_skip(row) != (-first if index == 0 else 0):
            raise RuntimeError("AAC skip metadata disagrees with presentation start")
        expected_pts = pts + duration
    if expected_pts != expected_samples:
        raise RuntimeError("AAC packet endpoint differs from the exact program clock")
    return {"allPacketsChecked": True, "packetCount": len(packets), "codedStartSample": first,
            "leadingSkipSamples": -first, "endSampleExclusive": expected_pts,
            "gapOverlapFree": True, "decodeClockMatchesPresentation": True}
