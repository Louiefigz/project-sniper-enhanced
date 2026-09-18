// timeline-scale assertions — run with: npx tsx src/lib/producer/__tests__/timeline-scale.test.ts
import assert from "node:assert/strict";
import {
  GRID_MAX_THRESHOLD_S,
  MAX_PX_PER_SEC,
  MIN_PX_PER_SEC,
  SNAP_PX,
  clampScroll,
  contentWidth,
  filmstripCols,
  fitPxPerSec,
  fmtMmSs,
  fmtWindow,
  moveWindow,
  pxToTime,
  resolveSnap,
  snapMovedWindow,
  snapThresholdS,
  tickStep,
  timeToPx,
  trimWindow,
  zoomAtCursor,
  zoomToRange,
} from "../timeline-scale";

const close = (a: number, b: number, msg: string, eps = 1e-9) =>
  assert.ok(Math.abs(a - b) < eps, `${msg}: ${a} vs ${b}`);

// ---- px↔time round trips ----
for (const pps of [MIN_PX_PER_SEC, 1, 8.33, 120, MAX_PX_PER_SEC]) {
  for (const t of [0, 0.04166, 12.34, 3599.9]) {
    close(pxToTime(timeToPx(t, pps), pps), t, `round trip t=${t} pps=${pps}`);
  }
}

// ---- fit ----
close(fitPxPerSec(900, 108), 900 / 108, "fit = viewport/duration");
assert.equal(fitPxPerSec(10, 100000), MIN_PX_PER_SEC, "fit clamps to MIN");
assert.throws(() => fitPxPerSec(0, 100), /fitPxPerSec/, "zero viewport fails loudly");
assert.throws(() => fitPxPerSec(900, 0), /fitPxPerSec/, "zero duration fails loudly");

// ---- zoomAtCursor keeps the moment under the cursor stationary ----
{
  const z = { pxPerSec: 10, scrollLeft: 200 };
  const cursorX = 350; // time under cursor = (200+350)/10 = 55s
  const next = zoomAtCursor(z, cursorX, 2, 900, 300);
  assert.equal(next.pxPerSec, 20, "zoom factor applied");
  close((next.scrollLeft + cursorX) / next.pxPerSec, 55, "cursor time invariant across zoom-in");
  const back = zoomAtCursor(next, cursorX, 0.5, 900, 300);
  assert.equal(back.pxPerSec, 10, "zoom back out");
  close(back.scrollLeft, 200, "scroll restored after in+out");
}
// zoom-out to fit clamps scroll to 0 (content smaller than viewport)
{
  const next = zoomAtCursor({ pxPerSec: 10, scrollLeft: 500 }, 100, 0.05, 900, 100);
  assert.equal(next.scrollLeft, 0, "scroll clamps to 0 when content fits");
  assert.equal(next.pxPerSec, MIN_PX_PER_SEC, "pxPerSec clamps to MIN");
}
// clampScroll upper bound
assert.equal(clampScroll(99999, 10, 900, 100), 100 * 10 - 900, "scroll clamps to content-viewport");
assert.equal(contentWidth(0, 10), 1, "content width floors at 1px");

// ---- zoomToRange ----
{
  const z = zoomToRange(10, 20, 900, 108);
  close(z.pxPerSec, (900 * 0.8) / 10, "range fills 80% of viewport");
  const midPx = 15 * z.pxPerSec - z.scrollLeft;
  close(midPx, 450, "range midpoint centered");
  assert.throws(() => zoomToRange(20, 20, 900, 108), /empty range/, "empty range fails loudly");
}

// ---- tick step scales with zoom ----
assert.equal(tickStep(500), 0.25, "high zoom → sub-second ticks");
assert.ok(tickStep(8) >= 10, "low zoom → coarse ticks");
assert.equal(tickStep(0.05), 600, "extreme zoom-out → 10-min ticks");

// ---- filmstrip columns: quantized, monotonic, capped ----
assert.equal(filmstripCols(108, 8.33), 16, "fit zoom → base 16 cols");
{
  let prev = 0;
  for (const pps of [1, 5, 10, 20, 50, 100, 200, 500]) {
    const n = filmstripCols(108, pps);
    assert.ok(n >= prev, `cols monotonic with zoom (pps=${pps})`);
    prev = n;
  }
  assert.equal(filmstripCols(108, 500), 160, "high zoom hits the honest cap");
}

// ---- snap threshold: ALWAYS 8 screen px, whatever the zoom ----
close(snapThresholdS(100), 0.08, "8px at 100pps = 0.08s");
close(snapThresholdS(10), 0.8, "8px at 10pps = 0.8s (no seconds cap — px is the unit)");
for (const pps of [MIN_PX_PER_SEC, 5, 24, 100, MAX_PX_PER_SEC]) {
  close(snapThresholdS(pps) * pps, SNAP_PX, `threshold is ${SNAP_PX} screen px at pps=${pps}`);
}
assert.throws(() => snapThresholdS(0), /snapThresholdS/, "zero pps fails loudly");

// ---- whole-second grid gates OFF at coarse zoom (else it captures ALL drags) ----
{
  const coarse = snapThresholdS(5); // 1.6s radius — grid spacing 1s would capture everything
  assert.ok(coarse > GRID_MAX_THRESHOLD_S, "coarse-zoom threshold exceeds the grid gate");
  assert.equal(resolveSnap(13.37, [], coarse).snapped, null, "coarse zoom: no grid quantize");
  assert.equal(resolveSnap(13.37, [12.9], coarse).snapped, 12.9, "coarse zoom: explicit target (playhead) still snaps within 8px");
  const fine = snapThresholdS(100); // 0.08s ≤ gate → grid live
  assert.equal(resolveSnap(31.95, [], fine).snapped, 32, "fine zoom: grid snaps");
}

// ---- resolveSnap: each target class + miss ----
{
  const targets = [12.3, 45.6]; // playhead + a block edge
  assert.equal(resolveSnap(12.25, targets, 0.15).snapped, 12.3, "snaps to playhead target");
  assert.equal(resolveSnap(45.7, targets, 0.15).snapped, 45.6, "snaps to block edge");
  assert.equal(resolveSnap(31.9, targets, 0.15).snapped, 32, "snaps to whole second");
  assert.equal(resolveSnap(31.5, targets, 0.15).snapped, null, "no target in range → no snap");
  assert.equal(resolveSnap(31.5, targets, 0.15).t, 31.5, "miss returns t unchanged");
  // explicit target beats the whole-second grid on a tie
  assert.equal(resolveSnap(12.0, [12.0], 0.15).snapped, 12.0, "explicit target on tie");
  // nearer target wins
  assert.equal(resolveSnap(12.34, [12.3, 12.4], 0.15).snapped, 12.3, "nearest target wins");
}

// ---- Alt bypass = caller skips snap; raw geometry stays exact ----
{
  const raw = moveWindow({ start: 10.07, end: 14.07 }, 0.001, 108);
  close(raw.start, 10.071, "no snap applied in raw move (Alt path)");
}

// ---- moveWindow: clamp both ends, length preserved ----
{
  const w = moveWindow({ start: 2, end: 6 }, -5, 108);
  assert.deepEqual(w, { start: 0, end: 4 }, "clamped at 0, length kept");
  const w2 = moveWindow({ start: 100, end: 104 }, 10, 108);
  assert.deepEqual(w2, { start: 104, end: 108 }, "clamped at duration, length kept");
  assert.throws(() => moveWindow({ start: 5, end: 5 }, 1, 108), /moveWindow/, "empty window fails");
}

// ---- snapMovedWindow: closer edge wins, both edges shift together ----
{
  const targets = [20];
  const r = snapMovedWindow({ start: 19.9, end: 23.9 }, targets, 0.15);
  assert.deepEqual(r.win, { start: 20, end: 24 }, "start edge snapped, window shifted");
  const r2 = snapMovedWindow({ start: 16.06, end: 19.95 }, targets, 0.15);
  close(r2.win.end, 20, "end edge snapped (closer than start's whole-second)");
  close(r2.win.end - r2.win.start, 3.89, "length preserved through snap");
  const r3 = snapMovedWindow({ start: 16.5, end: 19.4 }, [], 0.05);
  assert.equal(r3.snapped, null, "no snap → window untouched");
}

// ---- trimWindow: min duration + bounds ----
{
  assert.deepEqual(trimWindow({ start: 10, end: 14 }, "start", 13.8, 108), { start: 13.5, end: 14 },
    "start trim stops at min duration 0.5s");
  assert.deepEqual(trimWindow({ start: 10, end: 14 }, "end", 10.1, 108), { start: 10, end: 10.5 },
    "end trim stops at min duration 0.5s");
  assert.deepEqual(trimWindow({ start: 10, end: 14 }, "start", -3, 108), { start: 0, end: 14 },
    "start clamps at 0");
  assert.deepEqual(trimWindow({ start: 10, end: 14 }, "end", 500, 108), { start: 10, end: 108 },
    "end clamps at duration");
  // block already shorter than the minimum near 0 never goes negative
  const w = trimWindow({ start: 0.1, end: 0.3 }, "start", 0.25, 108);
  assert.ok(w.start >= 0 && w.end === 0.3, "short-block start trim stays in bounds");
}

// ---- formatting ----
assert.equal(fmtWindow({ start: 12.3, end: 16.3 }), "12.3s → 16.3s · 4.0s", "drag tooltip format");
assert.equal(fmtMmSs(0), "00:00.0", "zero");
assert.equal(fmtMmSs(75.46), "01:15.5", "mm:ss.s rounding");
assert.equal(fmtMmSs(9.94), "00:09.9", "sub-10s zero-padded");

console.log("timeline-scale.test.ts: all assertions passed");
