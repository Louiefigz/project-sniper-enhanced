"""Strict neutral stream/decoded-frame metadata for the first presenter class."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

from graphics.presenter_layout_contract import MAX_FRAMES
from graphics.presenter_layout_graph import PresenterGraphAsset
from guided_presenter_assets import PresenterAssetAdmission, SelectedPresenterAsset
from opening_prefix_contract import valid_canvas

MAX_HEADER_BYTES = 256 * 1024
MAX_FRAME_BYTES = 16 * 1024 * 1024
_COLORS = ("color_range", "color_space", "color_primaries", "color_transfer")
_SEI = "H.26[45] User Data Unregistered SEI message"
_VIDEO_COLOR = ("tv", "bt709", "bt709", "bt709")
_STILL_COLOR = ("pc", "gbr", "bt709", "iec61966-2-1")


@dataclass(frozen=True)
class PresenterProbeHeader:
    """Strict stream facts; final progressive/CFR proof requires every decoded row."""
    index: int
    width: int
    height: int
    pixel_format: str
    frame_rate: Fraction | None
    time_base: Fraction
    declared_frames: int | None
    codec: str
    kind: str


def _pairs(rows: list[tuple[str, object]]) -> dict:
    """Reject JSON duplicate fields instead of silently keeping the last value."""
    result = {}
    for key, value in rows:
        if key in result:
            raise ValueError("Presenter probe JSON contains duplicated fields")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    """Nonfinite JSON constants cannot represent observed metadata."""
    raise ValueError("Presenter probe JSON contains a nonfinite constant")


def probe_document(raw: str, maximum: int) -> dict:
    """Require complete bounded actual stdout; truncation is never repaired."""
    if type(raw) is not str or not 0 < len(raw.encode("utf-8")) <= maximum:
        raise ValueError("Presenter probe output is missing or over its byte bound")
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    if type(value) is not dict or "error" in value:
        raise ValueError("Presenter probe did not report an error-free complete document")
    return value


def _integer(value: object, label: str) -> int:
    """Parse actual ffprobe decimal fields, not floats, booleans or missing values."""
    if type(value) is int and abs(value) < 2**53:
        return value
    if type(value) is str and re.fullmatch(r"(?:0|[1-9][0-9]{0,15})", value):
        result = int(value)
        if result < 2**53:
            return result
    raise ValueError(f"Presenter probe {label} is not an exact integer")


def canonical_presenter_rate(value: str) -> str:
    """Normalize only the existing reduced guided N/1 spelling to graph N."""
    if type(value) is not str or re.fullmatch(r"[1-9][0-9]*(?:/[1-9][0-9]*)?", value) is None or len(value) > 32:
        raise ValueError("Presenter rate requires an exact reduced rational token")
    rate = Fraction(value)
    allowed = (str(rate), f"{rate.numerator}/{rate.denominator}")
    if value not in allowed or not 0 < rate <= 60 or max(rate.numerator, rate.denominator) > 2_147_483_647:
        raise ValueError("Presenter rate is unreduced or outside the graph clock class")
    return str(rate)


def _time_base(value: object) -> Fraction:
    """Require explicit positive integer timebase components without rounding."""
    if type(value) is not str or len(value) > 32 or re.fullmatch(r"[1-9][0-9]*/[1-9][0-9]*", value) is None:
        raise ValueError("Presenter probe time base is missing or malformed")
    rate = Fraction(value)
    if max(rate.numerator, rate.denominator) > 2_147_483_647:
        raise ValueError("Presenter probe time base exceeds exact integer bounds")
    return rate


def _side_data(row: dict) -> None:
    """Unknown ICC/HDR/orientation/alpha metadata is not a benign default."""
    if type(row) is not dict:
        raise ValueError("Presenter probe side metadata is malformed")
    sides, tags = row.get("side_data_list", []), row.get("tags", {})
    if type(sides) is not list or len(sides) > 16 or type(tags) is not dict:
        raise ValueError("Presenter probe side metadata is malformed")
    if any(type(side) is not dict or side != {"side_data_type": _SEI} for side in sides):
        raise ValueError("Presenter probe has unsupported ICC/HDR/orientation side metadata")
    forbidden = {"rotate", "rotation", "orientation", "alpha_mode", "icc_profile", "iccprofile"}
    if any(type(key) is not str or key.lower() in forbidden for key in tags):
        raise ValueError("Presenter probe has unsupported orientation/alpha/profile tags")


def _picture(row: dict, kind: str) -> None:
    """Require explicit range, matrix, primaries, transfer, native size and SAR."""
    expected_format, colors = ("rgb24", _STILL_COLOR) if kind == "still-image" else ("yuv420p", _VIDEO_COLOR)
    if not valid_canvas(row.get("width"), row.get("height")) or row.get("pix_fmt") != expected_format:
        raise ValueError("Presenter picture exceeds its bounded8-bit opaque native class")
    if row.get("sample_aspect_ratio") != "1:1" or tuple(row.get(key) for key in _COLORS) != colors:
        raise ValueError("Presenter picture lacks exact square-pixel and declared color metadata")
    _side_data(row)


def read_presenter_header(document: dict, kind: str, frame_rate: str) -> PresenterProbeHeader:
    """Reject known unsupported input classes before launching the full frame decode."""
    rows = document.get("streams")
    if type(rows) is not list or not 1 <= len(rows) <= 32 or kind not in ("still-image", "timed-media"):
        raise ValueError("Presenter probe requires bounded actual stream metadata")
    if any(type(row) is not dict or row.get("codec_type") not in ("video", "audio") for row in rows):
        raise ValueError("Presenter observation does not support auxiliary/data streams")
    videos = [row for row in rows if row["codec_type"] == "video"]
    if len(videos) != 1 or (kind == "still-image" and len(rows) != 1):
        raise ValueError("Presenter asset requires exactly one picture stream")
    row = videos[0]
    _picture(row, kind)
    _side_data(document.get("format", {}))
    if row.get("field_order") not in (None, "unknown", "progressive"):
        raise ValueError("Presenter input signals an interlaced picture")
    clock = _time_base(row.get("time_base"))
    rate = _header_rate(row, kind, frame_rate, clock)
    count = _integer(row["nb_frames"], "declared frames") if "nb_frames" in row else None
    if count is not None and not 1 <= count <= MAX_FRAMES:
        raise ValueError("Presenter declared frame count exceeds its existing graph bound")
    codec = row.get("codec_name")
    if type(codec) is not str or not codec or (kind == "still-image" and codec != "png"):
        raise ValueError("Presenter codec metadata is missing or unsupported")
    index = _integer(row.get("index"), "stream index")
    if not 0 <= index <= 31:
        raise ValueError("Presenter picture stream index is outside the bounded stream class")
    return PresenterProbeHeader(index, row["width"], row["height"],
                                row["pix_fmt"], rate, clock, count, codec, kind)


def _header_rate(row: dict, kind: str, requested: str, clock: Fraction) -> Fraction | None:
    """A still has no program cadence; video requires an exact representable clock."""
    rate = Fraction(canonical_presenter_rate(requested))
    if kind == "still-image":
        return None
    if (_integer(row.get("start_pts"), "start PTS") != 0
            or Fraction(canonical_presenter_rate(row.get("r_frame_rate"))) != rate
            or Fraction(canonical_presenter_rate(row.get("avg_frame_rate"))) != rate
            or (1 / rate / clock).denominator != 1):
        raise ValueError("Presenter video lacks the exact zero-origin representable CFR clock")
    return rate


def _frame(row: dict, index: int, header: PresenterProbeHeader) -> None:
    """Every decoded row must preserve geometry/color and its nonsynthesized PTS."""
    if type(row) is not dict or row.get("media_type") != "video":
        raise ValueError("Presenter decoded record is not a picture")
    _picture(row, header.kind)
    if (row["width"], row["height"], row["pix_fmt"]) != (header.width, header.height, header.pixel_format):
        raise ValueError("Presenter decoded picture geometry changes within the asset")
    if (_integer(row.get("stream_index"), "frame stream") != header.index
            or _integer(row.get("interlaced_frame"), "interlace") != 0
            or _integer(row.get("repeat_pict"), "repeat picture") != 0):
        raise ValueError("Presenter decoded picture stream/progressive/repeat flags are unsupported")
    pts = _integer(row.get("pts"), "frame PTS")
    if _integer(row.get("best_effort_timestamp"), "original frame PTS") != pts:
        raise ValueError("Presenter decoded timestamp was synthesized or changed")
    if header.frame_rate is None:
        if index != 0 or pts != 0:
            raise ValueError("Presenter still must contain one zero-origin decoded picture")
        return
    step = 1 / header.frame_rate / header.time_base
    if pts != index * step or _integer(row.get("duration"), "frame duration") != step:
        raise ValueError("Presenter decoded frame has shifted, missing or variable PTS/duration")


def finish_presenter_probe(selected: SelectedPresenterAsset, header: PresenterProbeHeader,
                           document: dict, guard: Callable[[], None]) -> PresenterGraphAsset:
    """Prove all emitted frames and exact selected coverage; no audio/rights claims."""
    count = validate_presenter_frames(header, document, guard)
    geometry = selected.geometry
    if header.frame_rate is None and (count != 1 or geometry.declaration.asset_start != 0):
        raise ValueError("Presenter still has animation or a nonzero timed-media offset")
    if header.frame_rate is not None:
        _coverage(geometry, header.frame_rate, count)
    return observed_graph_asset(selected.admission, header, count)


def validate_presenter_frames(header: PresenterProbeHeader, document: dict,
                              guard: Callable[[], None]) -> int:
    """Revalidate retained decoded metadata without spawning or reading source bytes."""
    rows = document.get("frames")
    if type(rows) is not list or not 1 <= len(rows) <= MAX_FRAMES:
        raise ValueError("Presenter full decode is empty, incomplete or beyond its frame bound")
    rate = str(header.frame_rate) if header.frame_rate is not None else "30"
    actual = read_presenter_header(document, header.kind, rate)
    if actual != header:
        raise ValueError("Presenter stream metadata changed across actual probes")
    stream = document["streams"][0]
    if _integer(stream.get("nb_read_frames"), "actual decoded count") != len(rows):
        raise ValueError("Presenter decoded frame inventory differs from the actual EOF count")
    if header.declared_frames is not None and len(rows) != header.declared_frames:
        raise ValueError("Presenter decoded EOF count differs from the declared source count")
    for index, row in enumerate(rows):
        guard()
        _frame(row, index, header)
    return len(rows)


def observed_graph_asset(admission: PresenterAssetAdmission, header: PresenterProbeHeader,
                         count: int) -> PresenterGraphAsset:
    """Project proved picture facts without inventing a new source/admission identity."""
    return PresenterGraphAsset(admission.asset_id, admission.snapshot_path,
        "still-image" if header.frame_rate is None else "video", header.width, header.height,
        header.pixel_format, str(header.frame_rate) if header.frame_rate is not None else None,
        count, True, "1:1", "srgb-display-to-bt709-bt1886-v1" if header.frame_rate is None else "bt709-limited-video")


def _coverage(geometry: object, rate: Fraction, count: int) -> None:
    """Require an integral source start and every selected absolute-window frame."""
    start = geometry.declaration.asset_start * rate
    length = geometry.timing.end_frame_exclusive - geometry.timing.start_frame
    if start.denominator != 1 or start < 0 or start + length > count:
        raise ValueError("Presenter asset offset is off-frame or selected video coverage is incomplete")
