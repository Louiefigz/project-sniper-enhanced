// DRAG-TO-PLACE geometry — pure functions only (tsx-asserted in
// __tests__/placement-geometry.test.ts); the preview component holds the
// pointer state and calls in here.
//
// CONTRACT: a graphicsTrack entry may carry `placement: {x, y}` in COMP-CANVAS
// px (the comp's authored canvas — 1080x1920 shorts / 1920x1080 longform):
// the point where the comp's rendered CONTENT top-left lands. Explicit
// placement WINS over anchor resolution at render (the compositor pins the
// measured alpha-bbox origin there — graphics_stage._explicit_offset);
// deleting it restores the anchor fallback. The preview mirrors the pin by
// translating the comp canvas by (placement − measured content origin) — see
// use-comp-html.useContentOrigin. The plan lint treats placement as a POINT:
// out-of-frame = lint ERROR — so `dragPlacement` CLAMPS into the canvas and the
// UI can never author that state — and outside SAFE_BOX (shorts only) = lint
// WARNING, surfaced live here via `inSafeRect` + the editor's amber strip.

export interface Placement {
  x: number;
  y: number;
}

/** The comp's authored canvas (px) — parseDims(comp html). */
export interface CanvasDims {
  w: number;
  h: number;
}

/** The <video> element's on-screen layout box (display px). */
export interface BoxSize {
  width: number;
  height: number;
}

// Mirror of scripts/producer/producer_config.SAFE_BOX — max UI margin per edge
// across TikTok/Reels/Shorts on the 1080x1920 shorts canvas. Longform has none.
export const SHORTS_CANVAS: CanvasDims = { w: 1080, h: 1920 };
export const SHORTS_SAFE_BOX = { top: 250, bottom: 520, left: 60, right: 150 } as const;

// Soft-snap radius in DISPLAY px (converted per-axis to canvas px at the
// current preview scale) — screen px is the unit that matches the hand; a fixed
// canvas-px radius would be sub-pixel-dead on a small preview (the
// timeline-scale SNAP_PX lesson). Alt disables (the caller skips the snap).
export const PLACEMENT_SNAP_PX = 12;

/** SAFE_BOX semantics apply ONLY to the authored shorts canvas. */
export function isShortsCanvas(c: CanvasDims): boolean {
  return c.w === SHORTS_CANVAS.w && c.h === SHORTS_CANVAS.h;
}

function assertGeometry(canvas: CanvasDims, box: BoxSize): void {
  if (canvas.w > 0 && canvas.h > 0 && box.width > 0 && box.height > 0) return;
  throw new Error(
    `placement geometry: canvas ${canvas.w}x${canvas.h} / video box ${box.width}x${box.height}`,
  );
}

/** Video-display px → comp-canvas px (scale by canvas/videoBox, per axis). */
export function displayToCanvas(d: Placement, canvas: CanvasDims, box: BoxSize): Placement {
  assertGeometry(canvas, box);
  return { x: (d.x * canvas.w) / box.width, y: (d.y * canvas.h) / box.height };
}

/** Comp-canvas px → video-display px — the exact inverse of displayToCanvas. */
export function canvasToDisplay(d: Placement, canvas: CanvasDims, box: BoxSize): Placement {
  assertGeometry(canvas, box);
  return { x: (d.x * box.width) / canvas.w, y: (d.y * box.height) / canvas.h };
}

/** Clamp a placement point inside the canvas — out-of-frame is a lint ERROR. */
export function clampToCanvas(p: Placement, canvas: CanvasDims): Placement {
  return {
    x: Math.min(Math.max(0, p.x), canvas.w),
    y: Math.min(Math.max(0, p.y), canvas.h),
  };
}

/** The platform-safe rect (canvas px). Throws if the margins swallow the canvas. */
export function safeRect(canvas: CanvasDims): {
  left: number;
  top: number;
  right: number;
  bottom: number;
} {
  const r = {
    left: SHORTS_SAFE_BOX.left,
    top: SHORTS_SAFE_BOX.top,
    right: canvas.w - SHORTS_SAFE_BOX.right,
    bottom: canvas.h - SHORTS_SAFE_BOX.bottom,
  };
  if (!(r.right > r.left && r.bottom > r.top)) {
    throw new Error(`safeRect: SAFE_BOX margins degenerate on a ${canvas.w}x${canvas.h} canvas`);
  }
  return r;
}

/** Is the placement point inside the platform-safe area (edges inclusive)? */
export function inSafeRect(p: Placement, canvas: CanvasDims): boolean {
  const r = safeRect(canvas);
  return p.x >= r.left && p.x <= r.right && p.y >= r.top && p.y <= r.bottom;
}

/** Nearest of `edges` within ±thr, or null (closer edge wins a tie). */
function snapAxis(v: number, edges: [number, number], thr: number): number | null {
  let best: number | null = null;
  for (const e of edges) {
    if (Math.abs(v - e) <= thr && (best === null || Math.abs(v - e) < Math.abs(v - best))) best = e;
  }
  return best;
}

export interface SnappedPlacement {
  p: Placement;
  snappedX: boolean;
  snappedY: boolean;
}

/** Soft-snap a placement to the safe-box edges; `thr` is per-axis canvas px. */
export function snapToSafeEdges(
  p: Placement,
  canvas: CanvasDims,
  thr: Placement,
): SnappedPlacement {
  const r = safeRect(canvas);
  const sx = snapAxis(p.x, [r.left, r.right], thr.x);
  const sy = snapAxis(p.y, [r.top, r.bottom], thr.y);
  return { p: { x: sx ?? p.x, y: sy ?? p.y }, snappedX: sx !== null, snappedY: sy !== null };
}

/** The preview iframe's comp-canvas transform: translate + uniform scale. */
export interface PreviewTransform extends Placement {
  s: number;
}

/**
 * The comp-canvas transform that honors `placement` as a CONTENT pin at any
 * scale: the renderer scales the comp clip uniformly ABOUT the placement point
 * (the content bbox top-left stays pinned at {x, y}), so the preview scales
 * the canvas by `s` about its own origin and translates it by
 * (point − s·origin) — content origin o then lands at exactly `point` for
 * every s. At s=1 this is byte-identical to the translate-only arithmetic
 * (scale absent = 1.0). Unmeasured (`origin` null): a placed comp falls back
 * to a raw-placement translate at `scale` — approximate until the origin
 * lands; an unplaced one stays untouched.
 */
export function previewTransform(
  point: Placement | null,
  origin: Placement | null,
  scale = 1,
): PreviewTransform {
  if (!point) return { x: 0, y: 0, s: 1 };
  if (!origin) return { x: point.x, y: point.y, s: scale };
  return { x: point.x - scale * origin.x, y: point.y - scale * origin.y, s: scale };
}

/**
 * The comp-canvas translate that honors `placement` as a CONTENT pin — the
 * scale-1 special case of `previewTransform` (kept: the pre-scale contract).
 */
export function previewTranslate(point: Placement | null, origin: Placement | null): Placement {
  const t = previewTransform(point, origin, 1);
  return { x: t.x, y: t.y };
}

export interface DragArgs {
  base: Placement; // committed placement at gesture start ({0,0} when absent)
  dxPx: number; // pointer delta since pointerdown, video-display px
  dyPx: number;
  canvas: CanvasDims;
  box: BoxSize;
  snap: boolean; // Alt held = false
}

/**
 * One pointermove → the live placement: convert the display delta to canvas
 * px, clamp inside the canvas, soft-snap to the safe edges (shorts canvas
 * only, ±PLACEMENT_SNAP_PX display px), and round to whole canvas px.
 */
export function dragPlacement(a: DragArgs): SnappedPlacement {
  const d = displayToCanvas({ x: a.dxPx, y: a.dyPx }, a.canvas, a.box);
  const raw = clampToCanvas({ x: a.base.x + d.x, y: a.base.y + d.y }, a.canvas);
  const round = (s: SnappedPlacement): SnappedPlacement => ({
    ...s,
    p: { x: Math.round(s.p.x), y: Math.round(s.p.y) },
  });
  if (!a.snap || !isShortsCanvas(a.canvas)) {
    return round({ p: raw, snappedX: false, snappedY: false });
  }
  const thr = displayToCanvas({ x: PLACEMENT_SNAP_PX, y: PLACEMENT_SNAP_PX }, a.canvas, a.box);
  return round(snapToSafeEdges(raw, a.canvas, thr));
}

// ---- UNIFORM SCALE (corner grips) ------------------------------------------
// CONTRACT: placement gains optional `scale` (0.25–1.5) — the renderer scales
// the rendered comp clip uniformly about the placement point; absent = 1.0
// byte-identical. The plan lint ERRORS outside these bounds, so the gesture
// clamps and the UI can never author that state. Own-screen never scales.

export const SCALE_MIN = 0.25;
export const SCALE_MAX = 1.5;
/** Soft-snap window around 100% (±3%). */
export const SCALE_SNAP = 0.03;

export type ScaleCorner = "tl" | "tr" | "bl" | "br";

const CORNER_SIGN: Record<ScaleCorner, Placement> = {
  tl: { x: -1, y: -1 },
  tr: { x: 1, y: -1 },
  bl: { x: -1, y: 1 },
  br: { x: 1, y: 1 },
};

export interface SnappedScale {
  s: number;
  snapped: boolean; // landed on 1.0 via the ±SCALE_SNAP window
  capped: boolean; // the raw drag left [SCALE_MIN, SCALE_MAX] and was clamped
}

/** The SCALED content bbox (canvas px) — top-left stays pinned at the point. */
export function scaledContentRect(
  pin: Placement,
  content: CanvasDims,
  scale: number,
): { left: number; top: number; width: number; height: number } {
  return { left: pin.x, top: pin.y, width: content.w * scale, height: content.h * scale };
}

export interface ScaleDragArgs {
  base: number; // committed scale at pointerdown (1 when absent)
  corner: ScaleCorner;
  dxPx: number; // pointer delta since pointerdown, video-display px
  dyPx: number;
  content: CanvasDims; // UNSCALED content bbox size (canvas px, measured in-iframe)
  canvas: CanvasDims;
  box: BoxSize;
  snap: boolean; // Alt held = false
}

/**
 * One pointermove on a corner grip → the live uniform scale. Least-squares
 * corner tracking: with the top-left pinned, the BR corner of the content box
 * sits at pin + s·(w, h), so dragging it by canvas delta d moves s by
 * (d·(w, h)) / |(w, h)|² — the exact projection onto the corner's path. The
 * other grips mirror by sign so an OUTWARD drag always grows. Clamps to
 * [SCALE_MIN, SCALE_MAX] (capped flag = the cap was hit), soft-snaps to 100%
 * (±SCALE_SNAP, Alt disables), and rounds to whole percent.
 */
export function scaleFromCornerDrag(a: ScaleDragArgs): SnappedScale {
  if (!(a.content.w > 0 && a.content.h > 0)) {
    throw new Error(`scaleFromCornerDrag: degenerate content bbox ${a.content.w}x${a.content.h}`);
  }
  const d = displayToCanvas({ x: a.dxPx, y: a.dyPx }, a.canvas, a.box);
  const sign = CORNER_SIGN[a.corner];
  const raw =
    a.base +
    (d.x * sign.x * a.content.w + d.y * sign.y * a.content.h) /
      (a.content.w * a.content.w + a.content.h * a.content.h);
  const clamped = Math.min(Math.max(raw, SCALE_MIN), SCALE_MAX);
  const capped = raw !== clamped;
  // 1e-9 keeps the ±SCALE_SNAP window edge inclusive under float noise.
  const snapped = a.snap && Math.abs(clamped - 1) <= SCALE_SNAP + 1e-9;
  return { s: snapped ? 1 : Math.round(clamped * 100) / 100, snapped, capped };
}
