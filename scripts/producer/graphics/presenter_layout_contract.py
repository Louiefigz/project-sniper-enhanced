"""Closed manual presenter declarations; no source, asset or render authority."""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import ClassVar

MAX_FRAMES = 432_000
_SAFE_INTEGER = 9_007_199_254_740_991
_FORMATS = frozenset({"yuv420p", "yuv422p", "yuv444p", "yuva420p",
                      "yuva422p", "yuva444p", "gbrp", "gbrap", "gray"})
_RECT_KEYS = frozenset({"x", "y", "width", "height"})
_KEYS = frozenset({"schemaVersion", "sourceIds", "layout", "cropSpace",
                   "presenterCrop", "protectedPresenterRect", "presenterRect",
                   "presentationRect", "mask", "assetId", "assetStart",
                   "presentationFit", "assetAudio", "enterFrames", "exitFrames",
                   "easing", "track"})
# Exact proposal_trim/String.trim policy, retained here to keep geometry pure.
_JS_EDGE_WHITESPACE = ("\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff")


def closed(value: object, keys: frozenset[str], label: str) -> dict:
    """Require exactly the stated JSON object fields."""
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f"{label} requires exact fields")
    return value


def number(value: object, label: str) -> float:
    """Reject booleans, nonfinite values and noncanonical negative zero."""
    if type(value) not in (int, float):
        raise ValueError(f"{label} requires a finite canonical number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} requires a finite canonical number") from exc
    if not math.isfinite(result) or (result == 0 and math.copysign(1, result) < 0):
        raise ValueError(f"{label} requires a finite canonical number")
    return result


def integer(value: object, label: str, maximum: int = _SAFE_INTEGER) -> int:
    """Require a nonnegative JSON safe integer without coercion."""
    result = number(value, label)
    if not result.is_integer() or result < 0 or result > maximum:
        raise ValueError(f"{label} requires a bounded safe integer")
    return int(result)


@dataclass(frozen=True)
class PixelRect:
    """Continuous held-base display pixel edges, not rounded raster evidence."""
    x: float
    y: float
    width: float
    height: float

    def corners(self) -> tuple[tuple[float, float], ...]:
        """Return all corners in stable top-left, top-right, bottom order."""
        return ((self.x, self.y), (self.x + self.width, self.y),
                (self.x, self.y + self.height),
                (self.x + self.width, self.y + self.height))


@dataclass(frozen=True)
class PresenterCanvas:
    """Caller-declared square-pixel canvas; actual media must be held separately."""
    width: int
    height: int
    total_frames: int
    pixel_format: str

    def __post_init__(self) -> None:
        """Preserve the existing prefix size class and reject depth conversion."""
        width = integer(self.width, "canvas width", 4096)
        height = integer(self.height, "canvas height", 4096)
        total = integer(self.total_frames, "total frames", MAX_FRAMES)
        if min(width, height) < 2 or width % 2 or height % 2 or not total:
            raise ValueError("Presenter canvas requires positive even dimensions/frames")
        if width * height > 4096 * 2160:
            raise ValueError("Presenter canvas exceeds existing prefix pixel bound")
        if type(self.pixel_format) is not str or self.pixel_format not in _FORMATS:
            raise ValueError("Presenter requires an explicit supported 8-bit pixel format")


@dataclass(frozen=True)
class PresenterTiming:
    """Global half-open window; ramp lengths count differences between frames."""
    start_frame: int
    end_frame_exclusive: int
    enter_frames: int
    exit_frames: int


@dataclass(frozen=True)
class PresenterSurfaces:
    """Immutable pixel-space projections of the four declared rectangles."""
    crop: PixelRect
    protected: PixelRect
    presenter: PixelRect
    presentation: PixelRect


@dataclass(frozen=True)
class PresenterShape:
    """Final mask and isotropic scale, with no inferred face location."""
    surfaces: PresenterSurfaces
    mask_kind: str
    radius_px: float
    scale: float
    declaration_rectangles: tuple[tuple[float, float, float, float], ...]


@dataclass(frozen=True)
class PresenterDeclaration:
    """Unresolved provenance names retained without asset/source admission."""
    layout: str
    source_ids: tuple[str, ...]
    asset_id: str
    asset_start: Fraction


@dataclass(frozen=True)
class PresenterGeometry:
    """Pure declared geometry; never a serialized completion or execution grant."""
    canvas: PresenterCanvas
    timing: PresenterTiming
    shape: PresenterShape
    declaration: PresenterDeclaration
    executable: ClassVar[bool] = False
    installed_mapping_qualified: ClassVar[bool] = False
    framing_observed: ClassVar[bool] = False


def _rect(value: object, canvas: PresenterCanvas) -> PixelRect:
    """Project exact normalized fields without clamping or rounding."""
    row = closed(value, _RECT_KEYS, "presenter rectangle")
    x, y = number(row["x"], "x"), number(row["y"], "y")
    width, height = number(row["width"], "width"), number(row["height"], "height")
    if min(x, y) < 0 or min(width, height) <= 0 or x + width > 1 or y + height > 1:
        raise ValueError("Presenter rectangle leaves its normalized canvas")
    return PixelRect(x * canvas.width, y * canvas.height,
                     width * canvas.width, height * canvas.height)


def presenter_identifier(value: object) -> str:
    """Match TS code-point/ECMAScript-blank checks without rewriting opaque IDs."""
    if type(value) is not str or not value.strip(_JS_EDGE_WHITESPACE) or len(value) > 128:
        raise ValueError("Presenter requires a bounded nonempty identifier")
    return value


def _declaration(row: dict) -> PresenterDeclaration:
    """Validate ordered unique source IDs and an exact reduced asset offset."""
    ids = row["sourceIds"]
    if type(ids) is not list or not 1 <= len(ids) <= 128:
        raise ValueError("Presenter requires 1–128 ordered source IDs")
    sources = tuple(presenter_identifier(value) for value in ids)
    if len(set(sources)) != len(sources):
        raise ValueError("Presenter source IDs are duplicated")
    start = closed(row["assetStart"], frozenset({"numerator", "denominator"}), "assetStart")
    numerator = integer(start["numerator"], "asset numerator")
    denominator = integer(start["denominator"], "asset denominator")
    if not denominator or math.gcd(numerator, denominator) != 1:
        raise ValueError("Presenter assetStart must be reduced including zero as 0/1")
    return PresenterDeclaration(row["layout"], sources, presenter_identifier(row["assetId"]),
                                Fraction(numerator, denominator))


def _shape(row: dict, canvas: PresenterCanvas) -> PresenterShape:
    """Validate matching mask, bounded radius, minimum crop and no upscale."""
    surfaces = PresenterSurfaces(*(_rect(row[key], canvas) for key in (
        "presenterCrop", "protectedPresenterRect", "presenterRect", "presentationRect")))
    crop, target = surfaces.crop, surfaces.presenter
    if crop.width < canvas.width * .05 or crop.height < canvas.height * .05:
        raise ValueError("Presenter crop is below the existing manual crop minimum")
    if min(crop.width, crop.height, target.width, target.height) < 2:
        raise ValueError("Presenter surfaces must be at least two pixels")
    if target.width > crop.width or target.height > crop.height:
        raise ValueError("Presenter upscale is unsupported")
    scale = target.width / crop.width
    if abs(crop.height * scale - target.height) > 1e-7:
        raise ValueError("Presenter crop and destination would stretch the picture")
    kind = {"inset": "rounded-rect", "bubble": "circle", "split": "rect"}[row["layout"]]
    keys = frozenset({"kind", "radiusPx"} if kind == "rounded-rect" else {"kind"})
    mask = closed(row["mask"], keys, "presenter mask")
    if mask["kind"] != kind:
        raise ValueError("Presenter mask must match its layout")
    radius = number(mask["radiusPx"], "radius") if kind == "rounded-rect" else 0.0
    if kind == "circle":
        radius = target.width / 2
    if kind == "circle" and abs(target.width - target.height) > 1e-7:
        raise ValueError("Presenter bubble requires a square in actual pixels")
    if kind == "rounded-rect" and (radius <= 0 or radius > min(target.width, target.height) / 2):
        raise ValueError("Presenter radius exceeds its mask")
    rectangles = tuple(tuple(number(row[key][field], field) for field in ("x", "y", "width", "height"))
                       for key in ("presenterCrop", "protectedPresenterRect", "presenterRect", "presentationRect"))
    return PresenterShape(surfaces, kind, radius, scale, rectangles)


def _timing(row: dict, canvas: PresenterCanvas, span: tuple[int, int]) -> PresenterTiming:
    """Reject overlapping ramps or an exit needing an unwritten endpoint."""
    if type(span) is not tuple or len(span) != 2:
        raise ValueError("Presenter frame range must be an exact pair")
    start, end = (integer(value, "frame range", canvas.total_frames) for value in span)
    enter = integer(row["enterFrames"], "enterFrames", 1_000_000_000)
    exit_frames = integer(row["exitFrames"], "exitFrames", 1_000_000_000)
    if not enter or not exit_frames or start + enter > end - 1 - exit_frames:
        raise ValueError("Presenter window cannot contain both complete positive ramps")
    return PresenterTiming(start, end, enter, exit_frames)


def parse_declaration(payload: object, canvas: PresenterCanvas,
                      frame_range: tuple[int, int]) -> PresenterGeometry:
    """Parse only this V1 manual declaration, without broader pipeline reads."""
    if type(canvas) is not PresenterCanvas:
        raise ValueError("Presenter requires its explicit canvas contract")
    row = closed(payload, _KEYS, "PresenterLayoutV1")
    if integer(row["schemaVersion"], "schemaVersion") != 1:
        raise ValueError("Presenter requires exact schemaVersion 1")
    expected = {"cropSpace": "held-base-display", "presentationFit": "contain",
                "assetAudio": "discard", "easing": "smoothstep-v1", "track": False}
    if any(type(row[key]) is not type(value) or row[key] != value for key, value in expected.items()):
        raise ValueError("Presenter requires exact manual picture-only policies")
    if type(row["layout"]) is not str or row["layout"] not in ("inset", "bubble", "split"):
        raise ValueError("Presenter requires a supported layout")
    return PresenterGeometry(canvas, _timing(row, canvas, frame_range),
                             _shape(row, canvas), _declaration(row))


def _original_rectangles(value: PresenterGeometry) -> dict:
    """Reproject held normalized tuples exactly, never reverse-round pixel floats."""
    rows = value.shape.declaration_rectangles
    names = ("presenterCrop", "protectedPresenterRect", "presenterRect", "presentationRect")
    if type(rows) is not tuple or len(rows) != 4:
        raise ValueError("Presenter requires original normalized rectangles")
    if any(type(row) is not tuple or len(row) != 4 for row in rows):
        raise ValueError("Presenter original rectangles have changed types")
    projected = {key: dict(zip(("x", "y", "width", "height"), row)) for key, row in zip(names, rows)}
    surfaces = value.shape.surfaces
    current = (surfaces.crop, surfaces.protected, surfaces.presenter, surfaces.presentation)
    if any(type(rect) is not PixelRect for rect in current):
        raise ValueError("Presenter requires exact pixel rectangle types")
    for rect in current:
        for item in (rect.x, rect.y, rect.width, rect.height):
            number(item, "pixel edge")
    if current != tuple(_rect(projected[key], value.canvas) for key in names):
        raise ValueError("Presenter pixel surfaces differ from original declaration")
    return projected


def declaration_payload(value: PresenterGeometry) -> dict:
    """Reconstruct closed data, rejecting replaced dataclass types/coefficients."""
    if type(value) is not PresenterGeometry or type(value.canvas) is not PresenterCanvas:
        raise ValueError("Presenter requires exact geometry/canvas types")
    value.canvas.__post_init__()
    if type(value.shape) is not PresenterShape or type(value.timing) is not PresenterTiming:
        raise ValueError("Presenter requires exact shape/timing types")
    if type(value.declaration) is not PresenterDeclaration or type(value.shape.surfaces) is not PresenterSurfaces:
        raise ValueError("Presenter requires exact declaration/surface types")
    declaration, timing, shape = value.declaration, value.timing, value.shape
    if type(declaration.source_ids) is not tuple or type(declaration.asset_start) is not Fraction:
        raise ValueError("Presenter declaration IDs/offset have changed types")
    surfaces = shape.surfaces
    projected = _original_rectangles(value)
    if surfaces.crop.width <= 0 or number(shape.scale, "scale") != surfaces.presenter.width / surfaces.crop.width:
        raise ValueError("Presenter derived scale differs from declared surfaces")
    radius = number(shape.radius_px, "radius")
    if shape.mask_kind != "rounded-rect" and radius != (surfaces.presenter.width / 2 if shape.mask_kind == "circle" else 0):
        raise ValueError("Presenter derived radius differs from declared mask")
    mask = {"kind": shape.mask_kind}
    if shape.mask_kind == "rounded-rect":
        mask["radiusPx"] = radius
    return {"schemaVersion": 1, "sourceIds": list(declaration.source_ids),
            "layout": declaration.layout, "cropSpace": "held-base-display", **projected,
            "mask": mask, "assetId": declaration.asset_id,
            "assetStart": {"numerator": declaration.asset_start.numerator,
                           "denominator": declaration.asset_start.denominator},
            "presentationFit": "contain", "assetAudio": "discard",
            "enterFrames": timing.enter_frames, "exitFrames": timing.exit_frames,
            "easing": "smoothstep-v1", "track": False}
