// placement-geometry assertions — run with:
//   npx tsx src/lib/producer/__tests__/placement-geometry.test.ts
import assert from "node:assert/strict";
import {
  PLACEMENT_SNAP_PX,
  SCALE_MAX,
  SCALE_MIN,
  SCALE_SNAP,
  SHORTS_CANVAS,
  SHORTS_SAFE_BOX,
  canvasToDisplay,
  clampToCanvas,
  displayToCanvas,
  dragPlacement,
  inSafeRect,
  isShortsCanvas,
  previewTransform,
  previewTranslate,
  safeRect,
  scaleFromCornerDrag,
  scaledContentRect,
  snapToSafeEdges,
  type BoxSize,
  type CanvasDims,
  type ScaleCorner,
} from "../placement-geometry";

const close = (a: number, b: number, msg: string, eps = 1e-9) =>
  assert.ok(Math.abs(a - b) < eps, `${msg}: ${a} vs ${b}`);

const SHORTS: CanvasDims = { w: 1080, h: 1920 };
const LONG: CanvasDims = { w: 1920, h: 1080 };

// ---- display↔canvas round trips at multiple zoom/letterbox geometries ----
const GEOMETRIES: [CanvasDims, BoxSize][] = [
  [SHORTS, { width: 270, height: 480 }], // uniform 0.25 (small pane)
  [SHORTS, { width: 1080, height: 1920 }], // 1:1
  [SHORTS, { width: 405, height: 720 }], // uniform 0.375
  [SHORTS, { width: 300, height: 480 }], // NON-uniform (stretched preview)
  [LONG, { width: 640, height: 360 }], // longform uniform
  [LONG, { width: 640, height: 480 }], // longform non-uniform
];
for (const [canvas, box] of GEOMETRIES) {
  for (const d of [
    { x: 0, y: 0 },
    { x: 1, y: 1 },
    { x: -37.5, y: 12.25 },
    { x: box.width / 2, y: box.height / 3 },
  ]) {
    const rt = canvasToDisplay(displayToCanvas(d, canvas, box), canvas, box);
    close(rt.x, d.x, `display round trip x ${canvas.w}x${canvas.h}/${box.width}x${box.height}`);
    close(rt.y, d.y, `display round trip y ${canvas.w}x${canvas.h}/${box.width}x${box.height}`);
    const c = { x: d.x * 4, y: d.y * 4 };
    const rt2 = displayToCanvas(canvasToDisplay(c, canvas, box), canvas, box);
    close(rt2.x, c.x, `canvas round trip x ${box.width}x${box.height}`);
    close(rt2.y, c.y, `canvas round trip y ${box.width}x${box.height}`);
  }
}

// half the box width maps to half the canvas width, per axis
for (const [canvas, box] of GEOMETRIES) {
  const d = displayToCanvas({ x: box.width / 2, y: box.height / 2 }, canvas, box);
  close(d.x, canvas.w / 2, "half-box → half-canvas x");
  close(d.y, canvas.h / 2, "half-box → half-canvas y");
}

// ---- fail loudly on degenerate geometry ----
assert.throws(() => displayToCanvas({ x: 1, y: 1 }, SHORTS, { width: 0, height: 480 }), /geometry/);
assert.throws(() => canvasToDisplay({ x: 1, y: 1 }, { w: 0, h: 1920 }, { width: 270, height: 480 }), /geometry/);

// ---- clamp ----
assert.deepEqual(clampToCanvas({ x: -5, y: 2000 }, SHORTS), { x: 0, y: 1920 });
assert.deepEqual(clampToCanvas({ x: 500, y: 900 }, SHORTS), { x: 500, y: 900 });

// ---- safe rect (mirrors producer_config.SAFE_BOX on 1080x1920) ----
assert.ok(isShortsCanvas(SHORTS) && !isShortsCanvas(LONG), "shorts-canvas gate");
assert.deepEqual(safeRect(SHORTS), { left: 60, top: 250, right: 930, bottom: 1400 });
assert.equal(SHORTS_SAFE_BOX.bottom, 520, "SAFE_BOX mirror intact");
assert.deepEqual(SHORTS_CANVAS, { w: 1080, h: 1920 });
assert.throws(() => safeRect({ w: 100, h: 100 }), /degenerate/, "margins swallow tiny canvas");

// ---- inSafeRect (edges inclusive) ----
assert.ok(inSafeRect({ x: 60, y: 250 }, SHORTS), "top-left safe corner");
assert.ok(inSafeRect({ x: 930, y: 1400 }, SHORTS), "bottom-right safe corner");
assert.ok(!inSafeRect({ x: 59, y: 900 }, SHORTS), "1px left of safe");
assert.ok(!inSafeRect({ x: 500, y: 1401 }, SHORTS), "1px below safe");
assert.ok(!inSafeRect({ x: 0, y: 0 }, SHORTS), "origin is unsafe (top-left margins)");

// ---- snapToSafeEdges (per-axis thresholds) ----
{
  const thr = { x: 12, y: 12 };
  const s = snapToSafeEdges({ x: 70, y: 900 }, SHORTS, thr);
  assert.deepEqual(s, { p: { x: 60, y: 900 }, snappedX: true, snappedY: false });
  const s2 = snapToSafeEdges({ x: 925, y: 1408 }, SHORTS, thr);
  assert.deepEqual(s2, { p: { x: 930, y: 1400 }, snappedX: true, snappedY: true });
  const s3 = snapToSafeEdges({ x: 73, y: 240 }, SHORTS, thr);
  assert.deepEqual(s3, { p: { x: 73, y: 250 }, snappedX: false, snappedY: true }, "x 13px = beyond thr, y 10px = snaps");
  const s4 = snapToSafeEdges({ x: 495, y: 800 }, SHORTS, thr);
  assert.deepEqual(s4, { p: { x: 495, y: 800 }, snappedX: false, snappedY: false }, "mid = no snap");
}

// ---- dragPlacement: convert + clamp + snap + integer px ----
{
  const box = { width: 270, height: 480 }; // 0.25 scale
  // from auto ({0,0}): half the box → half the canvas
  const r = dragPlacement({ base: { x: 0, y: 0 }, dxPx: 135, dyPx: 240, canvas: SHORTS, box, snap: false });
  assert.deepEqual(r.p, { x: 540, y: 960 }, "half-box drag lands mid-canvas");
  // clamps: leftward drag from auto can't leave the canvas (out-of-frame = lint ERROR)
  const l = dragPlacement({ base: { x: 0, y: 0 }, dxPx: -50, dyPx: -50, canvas: SHORTS, box, snap: false });
  assert.deepEqual(l.p, { x: 0, y: 0 }, "clamped at origin");
  const br = dragPlacement({ base: { x: 1000, y: 1900 }, dxPx: 100, dyPx: 100, canvas: SHORTS, box, snap: false });
  assert.deepEqual(br.p, { x: 1080, y: 1920 }, "clamped at canvas max");
  // integer px always
  const f = dragPlacement({ base: { x: 0, y: 0 }, dxPx: 33.3, dyPx: 77.7, canvas: SHORTS, box, snap: false });
  assert.ok(Number.isInteger(f.p.x) && Number.isInteger(f.p.y), "integer canvas px");
}

// snap radius is DISPLAY px: ±12 display px = ±48 canvas px at 0.25 scale
{
  const box = { width: 270, height: 480 };
  const nearLeft = dragPlacement({ base: { x: 100, y: 900 }, dxPx: -0.5, dyPx: 0, canvas: SHORTS, box, snap: true });
  assert.deepEqual(nearLeft.p, { x: 60, y: 900 }, "x 98 → snaps to 60 (within 48 canvas px)");
  assert.ok(nearLeft.snappedX && !nearLeft.snappedY, "snap flags per axis");
  const past = dragPlacement({ base: { x: 150, y: 900 }, dxPx: 0, dyPx: 0, canvas: SHORTS, box, snap: true });
  assert.deepEqual(past.p, { x: 150, y: 900 }, "x 150 is 90 canvas px away — no snap");
  // Alt (snap:false) passes straight through
  const alt = dragPlacement({ base: { x: 100, y: 900 }, dxPx: -0.5, dyPx: 0, canvas: SHORTS, box, snap: false });
  assert.deepEqual(alt.p, { x: 98, y: 900 }, "Alt disables the snap");
}

// at 1:1 scale the radius is exactly ±PLACEMENT_SNAP_PX canvas px
{
  const box = { width: 1080, height: 1920 };
  const inThr = dragPlacement({ base: { x: 60 + PLACEMENT_SNAP_PX, y: 900 }, dxPx: 0, dyPx: 0, canvas: SHORTS, box, snap: true });
  assert.deepEqual(inThr.p, { x: 60, y: 900 }, "exactly at the radius → snaps");
  const outThr = dragPlacement({ base: { x: 60 + PLACEMENT_SNAP_PX + 1, y: 900 }, dxPx: 0, dyPx: 0, canvas: SHORTS, box, snap: true });
  assert.deepEqual(outThr.p, { x: 60 + PLACEMENT_SNAP_PX + 1, y: 900 }, "1px past → no snap");
}

// longform canvas: drag works, safe-box snapping never applies
{
  const box = { width: 640, height: 360 };
  const r = dragPlacement({ base: { x: 0, y: 0 }, dxPx: 64, dyPx: 36, canvas: LONG, box, snap: true });
  assert.deepEqual(r, { p: { x: 192, y: 108 }, snappedX: false, snappedY: false }, "longform = no SAFE_BOX snap");
  assert.throws(() => inSafeRect({ x: 0, y: 0 }, { w: 100, h: 100 }), /degenerate/);
}

// ---- previewTranslate: placement is a CONTENT pin, not a canvas translate ----
{
  // The render pins the measured content top-left AT placement (proven:
  // authored alpha bbox (303,35) + offset (-183,345) → content at (120,380)
  // for placement {120,380}). The preview must land the SAME point.
  const origin = { x: 303, y: 35 }; // icon-badge-wide's authored content origin
  const pin = { x: 120, y: 380 };
  const t = previewTranslate(pin, origin);
  assert.deepEqual(t, { x: -183, y: 345 }, "translate = placement − origin (the compositor's offset)");
  assert.deepEqual({ x: origin.x + t.x, y: origin.y + t.y }, pin, "content lands exactly at the pin");
  // unplaced (no live point): content stays at its authored spot
  assert.deepEqual(previewTranslate(null, origin), { x: 0, y: 0 }, "unplaced = untranslated");
  // origin not yet measured: placed comps fall back to a raw translate (approx)
  assert.deepEqual(previewTranslate(pin, null), pin, "pre-measure fallback = raw placement");
  assert.deepEqual(previewTranslate(null, null), { x: 0, y: 0 }, "nothing known = untouched");
}

// dragging FROM AUTO starts the gesture at the content's measured origin, so a
// pure click-release (zero delta) commits the content exactly where it sits.
{
  const box = { width: 480, height: 270 }; // longform 0.25 scale
  const origin = { x: 303, y: 35 };
  const zero = dragPlacement({ base: origin, dxPx: 0, dyPx: 0, canvas: LONG, box, snap: false });
  assert.deepEqual(zero.p, origin, "zero-delta drag from auto pins the authored spot");
  const moved = dragPlacement({ base: origin, dxPx: 25, dyPx: -5, canvas: LONG, box, snap: false });
  assert.deepEqual(moved.p, { x: 403, y: 15 }, "display delta lands content origin + canvas delta");
}

// ---- previewTransform: the scale generalization of the CONTENT pin ----
{
  const origin = { x: 303, y: 35 };
  const pin = { x: 120, y: 380 };
  // s = 1 is byte-identical to previewTranslate (scale absent = 1.0)
  const t1 = previewTransform(pin, origin, 1);
  assert.deepEqual({ x: t1.x, y: t1.y }, previewTranslate(pin, origin), "s=1 == previewTranslate");
  assert.equal(t1.s, 1);
  // pin invariance: content origin lands EXACTLY at the pin for every s
  for (const s of [0.25, 0.5, 1, 1.28, 1.5]) {
    const t = previewTransform(pin, origin, s);
    close(t.x + s * origin.x, pin.x, `pin invariance x @ s=${s}`);
    close(t.y + s * origin.y, pin.y, `pin invariance y @ s=${s}`);
    assert.equal(t.s, s, "transform carries the scale");
  }
  // unplaced: untouched regardless of scale (scale requires placement)
  assert.deepEqual(previewTransform(null, origin, 1.4), { x: 0, y: 0, s: 1 }, "unplaced = identity");
  assert.deepEqual(previewTransform(null, null, 1.4), { x: 0, y: 0, s: 1 });
  // pre-measure fallback: raw translate at the committed scale (approx)
  assert.deepEqual(previewTransform(pin, null, 1.3), { x: 120, y: 380, s: 1.3 }, "pre-measure fallback");
}

// ---- scaledContentRect: top-left pinned, size × scale ----
assert.deepEqual(scaledContentRect({ x: 100, y: 200 }, { w: 300, h: 400 }, 1.5), {
  left: 100,
  top: 200,
  width: 450,
  height: 600,
});
assert.deepEqual(scaledContentRect({ x: 60, y: 250 }, { w: 300, h: 400 }, 1), {
  left: 60,
  top: 250,
  width: 300,
  height: 400,
});

// ---- scaleFromCornerDrag: display→scale about the pin ----
{
  const canvas = SHORTS;
  const box = { width: 1080, height: 1920 }; // 1:1 — display px == canvas px
  const content = { w: 300, h: 400 }; // |(w,h)|² = 250000
  const drag = (corner: ScaleCorner, dxPx: number, dyPx: number, base = 1, snap = false) =>
    scaleFromCornerDrag({ base, corner, dxPx, dyPx, content, canvas, box, snap });

  // BR tracks the corner exactly: pin + s·(w,h) — outward (w/2, h/2) = +0.5
  assert.deepEqual(drag("br", 150, 200), { s: 1.5, snapped: false, capped: false }, "BR outward grows");
  assert.deepEqual(drag("br", -75, -100), { s: 0.75, snapped: false, capped: false }, "BR inward shrinks");
  // corner sign mirroring: TL inward (down-right) shrinks; TR up-right grows; BL down-left grows
  assert.deepEqual(drag("tl", 75, 100).s, 0.75, "TL inward shrinks");
  assert.deepEqual(drag("tl", -75, -100).s, 1.25, "TL outward grows");
  assert.deepEqual(drag("tr", 150, -200).s, 1.5, "TR up-right grows");
  assert.deepEqual(drag("bl", -150, 200).s, 1.5, "BL down-left grows");

  // clamp [SCALE_MIN, SCALE_MAX] with the cap flagged when hit
  assert.deepEqual(drag("br", 300, 400), { s: SCALE_MAX, snapped: false, capped: true }, "clamped at max");
  assert.deepEqual(drag("br", -75, -100, 0.3), { s: SCALE_MIN, snapped: false, capped: true }, "clamped at min");
  assert.ok(!drag("br", 150, 200).capped, "landing exactly ON the bound is not capped");

  // soft snap at 100% (±SCALE_SNAP): raw 1.02 → 1 with snap, 1.02 without (Alt)
  assert.equal(SCALE_SNAP, 0.03, "±3% window");
  assert.deepEqual(drag("br", 0, 12.5, 1, true), { s: 1, snapped: true, capped: false }, "raw 1.02 snaps to 100%");
  assert.deepEqual(drag("br", 0, 12.5, 1, false).s, 1.02, "Alt disables the snap");
  assert.deepEqual(drag("br", 0, 18.75, 1, true).s, 1, "raw 1.03 = window edge, snaps");
  const past = drag("br", 0, 25, 1, true); // raw 1.04 — outside the window
  assert.deepEqual(past, { s: 1.04, snapped: false, capped: false }, "past the window = no snap");

  // whole-percent rounding
  assert.equal(drag("br", 0, 80).s, 1.13, "raw 1.128 rounds to a whole percent");
  assert.ok(Number.isInteger(Math.round(drag("br", 33.3, 77.7).s * 100)), "always whole percent");

  // the delta is DISPLAY px: at 0.5 preview scale the same gesture doubles in canvas px
  const half = { width: 540, height: 960 };
  const r = scaleFromCornerDrag({ base: 1, corner: "br", dxPx: 75, dyPx: 100, content, canvas, box: half, snap: false });
  assert.equal(r.s, 1.5, "display delta converts per the preview scale");

  // degenerate content bbox fails loudly (never guess a scale)
  assert.throws(() => drag("br", 10, 10, 1) && scaleFromCornerDrag({ base: 1, corner: "br", dxPx: 1, dyPx: 1, content: { w: 0, h: 400 }, canvas, box, snap: false }), /degenerate/);
}

console.log("placement-geometry: all assertions passed");
