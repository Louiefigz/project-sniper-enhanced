// The ONE px↔time transform behind every timeline lane, the ruler, the
// playhead, and the drag/trim/snap interactions. Pure functions only — the
// timeline components hold the state (pxPerSec + the scroll container) and
// call in here for the geometry, so all of it is npx-tsx testable
// (__tests__/timeline-scale.test.ts).

export const MIN_PX_PER_SEC = 0.5; // 20-min video in a ~600px viewport
export const MAX_PX_PER_SEC = 500; // sub-frame precision at 24fps

export function clampPxPerSec(v: number): number {
  if (!Number.isFinite(v)) throw new Error(`clampPxPerSec: non-finite ${v}`);
  return Math.min(MAX_PX_PER_SEC, Math.max(MIN_PX_PER_SEC, v));
}

export const timeToPx = (t: number, pxPerSec: number): number => t * pxPerSec;
export const pxToTime = (px: number, pxPerSec: number): number => px / pxPerSec;

/** Width of the scrollable timeline content for a duration at a zoom. */
export const contentWidth = (duration: number, pxPerSec: number): number =>
  Math.max(1, duration * pxPerSec);

/** The zoom that fits the whole video in the viewport (the Fit button / default). */
export function fitPxPerSec(viewportPx: number, duration: number): number {
  if (viewportPx <= 0 || duration <= 0) {
    throw new Error(`fitPxPerSec: viewport ${viewportPx}px / duration ${duration}s`);
  }
  return clampPxPerSec(viewportPx / duration);
}

/** Clamp a scrollLeft into [0, contentWidth - viewport]. */
export function clampScroll(
  scrollLeft: number,
  pxPerSec: number,
  viewportPx: number,
  duration: number,
): number {
  return Math.max(0, Math.min(scrollLeft, contentWidth(duration, pxPerSec) - viewportPx));
}

export interface ZoomState {
  pxPerSec: number;
  scrollLeft: number;
}

/**
 * Zoom by `factor` keeping the moment under the cursor stationary on screen:
 * tCursor = (scrollLeft + cursorX) / pxPerSec is invariant across the zoom.
 * `cursorX` is viewport-relative px (clientX - viewport left).
 */
export function zoomAtCursor(
  z: ZoomState,
  cursorX: number,
  factor: number,
  viewportPx: number,
  duration: number,
): ZoomState {
  const pxPerSec = clampPxPerSec(z.pxPerSec * factor);
  const tCursor = (z.scrollLeft + cursorX) / z.pxPerSec;
  const scrollLeft = clampScroll(tCursor * pxPerSec - cursorX, pxPerSec, viewportPx, duration);
  return { pxPerSec, scrollLeft };
}

/** Zoom + scroll that shows [a, b] filling ~80% of the viewport, centered. */
export function zoomToRange(
  a: number,
  b: number,
  viewportPx: number,
  duration: number,
): ZoomState {
  if (!(b > a)) throw new Error(`zoomToRange: empty range ${a}–${b}`);
  const pxPerSec = clampPxPerSec((viewportPx * 0.8) / (b - a));
  const mid = (a + b) / 2;
  const scrollLeft = clampScroll(mid * pxPerSec - viewportPx / 2, pxPerSec, viewportPx, duration);
  return { pxPerSec, scrollLeft };
}

/** Ruler tick step (s) keeping labels ≥ ~70px apart at the current zoom. */
export function tickStep(pxPerSec: number): number {
  const steps = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];
  for (const s of steps) if (s * pxPerSec >= 70) return s;
  return 600;
}

// FILMSTRIP RESOLUTION — the sprite route tiles the WHOLE video (cached by
// (path, mtime, n)), so n is quantized: a continuous n would regenerate a
// sprite on every zoom tick. HONEST CAP: n never exceeds FILMSTRIP_MAX_COLS
// (route-enforced too) — beyond ~15k sprite px the PNG gets silly, so at high
// zoom the thumbs stretch instead of gaining new frames. Visible-window tiling
// would fix that but needs a windowed cache keyed by scroll — not "simple",
// deliberately not built.
export const FILMSTRIP_TILE_PX = 96;
export const FILMSTRIP_MAX_COLS = 160;
const FILMSTRIP_STEPS = [16, 32, 48, 80, 120, FILMSTRIP_MAX_COLS];

export function filmstripCols(duration: number, pxPerSec: number): number {
  const want = Math.ceil(contentWidth(duration, pxPerSec) / FILMSTRIP_TILE_PX);
  for (const q of FILMSTRIP_STEPS) if (q >= want) return q;
  return FILMSTRIP_MAX_COLS;
}

// SNAP — ±8 SCREEN px at the current zoom, converted to seconds (8/pps).
// Screen px is the unit that matches the hand: at 500pps that's ±0.016s
// (sub-frame), at 5pps ±1.6s — either way 8px of mouse travel, so snapping to
// the playhead / block edges feels identical at both zoom extremes. (The old
// 0.15s cap made the radius SUB-PIXEL below ~50pps — snap was dead at fit
// zoom.) The whole-second grid participates only while it's resolvable at the
// current zoom (threshold ≤ GRID_STEP_S/3 ⇒ pps ≥ 24): with a coarser zoom
// every position sits within radius of SOME second and the grid would
// quantize ALL drags. Alt bypasses snapping entirely (the caller skips these).
export const SNAP_PX = 8;
export const GRID_STEP_S = 1; // whole-second snap grid
export const GRID_MAX_THRESHOLD_S = GRID_STEP_S / 3;

export function snapThresholdS(pxPerSec: number): number {
  if (!(pxPerSec > 0)) throw new Error(`snapThresholdS: non-positive pxPerSec ${pxPerSec}`);
  return SNAP_PX / pxPerSec;
}

export interface SnapResult {
  t: number;
  snapped: number | null; // the target hit, or null = no snap
}

/**
 * Nearest snap target within ±threshold. Targets = the explicit list (playhead,
 * other blocks' edges) plus — only while the grid is resolvable at this zoom
 * (thresholdS ≤ GRID_MAX_THRESHOLD_S) — the whole-second grid; explicit
 * targets win ties.
 */
export function resolveSnap(t: number, targets: number[], thresholdS: number): SnapResult {
  let best: number | null = null;
  let bestD = thresholdS;
  for (const target of targets) {
    const d = Math.abs(t - target);
    if (d <= bestD) {
      best = target;
      bestD = d;
    }
  }
  if (thresholdS <= GRID_MAX_THRESHOLD_S) {
    const sec = Math.round(t / GRID_STEP_S) * GRID_STEP_S;
    const dSec = Math.abs(t - sec);
    if (dSec < bestD || (best === null && dSec <= bestD)) best = sec;
  }
  return best === null ? { t, snapped: null } : { t: best, snapped: best };
}

export interface Win {
  start: number;
  end: number;
}

export const MIN_GRAPHIC_S = 0.5;

/** Move a window by delta, length preserved, clamped inside [0, duration]. */
export function moveWindow(w: Win, delta: number, duration: number): Win {
  const len = w.end - w.start;
  if (len <= 0 || duration <= 0) {
    throw new Error(`moveWindow: window ${w.start}–${w.end}s / duration ${duration}s`);
  }
  const start = Math.min(Math.max(0, w.start + delta), Math.max(0, duration - len));
  return { start, end: start + len };
}

/** Snap a MOVED window: try both edges against the targets, shift by the closer hit. */
export function snapMovedWindow(w: Win, targets: number[], thresholdS: number): {
  win: Win;
  snapped: number | null;
} {
  const s = resolveSnap(w.start, targets, thresholdS);
  const e = resolveSnap(w.end, targets, thresholdS);
  const ds = s.snapped === null ? Infinity : Math.abs(s.t - w.start);
  const de = e.snapped === null ? Infinity : Math.abs(e.t - w.end);
  if (ds === Infinity && de === Infinity) return { win: w, snapped: null };
  const shift = ds <= de ? s.t - w.start : e.t - w.end;
  return {
    win: { start: w.start + shift, end: w.end + shift },
    snapped: ds <= de ? (s.snapped as number) : (e.snapped as number),
  };
}

/** Trim one edge to `t`, honoring min duration and the [0, duration] bounds. */
export function trimWindow(w: Win, edge: "start" | "end", t: number, duration: number): Win {
  if (edge === "start") {
    return { start: Math.max(0, Math.min(t, w.end - MIN_GRAPHIC_S)), end: w.end };
  }
  return { start: w.start, end: Math.min(duration, Math.max(t, w.start + MIN_GRAPHIC_S)) };
}

/** Drag tooltip: "12.3s → 16.3s · 4.0s". */
export function fmtWindow(w: Win): string {
  return `${w.start.toFixed(1)}s → ${w.end.toFixed(1)}s · ${(w.end - w.start).toFixed(1)}s`;
}

/** mm:ss.s — the Ask-Claude range prefix + selection labels. */
export function fmtMmSs(t: number): string {
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${String(m).padStart(2, "0")}:${s < 10 ? "0" : ""}${s.toFixed(1)}`;
}
