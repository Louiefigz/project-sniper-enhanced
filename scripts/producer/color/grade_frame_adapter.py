"""Strict pinned ffprobe text adapter; no execution or admission inferred here.

Every raw decoded record is retained. Only known metadata fields are mapped;
missing exact PTS/duration/color or unrecognized side data is unsupported.
Unavailable AVFrame corruption flags remain None, never invented zeroes.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from color.grade_source_class import ERROR_POLICY, SourceFrameValidator, SourceRecordValidation
from color.grade_observation_geometry import chroma_location, sample_aspect_ratio, source_metadata
from color.grade_observation_profile import V2, observation_profile
from graphics.render_rate import normalize_render_rate

_FIELDS = {"media_type", "stream_index", "key_frame", "pkt_pts", "pkt_pts_time",
    "pkt_dts", "pkt_dts_time", "best_effort_timestamp", "best_effort_timestamp_time",
    "pkt_duration", "pkt_duration_time", "pkt_pos", "pkt_size", "width", "height",
    "pix_fmt", "sample_aspect_ratio", "pict_type", "coded_picture_number",
    "display_picture_number", "interlaced_frame", "top_field_first", "repeat_pict",
    "color_range", "color_space", "color_primaries", "color_transfer", "chroma_location"}
_COLOR_FIELDS = {"pixelFormat": "pix_fmt", "range": "color_range", "matrix": "color_space",
                 "primaries": "color_primaries", "transfer": "color_transfer"}
_SEI = "H.26[45] User Data Unregistered SEI message"


def _integer(value: object) -> int:
    """Never infer a missing timestamp or round a floating media clock."""
    if type(value) is int and abs(value) < 2 ** 53:
        return value
    if type(value) is not str or not re.fullmatch(r"-?(?:0|[1-9][0-9]{0,15})", value):
        raise ValueError("grade decoded integer is missing or invalid")
    parsed = int(value)
    if abs(parsed) >= 2 ** 53:
        raise ValueError("grade decoded integer exceeds exact clock bounds")
    return parsed


def _color(row: dict) -> dict:
    """Preserve absent fields; the class validator must reject them."""
    result = {key: row.get(field) for key, field in _COLOR_FIELDS.items()}
    side = row.get("side_data_list", [])
    if type(side) is not list or len(side) > 16:
        raise ValueError("grade source side metadata is malformed")
    if any(type(item) is not dict or set(item) != {"side_data_type"}
           or item["side_data_type"] != _SEI for item in side):
        raise ValueError("grade source has unsupported or HDR side metadata")
    result["hdrSignaled"] = result["transfer"] in ("smpte2084", "arib-std-b67")
    return result


def frame_records(lines: Iterable[str]) -> Iterator[dict]:
    """Parse the pinned wrapper format in constant memory with closed nesting."""
    frame, side = None, None
    for raw in lines:
        if type(raw) is not str or len(raw) > 32768 or not raw.endswith("\n"):
            raise ValueError("grade raw decoder line is oversized or truncated")
        line = raw[:-1]
        if line == "[FRAME]" and frame is None:
            frame = {"side_data_list": []}
        elif line == "[SIDE_DATA]" and frame is not None and side is None:
            side = {}
        elif line == "[/SIDE_DATA]" and side is not None:
            if set(side) != {"side_data_type"} or len(frame["side_data_list"]) >= 16:
                raise ValueError("grade side metadata is missing or over budget")
            frame["side_data_list"].append(side)
            side = None
        elif line == "[/FRAME]" and frame is not None and side is None:
            yield frame
            frame = None
        elif line and not line.startswith("[") and frame is not None:
            target = side if side is not None else frame
            key, marker, value = line.partition("=")
            permitted = {"side_data_type"} if side is not None else _FIELDS
            if not marker or key not in permitted or key in target or len(value) > 4096:
                raise ValueError("grade decoded field is unknown, duplicated or oversized")
            target[key] = value
        else:
            raise ValueError("grade decoder wrapper structure is malformed")
    if frame is not None or side is not None:
        raise ValueError("grade decoded record was truncated before EOF")


def observed_stream(probe: dict, binding: dict, first: dict, profile: str | None = None) -> dict:
    """Derive the exact stream descriptor; per-frame checks prove progressive."""
    streams = probe.get("streams")
    if type(streams) is not list or len(streams) > 32:
        raise ValueError("grade probe streams are missing or over budget")
    video = [row for row in streams if type(row) is dict and row.get("codec_type") == "video"]
    if len(video) != 1:
        raise ValueError("grade requires exactly one video stream")
    row = video[0]
    fps = normalize_render_rate(row.get("avg_frame_rate")).token
    if normalize_render_rate(row.get("r_frame_rate")).token != fps or fps != binding["fps"]:
        raise ValueError("grade source stream rates are inconsistent")
    first_pts = _integer(first.get("pkt_pts"))
    if _integer(row.get("start_pts")) != first_pts:
        raise ValueError("grade source PTS origin differs from its first decoded frame")
    extra = {"sourceMetadata": source_metadata(row, first)} if observation_profile(profile) is V2 else {}
    return {**_color(row), **extra, "videoStreamCount": 1, "streamIndex": _integer(row.get("index")),
        "fps": fps, "timeBase": row.get("time_base"), "firstPts": first_pts,
        "frameCount": _integer(row.get("nb_frames")), "width": _integer(row.get("width")),
        "height": _integer(row.get("height")), "progressive": True}


def normalized_frame(row: dict, index: int, profile: str | None = None) -> dict:
    """No conversion before classification; missing decoder flags stay unknown."""
    if row.get("media_type") != "video":
        raise ValueError("grade record is not a decoded video frame")
    pts = _integer(row.get("pkt_pts"))
    if _integer(row.get("best_effort_timestamp")) != pts:
        raise ValueError("grade source requires original non-synthesized exact PTS")
    extra = {"chromaLocation": chroma_location(row.get("chroma_location")),
             "sampleAspectRatio": sample_aspect_ratio(row.get("sample_aspect_ratio"))} \
        if observation_profile(profile) is V2 else {}
    return {**_color(row), **extra, "index": index, "streamIndex": _integer(row.get("stream_index")),
        "pts": pts, "durationTicks": _integer(row.get("pkt_duration")),
        "width": _integer(row.get("width")), "height": _integer(row.get("height")),
        "interlaced": _integer(row.get("interlaced_frame")) != 0,
        "repeatPict": _integer(row.get("repeat_pict")), "corrupt": None, "decodeErrorFlags": None}


def validate_records(context: tuple[dict, dict, dict], lines: Iterable[str],
                     terminal: dict, profile: str | None = None) -> SourceRecordValidation:
    """Validate all supplied records; only external execution proof authenticates them."""
    binding, declaration, probe = context
    records = frame_records(lines)
    first = next(records, None)
    if first is None:
        raise ValueError("grade source has no decoded frames")
    scanner = SourceFrameValidator(binding, declaration, observed_stream(probe, binding, first, profile), profile)
    scanner.add_frame(normalized_frame(first, 0, profile))
    for index, row in enumerate(records, start=1):
        scanner.add_frame(normalized_frame(row, index, profile))
    return finish_records(scanner, terminal, binding)


def finish_records(scanner: SourceFrameValidator, terminal: dict, binding: dict) -> SourceRecordValidation:
    """Share the unchanged strict terminal contract with opt-in metadata readers."""
    if terminal.get("reachedEof") is not True or type(terminal.get("exitCode")) is not int \
            or terminal.get("exitCode") != 0 or type(terminal.get("stderrBytes")) is not int \
            or type(terminal.get("frames")) is not int \
            or terminal.get("signal") is not None or terminal.get("stderr") != "" \
            or terminal.get("stderrBytes") != 0 or terminal.get("frames") != binding["frameCount"] \
            or terminal.get("perFrameCorruptFlag") != "unavailable" \
            or terminal.get("perFrameDecodeErrorFlags") != "unavailable":
        raise ValueError("grade requires exact clean warning-free decoder completion")
    return scanner.finish({"source": binding, "reachedEof": True, "decoderExitCode": 0,
        "decoderErrorCount": 0, "decoderWarningCount": 0, "decoderErrorObservationPolicy": ERROR_POLICY})
