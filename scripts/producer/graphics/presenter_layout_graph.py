"""Opt-in presenter graph construction, not asset admission or render approval.

Callers must independently hold/probe these inputs. This low-level seam has no
Producer profile, accepted-plan, prefix-proof or observed-framing authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from graphics.presenter_layout_contract import MAX_FRAMES, PresenterCanvas, PresenterGeometry
from graphics.presenter_layout_geometry import presenter_expressions
from opening_prefix_contract import GRAPH_WORKLOAD_POLICY, valid_canvas


@dataclass(frozen=True)
class PresenterGraphAsset:
    """Caller-observed picture metadata; bytes/clock still need an owning receipt."""

    asset_id: str
    path: str
    kind: str
    width: int
    height: int
    pixel_format: str
    frame_rate: str | None
    total_frames: int
    zero_origin: bool
    sample_aspect_ratio: str
    color_policy: str


@dataclass(frozen=True)
class PresenterGraphWindow:
    """One original operation and its compiled manual declaration, never tracking."""

    operation_index: int
    geometry: PresenterGeometry
    asset: PresenterGraphAsset


@dataclass(frozen=True)
class PresenterGraphSpec:
    """Closed disjoint layouts over the already-held, already-reframed cut base."""

    canvas: PresenterCanvas
    frame_rate: str
    windows: tuple[PresenterGraphWindow, ...]
    base_color_policy: str


def _rate(value: object) -> Fraction:
    """Keep source/target cadence exact instead of guessing from asset duration."""
    if type(value) is not str or not value or len(value) > 32:
        raise ValueError("presenter graph needs a bounded rational frame rate")
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError("presenter graph frame rate is malformed") from error
    if str(rate) != value or not 0 < rate <= 60 \
            or max(rate.numerator, rate.denominator) > 2_147_483_647:
        raise ValueError("presenter graph frame rate is noncanonical or exceeds its exact clock bound")
    return rate


def _asset(window: PresenterGraphWindow, rate: Fraction) -> int:
    """Return an exact first video frame; stills have one explicit zero origin."""
    asset, geometry = window.asset, window.geometry
    if type(asset) is not PresenterGraphAsset or asset.asset_id != geometry.declaration.asset_id:
        raise ValueError("presenter graph asset differs from its declared selection")
    if type(asset.path) is not str or not asset.path or len(asset.path) > 4096 \
            or any(ord(char) < 32 for char in asset.path) or not Path(asset.path).is_absolute() \
            or str(Path(asset.path)) != asset.path or any(part in {".", ".."} for part in Path(asset.path).parts):
        raise ValueError("presenter graph asset path is not a bounded absolute local path")
    if not valid_canvas(asset.width, asset.height) or asset.zero_origin is not True \
            or asset.sample_aspect_ratio != "1:1" or type(asset.total_frames) is not int \
            or not 1 <= asset.total_frames <= MAX_FRAMES:
        raise ValueError("presenter graph asset lacks its bounded square-pixel zero-origin observation")
    start = geometry.declaration.asset_start * rate
    if asset.kind == "still-image":
        if asset.frame_rate is not None or asset.total_frames != 1 or start != 0 \
                or asset.pixel_format != "rgb24" or asset.color_policy != "srgb-display-to-bt709-bt1886-v1":
            raise ValueError("presenter still needs one opaque RGB image, explicit display-transfer policy and zero start")
        return 0
    if asset.kind != "video" or _rate(asset.frame_rate) != rate \
            or asset.pixel_format != "yuv420p" or asset.color_policy != "bt709-limited-video":
        raise ValueError("presenter video needs the exact held cadence and admitted8-bit BT709 policy")
    length = geometry.timing.end_frame_exclusive - geometry.timing.start_frame
    if start.denominator != 1 or not 0 <= start.numerator < asset.total_frames \
            or start.numerator + length > asset.total_frames:
        raise ValueError("presenter video start is off-frame or asset coverage is insufficient")
    return start.numerator


def _presentation_box(geometry: PresenterGeometry) -> tuple[int, int, int, int]:
    """No silent half-pixel rounding in the initial 4:2:0 composition policy."""
    box = geometry.shape.surfaces.presentation
    values = (box.x, box.y, box.width, box.height)
    if any(value != int(value) or int(value) % 2 for value in values):
        raise ValueError("presenter presentation cell requires exact even pixel boundaries")
    return tuple(int(value) for value in values)


def validate_presenter_graph(value: PresenterGraphSpec) -> None:
    """Validate all graph work before input arguments or a media process exist."""
    if type(value) is not PresenterGraphSpec or type(value.canvas) is not PresenterCanvas \
            or value.canvas.pixel_format != "yuv420p" or not valid_canvas(value.canvas.width, value.canvas.height) \
            or value.base_color_policy != "bt709-limited-video":
        raise ValueError("presenter graph requires its exact8-bit held compositor canvas")
    rate = _rate(value.frame_rate)
    if type(value.windows) is not tuple or not 1 <= len(value.windows) <= 32:
        raise ValueError("presenter graph requires1–32 explicitly ordered windows")
    last_end, seen, paths = 0, set(), {}
    pixels = value.canvas.width * value.canvas.height
    for window in value.windows:
        if type(window) is not PresenterGraphWindow or type(window.operation_index) is not int \
                or not 0 <= window.operation_index < 128 or window.operation_index in seen \
                or type(window.geometry) is not PresenterGeometry or window.geometry.canvas != value.canvas:
            raise ValueError("presenter graph operation identity/canvas is malformed or duplicated")
        presenter_expressions(window.geometry, origin_frame=window.geometry.timing.start_frame)
        _presentation_box(window.geometry)
        _asset(window, rate)
        if window.geometry.timing.start_frame < last_end:
            raise ValueError("presenter graph windows overlap or are not in original timeline order")
        if window.asset.path in paths and paths[window.asset.path] != window.asset:
            raise ValueError("presenter graph changed metadata for the same asset path")
        paths[window.asset.path] = window.asset
        seen.add(window.operation_index)
        last_end = window.geometry.timing.end_frame_exclusive
        pixels += window.asset.width * window.asset.height
    if pixels > GRAPH_WORKLOAD_POLICY["maxGraphInputPixels"]:
        raise ValueError("presenter graph exceeds the existing aggregate input-pixel bound")


def presenter_input_arguments(value: PresenterGraphSpec) -> list[str]:
    """Append one admitted asset input per window; never insert an audio mapping."""
    validate_presenter_graph(value)
    result: list[str] = []
    for window in value.windows:
        if window.asset.kind == "still-image":
            result += ["-f", "image2", "-pattern_type", "none", "-framerate", value.frame_rate]
        result += ["-i", window.asset.path]
    return result


def _presentation_filter(window: PresenterGraphWindow, rate: Fraction) -> str:
    """Contain picture only; still color uses the declared display-referred path.

    FFmpeg n8 libswscale maps sRGB's EOTF to inverse BT.1886 for BT709 signals,
    not the nominal camera OETF. Media owners still need exact tool/metadata,
    SDR white/black endpoint and actual chromatic/transfer qualification.
    """
    geometry = window.geometry
    x, y, width, height = _presentation_box(geometry)
    start = _asset(window, rate)
    count = geometry.timing.end_frame_exclusive - geometry.timing.start_frame
    origin = f"(N+{geometry.timing.start_frame})*{rate.denominator}"
    input_range = "full" if window.asset.kind == "still-image" else "tv"
    transfer = "srgb" if window.asset.kind == "still-image" else "bt709"
    # Prepare an opaque still once, then repeat its already-converted frame.
    # Keep repetition graph-local and finite: no intermediate lossy video.
    still = window.asset.kind == "still-image"
    repeat = f",loop=loop={count - 1}:size=1:start=0" if still else ""
    return (f"trim=start_frame={start}:end_frame={start + (1 if still else count)},"
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos:"
        f"in_color_matrix=bt709:out_color_matrix=bt709:in_range={input_range}:out_range=tv:"
        f"in_primaries=bt709:out_primaries=bt709:in_transfer={transfer}:out_transfer=bt709:intent=relative_colorimetric,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"pad={geometry.canvas.width}:{geometry.canvas.height}:{x}:{y}:color=black,setsar=1,format=yuv420p"
        f"{repeat},settb=expr=1/{rate.numerator},setpts={origin}")


def build_presenter_graph(value: PresenterGraphSpec, first_asset_input: int) -> tuple[list[str], str]:
    """Branch from immutable input0 before graphics; keep original global PTS."""
    validate_presenter_graph(value)
    if type(first_asset_input) is not int or not 1 <= first_asset_input <= 513:
        raise ValueError("presenter asset input index is malformed")
    rate = _rate(value.frame_rate)
    branches = "".join(f"[pl{index}source]" for index in range(len(value.windows)))
    # Frame-index policy: one common exact lattice prevents framesync selecting a
    # preceding mask when an input container rounds PTS to milliseconds. This
    # neither admits VFR sources nor proves the caller-observed clock is genuine.
    # Metadata declaration only, not source grading: an eventual execution owner
    # must first observe this exact base policy. Never infer it from pixel format.
    parts = [f"[0:v]setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=limited,"
             f"settb=expr=1/{rate.numerator},setpts=N*{rate.denominator},"
             f"split={len(value.windows) + 1}[plbase]{branches}"]
    previous = "[plbase]"
    for index, window in enumerate(value.windows):
        geometry, tag = window.geometry, f"pl{index}"
        expression = presenter_expressions(geometry, origin_frame=geometry.timing.start_frame)
        span = f"trim=start_frame={geometry.timing.start_frame}:end_frame={geometry.timing.end_frame_exclusive}"
        parts += [f"[{first_asset_input + index}:v]{_presentation_filter(window, rate)}[{tag}asset]",
            f"[{tag}source]{span},split[{tag}pixels][{tag}masksource]",
            f"[{tag}pixels]{expression.perspective}[{tag}warped]",
            f"[{tag}masksource]format=gray,{expression.alpha}[{tag}mask]",
            f"[{tag}warped][{tag}mask]alphamerge[{tag}presenter]",
            f"[{tag}asset][{tag}presenter]overlay=x=0:y=0:format=yuv420:shortest=1[{tag}layout]",
            f"{previous}[{tag}layout]overlay=x=0:y=0:format=yuv420:eof_action=pass:repeatlast=0:"
            f"enable='{expression.gate}'[{tag}out]"]
        previous = f"[{tag}out]"
    return parts, previous
