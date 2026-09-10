/** Metadata arithmetic only: no observed pixels, rendering, caption clearance or RSS qualification. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { assertPresenterGraphWorkload, PRESENTER_GRAPH_PIXEL_LIMIT, type PresenterGraphWorkloadInput } from "../contracts/guided-presenter-workload";

function workload(patch: Partial<PresenterGraphWorkloadInput> = {}): PresenterGraphWorkloadInput {
  return { target: { mode: "longform", width: 1920, height: 1080 }, clock: { frameRate: "30/1", totalFrames: 900 },
    graphicCount: 0, captioned: false, presenterAssetCanvases: [{ width: 1920, height: 1080 }], ...patch };
}

test("combined input budget accepts exact64MiPixel and rejects one extra pixel without dropping an occurrence", () => {
  const input = workload({ graphicCount: 31, presenterAssetCanvases: [{ width: 736, height: 1024 }] });
  const result = assertPresenterGraphWorkload(input);
  assert.equal(result.inputPixels, PRESENTER_GRAPH_PIXEL_LIMIT);
  assert.equal(result.limitPixels, 67_108_864);
  assert.throws(() => assertPresenterGraphWorkload({ ...input,
    presenterAssetCanvases: [...input.presenterAssetCanvases, { width: 1, height: 1 }] }), /64MiPixel/);
});

test("every occurrence is counted, including repeated equal canvases and all-future disjoint windows", () => {
  const canvas = { width: 1920, height: 1080 };
  const result = assertPresenterGraphWorkload(workload({ graphicCount: 1, captioned: true,
    presenterAssetCanvases: [canvas, canvas, canvas] }));
  assert.equal(result.presenterOccurrenceCount, 3); assert.equal(result.captionPageCount, 1);
  assert.equal(result.inputPixels, 6 * 1920 * 1080);
  assert.match(result.scope, /not-observed-media-or-clearance/);
  assert.throws(() => assertPresenterGraphWorkload(workload({ presenterAssetCanvases: Array(32).fill(canvas) })), /64MiPixel/);
});

test("NTSC uses original full-page frame origin and one extra frame costs an entire native page", () => {
  const at = workload({ captioned: true, clock: { frameRate: "30000/1001", totalFrames: 899 } });
  const before = assertPresenterGraphWorkload(at);
  const after = assertPresenterGraphWorkload({ ...at, clock: { ...at.clock, totalFrames: 900 } });
  assert.equal(before.captionPageCount, 1); assert.equal(after.captionPageCount, 2);
  assert.equal(after.inputPixels - before.inputPixels, 1920 * 1080);
  const whole = assertPresenterGraphWorkload(workload({ captioned: true, clock: { frameRate: "30/1", totalFrames: 2701 } }));
  assert.equal(whole.captionPageCount, 4);
});

test("native portrait and landscape have equal work without claiming asset display geometry", () => {
  const landscape = assertPresenterGraphWorkload(workload());
  const portrait = assertPresenterGraphWorkload(workload({ target: { mode: "short", width: 1080, height: 1920 } }));
  assert.deepEqual(portrait, landscape);
  for (const target of [{ mode: "short", width: 1920, height: 1080 }, { mode: "longform", width: 3840, height: 2160 },
    { width: 1920, height: 1080 }, { mode: "longform", width: "1920", height: 1080 }]) {
    assert.throws(() => assertPresenterGraphWorkload(workload({ target })), /native1920/);
  }
});

test("unknown, oversized and coerced occurrence metadata refuses before any execution", () => {
  for (const presenterAssetCanvases of [[], [{ width: 4097, height: 2 }], [{ width: 4096, height: 2161 }],
    [{ width: NaN, height: 2 }], [{ width: 2, height: 0 }], Array(33).fill({ width: 2, height: 2 })]) {
    assert.throws(() => assertPresenterGraphWorkload(workload({ presenterAssetCanvases })));
  }
  for (const graphicCount of [-1, 129, 1.5, NaN, Infinity]) assert.throws(() => assertPresenterGraphWorkload(workload({ graphicCount })));
  assert.throws(() => assertPresenterGraphWorkload(workload({ captioned: 0 as unknown as boolean })));
});

test("original opening intake clock remains bounded and rational metadata cannot silently normalize", () => {
  for (const frameRate of ["30", "60/2", "030/1", "30/01", "61/1", "1/2", "1/0", "1/1/1", "10000000000/1"]) {
    assert.throws(() => assertPresenterGraphWorkload(workload({ clock: { frameRate, totalFrames: 900 } })));
  }
  for (const totalFrames of [0, -1, 0.5, NaN, Infinity, 72_001]) {
    assert.throws(() => assertPresenterGraphWorkload(workload({ clock: { frameRate: "30/1", totalFrames } })));
  }
  assertPresenterGraphWorkload(workload({ clock: { frameRate: "1/1", totalFrames: 72_000 } }));
});
