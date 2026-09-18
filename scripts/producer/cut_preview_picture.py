"""Exact copied-picture time-origin proof, without re-encoding any frame."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from cut_preview_io import MAX_MEDIA, digest, file_hash, run_bounded


def picture_clock(path: Path, ffprobe: str, maximum_media_bytes: int = MAX_MEDIA) -> dict:
    """Observe packet payloads and relative PTS/DTS/durations with bounded rows."""
    before = file_hash(path, maximum_media_bytes)
    result = run_bounded([ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_streams", "-show_packets", "-show_data_hash", "sha256", "-show_entries",
        "stream=start_pts,time_base,r_frame_rate:packet=pts,dts,duration,size,data_hash",
        "-of", "json", str(path)], maximum=32 * 1024 * 1024)
    if result.returncode or result.stderr or len(result.stdout) > 32 * 1024 * 1024:
        raise RuntimeError("cut preview picture-clock observation failed or exceeded its bound")
    document = json.loads(result.stdout)
    streams, packets = document.get("streams", []), document.get("packets", [])
    if len(streams) != 1 or not 0 < len(packets) <= 72000:
        raise RuntimeError("cut preview picture-clock has invalid streams or packet count")
    stream = streams[0]
    origin = int(stream["start_pts"])
    clock, fps = Fraction(stream["time_base"]), Fraction(stream["r_frame_rate"])
    if clock <= 0 or fps <= 0 or abs(origin * clock) > 1 / fps:
        raise RuntimeError("cut preview picture time origin exceeds its one-frame bound")
    rows = [_relative_packet(packet, origin) for packet in packets]
    if min(row["pts"] for row in rows) != 0:
        raise RuntimeError("cut preview picture packet origin disagrees with stream start")
    if before != file_hash(path, maximum_media_bytes):
        raise RuntimeError("cut preview picture changed during packet observation")
    return {"timeBase": stream["time_base"], "frameRate": stream["r_frame_rate"],
            "startPts": origin, "packetCount": len(rows), "relativePacketsHash": digest(rows),
            "fileHash": before}


def _relative_packet(packet: dict, origin: int) -> dict:
    """Keep ordered packet timing and the exact compressed payload digest."""
    import re
    data_hash = packet.get("data_hash")
    if type(data_hash) is not str or not re.fullmatch(r"SHA256:[0-9a-f]{64}", data_hash):
        raise RuntimeError("cut preview picture packet has no payload proof")
    duration, size = int(packet["duration"]), int(packet["size"])
    if duration <= 0 or size <= 0:
        raise RuntimeError("cut preview picture packet duration or size is invalid")
    return {"pts": int(packet["pts"]) - origin, "dts": int(packet["dts"]) - origin,
            "duration": duration, "size": size, "payloadSha256": data_hash[7:]}


def origin_arguments(clock: dict) -> list[str]:
    """Request a bounded origin shift; exact tick preservation is checked afterward."""
    shift = -Fraction(clock["startPts"]) * Fraction(clock["timeBase"])
    return ["-itsoffset", f"{float(shift):.12f}"] if shift else []


def verify_picture_origin(before: dict, after: dict) -> dict:
    """Reject rounding, frame, payload, relative-clock or duration changes."""
    if after["startPts"] != 0 or any(before[key] != after[key] for key in
            ("timeBase", "frameRate", "packetCount", "relativePacketsHash")):
        raise RuntimeError("cut preview copied picture did not preserve exact relative clocks/payloads")
    return {"schemaVersion": 1, "kind": "cut-preview-picture-origin",
            "originalStartPts": before["startPts"], "normalizedStartPts": 0,
            **{key: before[key] for key in ("timeBase", "frameRate", "packetCount", "relativePacketsHash")},
            "beforeFileHash": before["fileHash"], "afterFileHash": after["fileHash"]}
