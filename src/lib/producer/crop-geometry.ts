// Pure crop-rect geometry for the LAYOUT crop modal. Every rect is a
// `CropRect` — [x, y, w, h] NORMALIZED to the source frame (0-1). The aspect
// lock works in PIXEL space: a crop matching a `cellW x cellH` output cell on
// a `srcW x srcH` source satisfies (w*srcW)/(h*srcH) = cellW/cellH, so the
// normalized width per normalized height is a single constant
// k = (cellW/cellH) * (srcH/srcW). All functions are pure and exported so the
// drag math is verifiable with one-off tsx assertions (no browser needed).

import type { CropRect } from "./edit-plan";

export type Handle = "nw" | "n" | "ne" | "e" | "se" | "s" | "sw" | "w";

export interface Dims {
  w: number;
  h: number;
}

export type CellRegion = "fill" | "top" | "bottom";

/** The 9:16 shorts canvas the layout contract vstacks into. */
export const OUT_W = 1080;
export const OUT_H = 1920;

/** Smallest normalized crop height a resize can reach (5% of the frame). */
const MIN_H = 0.05;

export function evenPx(n: number): number {
  return Math.round(n / 2) * 2;
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(Math.max(n, lo), hi);
}

/**
 * Output-pixel dims of the target cell a crop feeds. Split top =
 * 1080 x even(round(1920*frac)); bottom = the remainder — the same snap the
 * renderer applies, so the modal's lock previews exactly what the viewer sees.
 */
export function cellDims(region: CellRegion, frac: number): Dims {
  if (region === "fill") return { w: OUT_W, h: OUT_H };
  const topH = evenPx(OUT_H * frac);
  return region === "top" ? { w: OUT_W, h: topH } : { w: OUT_W, h: OUT_H - topH };
}

/** Normalized-width-per-normalized-height constant for the aspect lock. */
export function aspectK(cell: Dims, src: Dims): number {
  return (cell.w / cell.h) * (src.h / src.w);
}

/** Largest centered crop of the locked aspect that fits the source frame. */
export function centeredCrop(k: number): CropRect {
  const h = Math.min(1, 1 / k);
  const w = h * k;
  return [(1 - w) / 2, (1 - h) / 2, w, h];
}

/**
 * Conform an incoming rect to the locked aspect (e.g. a stored split crop
 * after the frac slider moved): keep its center and height, derive the width
 * from k, shrink to fit, clamp inside the frame. Deterministic — no guessing.
 */
export function fitToAspect(rect: CropRect, k: number): CropRect {
  const [x, y, w, h] = rect;
  const cx = x + w / 2;
  const cy = y + h / 2;
  let nh = clamp(h, MIN_H, Math.min(1, 1 / k));
  let nw = nh * k;
  if (nw > 1) {
    nw = 1;
    nh = nw / k;
  }
  return [clamp(cx - nw / 2, 0, 1 - nw), clamp(cy - nh / 2, 0, 1 - nh), nw, nh];
}

/** Translate a rect by normalized deltas, clamped inside the frame. */
export function moveCrop(rect: CropRect, dx: number, dy: number): CropRect {
  const [x, y, w, h] = rect;
  return [clamp(x + dx, 0, 1 - w), clamp(y + dy, 0, 1 - h), w, h];
}

/**
 * Resize from one of the 8 handles, keeping the pixel aspect (k) locked and
 * the rect inside the frame. The handle's opposite edge/corner anchors:
 * corner → opposite corner fixed; e/w edge → opposite edge + vertical center
 * fixed; n/s edge → opposite edge + horizontal center fixed. Corner drags take
 * the dominant axis (the delta implying the larger height change).
 */
export function resizeCrop(
  rect: CropRect,
  handle: Handle,
  delta: { dx: number; dy: number },
  k: number,
): CropRect {
  const [x, y, w, h] = rect;
  const east = handle.includes("e");
  const west = handle.includes("w");
  const north = handle.includes("n");
  const south = handle.includes("s");
  const dw = east ? delta.dx : west ? -delta.dx : 0;
  const dh = south ? delta.dy : north ? -delta.dy : 0;
  const dhFromW = dw / k;
  const grow = Math.abs(dhFromW) >= Math.abs(dh) ? dhFromW : dh;
  // Max size the anchor allows before the rect would leave the frame.
  const maxW = west ? x + w : east ? 1 - x : 2 * Math.min(x + w / 2, 1 - x - w / 2);
  const maxHy = north ? y + h : south ? 1 - y : 2 * Math.min(y + h / 2, 1 - y - h / 2);
  const maxH = Math.min(maxHy, maxW / k);
  const nh = clamp(h + grow, Math.min(MIN_H, maxH), maxH);
  const nw = nh * k;
  const nx = west ? x + w - nw : east ? x : x + w / 2 - nw / 2;
  const ny = north ? y + h - nh : south ? y : y + h / 2 - nh / 2;
  return [nx, ny, nw, nh];
}
