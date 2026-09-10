import assert from "node:assert/strict";
import { test } from "node:test";
import { assertPresenterLayoutGeometry, parsePresenterLayoutV1, PRESENTER_LAYOUT_MAX_FRAMES } from "../contracts/presenter-layout-v1";
import { LANDSCAPE, layoutSelection, type Row } from "./_presenter-layout-fixture";

test("all three declared layouts preserve explicit source order and input bytes", () => {
  for (const kind of ["inset", "bubble", "split"] as const) {
    const value = layoutSelection(kind), before = JSON.stringify(value);
    assert.deepEqual(parsePresenterLayoutV1(value), value);
    assertPresenterLayoutGeometry(value, LANDSCAPE);
    assert.equal(JSON.stringify(value), before);
    assert.deepEqual(value.sourceIds, ["raw-2", "raw-1"]);
  }
});

test("portrait bubble and both split axes use actual pixel rather than normalized square geometry", () => {
  const portrait = { ...layoutSelection("bubble"), presenterCrop: { x: 0, y: 0.21875, width: 1, height: 0.5625 },
    protectedPresenterRect: { x: 0.3, y: 0.4, width: 0.4, height: 0.2 },
    presenterRect: { x: 0.5, y: 0.75, width: 0.4, height: 0.225 } };
  assertPresenterLayoutGeometry(portrait, { width: 1080, height: 1920 });
  const vertical = { ...layoutSelection("split"), presenterCrop: { x: 0, y: 0, width: 1, height: 0.5 },
    protectedPresenterRect: { x: 0.2, y: 0.1, width: 0.6, height: 0.3 },
    presenterRect: { x: 0, y: 0.5, width: 1, height: 0.5 }, presentationRect: { x: 0, y: 0, width: 1, height: 0.5 } };
  assertPresenterLayoutGeometry(vertical, LANDSCAPE);
});

test("the closed declaration cannot carry paths, tracking, asset audio or approval metadata", () => {
  for (const patch of [{ schemaVersion: true }, { cropSpace: "source-pixels" }, { presentationFit: "fill" },
    { assetAudio: "mix" }, { easing: "linear" }, { track: true }, { layout: ["inset"] }, { sourceId: "raw-1" },
    { path: "/tmp/unadmitted.mp4" }, { creativeApproved: true }, { assetId: [] }, { assetId: " " }]) {
    assert.throws(() => parsePresenterLayoutV1({ ...layoutSelection(), ...patch }), JSON.stringify(patch));
  }
  const { protectedPresenterRect: _removed, ...missing } = layoutSelection(); void _removed;
  assert.throws(() => parsePresenterLayoutV1(missing), /missing/);
});

test("source IDs are ordered, unique and bounded without coercion or inferred replacements", () => {
  for (const sourceIds of [[], ["raw-1", "raw-1"], [" "], [true], Array(129).fill("raw-1"), ["x".repeat(129)]]) {
    assert.throws(() => parsePresenterLayoutV1({ ...layoutSelection(), sourceIds }));
  }
});

test("all rectangle numbers and manual crop bounds fail closed without clamping", () => {
  for (const number of [false, null, "0", NaN, Infinity, -Infinity, -0, -1]) {
    assert.throws(() => parsePresenterLayoutV1({ ...layoutSelection(), presenterCrop: { x: number, y: 0, width: 1, height: 1 } }));
  }
  for (const presenterCrop of [{ x: 0, y: 0, width: 0.049, height: 1 }, { x: 0.6, y: 0, width: 0.5, height: 1 },
    { x: 0, y: 0, width: 0, height: 1 }, { x: 0, y: 0, width: 1, height: 1, guessed: true }, [0, 0, 1, 1]]) {
    assert.throws(() => parsePresenterLayoutV1({ ...layoutSelection(), presenterCrop }));
  }
  assert.doesNotThrow(() => parsePresenterLayoutV1({ ...layoutSelection(), presenterCrop: { x: 0, y: 0, width: 0.05, height: 1 } }));
});

test("asset offsets are canonical reduced safe-integer rationals including zero as 0/1", () => {
  for (const assetStart of [{ numerator: 0, denominator: 1 }, { numerator: 1, denominator: 3 },
    { numerator: Number.MAX_SAFE_INTEGER, denominator: 1 }]) {
    assert.deepEqual(parsePresenterLayoutV1({ ...layoutSelection(), assetStart }).assetStart, assetStart);
  }
  for (const assetStart of [{ numerator: 0, denominator: 2 }, { numerator: 2, denominator: 4 },
    { numerator: -0, denominator: 1 }, { numerator: -1, denominator: 1 }, { numerator: 1, denominator: 0 },
    { numerator: true, denominator: 1 }, { numerator: 0.1, denominator: 1 }, { numerator: 1, denominator: Infinity },
    { numerator: 9007199254740992, denominator: 1 }, { numerator: 1, denominator: 1, seconds: 1 }]) {
    assert.throws(() => parsePresenterLayoutV1({ ...layoutSelection(), assetStart }));
  }
});

test("positive ramp frames are bounded declarations, not a substituted frame clock", () => {
  for (const enterFrames of [0, -1, true, "12", 1.5, NaN, PRESENTER_LAYOUT_MAX_FRAMES + 1]) {
    assert.throws(() => parsePresenterLayoutV1({ ...layoutSelection(), enterFrames }));
    assert.throws(() => parsePresenterLayoutV1({ ...layoutSelection(), exitFrames: enterFrames }));
  }
  assert.equal(parsePresenterLayoutV1({ ...layoutSelection(), enterFrames: PRESENTER_LAYOUT_MAX_FRAMES }).enterFrames, PRESENTER_LAYOUT_MAX_FRAMES);
});

test("mask class, radius and actual crop-to-destination aspect cannot be substituted", () => {
  for (const kind of ["inset", "bubble", "split"] as const) {
    assert.throws(() => parsePresenterLayoutV1({ ...layoutSelection(kind), mask: { kind: "circle", radiusPx: 3 } }));
  }
  for (const radiusPx of [0, -1, true, NaN, 8193]) {
    assert.throws(() => parsePresenterLayoutV1({ ...layoutSelection(), mask: { kind: "rounded-rect", radiusPx } }));
  }
  assert.throws(() => assertPresenterLayoutGeometry({ ...layoutSelection(), mask: { kind: "rounded-rect", radiusPx: 200 } }, LANDSCAPE), /radius/);
  const value = layoutSelection(); value.presenterRect.height = 0.2;
  assert.throws(() => assertPresenterLayoutGeometry(value, LANDSCAPE), /stretch/);
  const circle = layoutSelection("bubble"); circle.presenterCrop = { x: 0, y: 0, width: 1, height: 1 };
  circle.presenterRect.width = 0.2; circle.presenterRect.height = 0.2;
  assert.throws(() => assertPresenterLayoutGeometry(circle, LANDSCAPE), /square/);
});

test("manual protected envelope must fit every actual rounded or circular mask corner", () => {
  const bubble = layoutSelection("bubble"); bubble.protectedPresenterRect = { ...bubble.presenterCrop };
  assert.throws(() => assertPresenterLayoutGeometry(bubble, LANDSCAPE), /target mask/);
  const inset = layoutSelection(); inset.protectedPresenterRect = { ...inset.presenterCrop };
  assert.throws(() => assertPresenterLayoutGeometry(inset, LANDSCAPE), /target mask/);
  const split = layoutSelection("split"); split.protectedPresenterRect.width = 0.5;
  assert.throws(() => assertPresenterLayoutGeometry(split, LANDSCAPE), /leaves the crop/);
});

test("split must exactly tile and inset presentation must retain an explicit full canvas", () => {
  for (const patch of [{ x: 0.400000001, width: 0.599999999 }, { x: 0.39, width: 0.61 }, { height: 0.9 }]) {
    const value = layoutSelection("split"); Object.assign(value.presentationRect, patch);
    assert.throws(() => assertPresenterLayoutGeometry(value, LANDSCAPE), /tile/);
  }
  const inset = layoutSelection(); inset.presentationRect.width = 0.9;
  assert.throws(() => assertPresenterLayoutGeometry(inset, LANDSCAPE), /full-canvas/);
  inset.presentationRect.width = 1; inset.presenterRect = { x: 0, y: 0, width: 1, height: 1 };
  assert.throws(() => assertPresenterLayoutGeometry(inset, LANDSCAPE), /smaller/);
});

test("target geometry rejects malformed canvas and subpixel surfaces", () => {
  for (const patch of [{ width: true }, { height: "1080" }, { width: Infinity }, { height: 1 }, { width: 16385 }] as Row[]) {
    assert.throws(() => assertPresenterLayoutGeometry(layoutSelection(), { ...LANDSCAPE, ...patch }));
  }
  const value = layoutSelection(); value.presenterRect = { x: 0, y: 0, width: 0.0001, height: 0.0001 };
  assert.throws(() => assertPresenterLayoutGeometry(value, LANDSCAPE), /two pixels/);
});
