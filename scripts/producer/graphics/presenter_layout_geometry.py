"""Pure manual presenter motion/masks; no renderer, admission or approval.

For progress p, each source point follows (1-p)*point + p*final(point).
The viewport and radius also interpolate linearly. Rounded rectangles are
axis-aligned rectangles Minkowski-added to a disk: the intermediate mask is
the Minkowski interpolation of the full canvas and final mask. Consequently
endpoint containment of all protected corners proves continuous containment.
Numerical critical-frame checks supplement this proof, not actual observation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar

from graphics.presenter_layout_contract import (
    PixelRect, PresenterCanvas, PresenterGeometry, declaration_payload, integer,
    parse_declaration,
)

_EPSILON = 1e-7  # Numerical comparison only, not a framing/fit allowance.


@dataclass(frozen=True)
class PresenterFrame:
    """Continuous pixel geometry at one original global output frame."""
    scale: float
    translation: tuple[float, float]
    viewport: PixelRect
    radius_px: float

    def visible_crop(self) -> PixelRect:
        """Invert the affine viewport without fabricating source coordinates."""
        tx, ty = self.translation
        rect = self.viewport
        return PixelRect((rect.x - tx) / self.scale, (rect.y - ty) / self.scale,
                         rect.width / self.scale, rect.height / self.scale)


@dataclass(frozen=True)
class PresenterExpressions:
    """Unqualified filter fragments, not a command or owned media receipt."""
    perspective: str
    alpha: str
    gate: str
    origin_frame: int
    executable: ClassVar[bool] = False
    installed_mapping_qualified: ClassVar[bool] = False
    mask_sampling: ClassVar[str] = "pixel-centre-binary-unqualified-v1"
    coordinate_mapping: ClassVar[str] = "edge-affine-to-centre-index-unqualified-v1"


def _progress(value: PresenterGeometry, frame: int) -> float:
    """Evaluate cubic smoothstep on exact complete enter/exit frame ramps."""
    timing = value.timing
    entering = (frame - timing.start_frame) / timing.enter_frames
    exiting = (timing.end_frame_exclusive - 1 - frame) / timing.exit_frames
    q = max(0.0, min(1.0, entering, exiting))
    return q * q * (3 - 2 * q)


def presenter_frame(value: PresenterGeometry, global_frame: int) -> PresenterFrame:
    """Project the original clock without restarting progress at an opening trim."""
    frame = integer(global_frame, "global frame", value.canvas.total_frames - 1)
    p = _progress(value, frame)
    crop, target = value.shape.surfaces.crop, value.shape.surfaces.presenter
    scale = 1 + p * (value.shape.scale - 1)
    translation = (p * (target.x - value.shape.scale * crop.x),
                   p * (target.y - value.shape.scale * crop.y))
    viewport = PixelRect(p * target.x, p * target.y,
                         value.canvas.width + p * (target.width - value.canvas.width),
                         value.canvas.height + p * (target.height - value.canvas.height))
    return PresenterFrame(scale, translation, viewport, p * value.shape.radius_px)


def _distance(point: tuple[float, float], frame: PresenterFrame) -> float:
    """Signed distance to the continuous rounded mask; rect is radius zero."""
    rect, radius = frame.viewport, frame.radius_px
    dx = abs(point[0] - rect.x - rect.width / 2) - (rect.width / 2 - radius)
    dy = abs(point[1] - rect.y - rect.height / 2) - (rect.height / 2 - radius)
    return math.hypot(max(dx, 0), max(dy, 0)) + min(max(dx, dy), 0) - radius


def _inside(inner: PixelRect, outer: PixelRect) -> bool:
    """Compare continuous bounds with numerical-error tolerance only."""
    return (inner.x >= outer.x - _EPSILON and inner.y >= outer.y - _EPSILON
            and inner.x + inner.width <= outer.x + outer.width + _EPSILON
            and inner.y + inner.height <= outer.y + outer.height + _EPSILON)


def _cells(value: PresenterGeometry) -> None:
    """Preserve exact layout intent; a split tiles, an inset uses full backing."""
    canvas = PixelRect(0, 0, value.canvas.width, value.canvas.height)
    presenter, presentation = value.shape.surfaces.presenter, value.shape.surfaces.presentation
    if value.declaration.layout != "split":
        if presentation != canvas:
            raise ValueError("Inset/bubble requires full-canvas presentation")
        if presenter.width == canvas.width and presenter.height == canvas.height:
            raise ValueError("Inset/bubble presenter must be smaller than full canvas")
        return
    # Topology belongs to the original normalized declaration. Multiplying
    # valid .052/.948 cells by 1920 introduces a floating-point sum error.
    a, b = (PixelRect(*row) for row in value.shape.declaration_rectangles[2:])
    horizontal = (a.y == b.y == 0 and a.height == b.height == 1
                  and a.width + b.width == 1
                  and ((a.x == 0 and b.x == a.width) or (b.x == 0 and a.x == b.width)))
    vertical = (a.x == b.x == 0 and a.width == b.width == 1
                and a.height + b.height == 1
                and ((a.y == 0 and b.y == a.height) or (b.y == 0 and a.y == b.height)))
    if not horizontal and not vertical:
        raise ValueError("Presenter split cells must tile without gaps or overlaps")


def _verify_frame(value: PresenterGeometry, frame: int) -> None:
    """Check corners and inverse crop against the declared source at one frame."""
    state = presenter_frame(value, frame)
    canvas = PixelRect(0, 0, value.canvas.width, value.canvas.height)
    if not _inside(state.viewport, canvas) or not _inside(state.visible_crop(), canvas):
        raise ValueError("Presenter intermediate viewport leaves held base")
    if not 0 <= state.radius_px <= min(state.viewport.width, state.viewport.height) / 2 + _EPSILON:
        raise ValueError("Presenter intermediate mask has an invalid radius")
    for x, y in value.shape.surfaces.protected.corners():
        point = (state.scale * x + state.translation[0], state.scale * y + state.translation[1])
        if _distance(point, state) > _EPSILON:
            raise ValueError("Protected manual presenter envelope intersects mask")


def _sample_frames(value: PresenterGeometry) -> tuple[int, ...]:
    """Bound numerical sampling independently of total video duration."""
    timing = value.timing
    a, d = timing.start_frame, timing.end_frame_exclusive - 1
    b, c = a + timing.enter_frames, d - timing.exit_frames
    anchors = (a, b, c, d)
    near = {frame + delta for frame in anchors for delta in (-1, 0, 1)}
    samples = {a + (d - a) * index // 16 for index in range(17)}
    return tuple(sorted(frame for frame in near | samples if a <= frame <= d))


def compile_presenter_geometry(payload: object, canvas: PresenterCanvas,
                               frame_range: tuple[int, int]) -> PresenterGeometry:
    """Validate manual geometry analytically and with bounded frame samples.

    Endpoint corner containment proves all continuous intermediate rounded
    masks by Minkowski convexity. This does not prove the operator selected
    the real subject, asset eligibility, captions, resampling or painted pixels.
    """
    value = parse_declaration(payload, canvas, frame_range)
    surfaces = value.shape.surfaces
    if not _inside(surfaces.protected, surfaces.crop):
        raise ValueError("Protected manual presenter envelope leaves source crop")
    _cells(value)
    for frame in _sample_frames(value):
        _verify_frame(value, frame)
    return value


def revalidate_presenter_geometry(value: PresenterGeometry) -> None:
    """Reject caller-constructed/replaced invalid values before graph compilation.

    Frozen dataclasses are not authority. Reconstruct all declaration fields
    and repeat closed parsing, derived-coefficient, endpoint and sample checks.
    An owner must still independently bind the original submitted declaration.
    """
    payload = declaration_payload(value)
    span = (value.timing.start_frame, value.timing.end_frame_exclusive)
    compile_presenter_geometry(payload, value.canvas, span)


def _literal(value: float | int) -> str:
    """Serialize generated numeric coefficients only, never authored strings."""
    return format(value, ".17g")


def _progress_expression(value: PresenterGeometry, counter: str) -> str:
    """Compile deterministic stateless progress from a closed frame counter."""
    timing = value.timing
    q = (f"clip(min((({counter})-{timing.start_frame})/{timing.enter_frames},"
         f"({timing.end_frame_exclusive - 1}-({counter}))/{timing.exit_frames}),0,1)")
    return f"(({q})*({q})*(3-2*({q})))"


def _lerp(initial: float, final: float, progress: str) -> str:
    """Emit an affine scalar interpolation preserving caller-supplied endpoints."""
    return f"({_literal(initial)}+({_literal(final - initial)})*({progress}))"


def _perspective(value: PresenterGeometry, progress: str) -> str:
    """Convert edge-space motion to FFmpeg integer sample-centre coordinates.

    Source sample index i represents edge coordinate i+0.5. Its destination
    index is s*(i+0.5)+t-0.5, hence the additional (s-1)/2 translation.
    Installed-binary interpolation/format/endpoint behavior is still unproven.
    """
    crop, target = value.shape.surfaces.crop, value.shape.surfaces.presenter
    scale = _lerp(1, value.shape.scale, progress)
    tx = _lerp(0, target.x - value.shape.scale * crop.x, progress)
    ty = _lerp(0, target.y - value.shape.scale * crop.y, progress)
    tx, ty = f"({tx}+({scale}-1)/2)", f"({ty}+({scale}-1)/2)"
    right, bottom = f"({tx}+{value.canvas.width}*{scale})", f"({ty}+{value.canvas.height}*{scale})"
    coords = (tx, ty, right, ty, tx, bottom, right, bottom)
    names = ("x0", "y0", "x1", "y1", "x2", "y2", "x3", "y3")
    options = ":".join(f"{key}='{expression}'" for key, expression in zip(names, coords))
    return f"perspective={options}:sense=destination:eval=frame:interpolation=cubic"


def _alpha(value: PresenterGeometry, progress: str) -> str:
    """Keep exact mask arithmetic, evaluating repeated scalars once per pixel.

    Every register is assigned in this expression before use. Nothing depends
    on a previous pixel/frame or another geq thread's expression state.
    """
    target = value.shape.surfaces.presenter
    x, y = _lerp(0, target.x, "ld(0)"), _lerp(0, target.y, "ld(0)")
    width = _lerp(value.canvas.width, target.width, "ld(0)")
    height = _lerp(value.canvas.height, target.height, "ld(0)")
    radius = _lerp(0, value.shape.radius_px, "ld(0)")
    dx = f"(abs(X+0.5-({x})-({width})/2)-(({width})/2-(ld(1))))"
    dy = f"(abs(Y+0.5-({y})-({height})/2)-(({height})/2-(ld(1))))"
    distance = "(hypot(max(ld(2),0),max(ld(3),0))+min(max(ld(2),ld(3)),0)-(ld(1)))"
    assignments = f"st(0,{progress});st(1,{radius});st(2,{dx});st(3,{dy});"
    return f"geq=lum_expr='{assignments}255*lte({distance},0)'"


def presenter_expressions(value: PresenterGeometry, origin_frame: int = 0) -> PresenterExpressions:
    """Compile fragments for untrimmed or exact-operation-trimmed clean base.

    Caller must split immutable base before graphics, preserve PTS, supply the
    same frame stream to gray mask and perspective, and keep original global
    main overlay n. Binary mask/8-bit cubic mapping remain unqualified. No
    source string, path or asset identifier enters these filter expressions.
    """
    revalidate_presenter_geometry(value)
    origin = integer(origin_frame, "presenter branch origin", value.canvas.total_frames - 1)
    if origin not in (0, value.timing.start_frame):
        raise ValueError("Presenter branch must start at zero or exact operation origin")
    perspective = _perspective(value, _progress_expression(value, f"in-1+{origin}"))
    alpha = _alpha(value, _progress_expression(value, f"N+{origin}"))
    gate = f"gt(n,{value.timing.start_frame})*lt(n,{value.timing.end_frame_exclusive - 1})"
    return PresenterExpressions(perspective, alpha, gate, origin)
