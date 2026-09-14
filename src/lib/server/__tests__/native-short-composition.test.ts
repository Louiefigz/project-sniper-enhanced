/** Failure boundaries for native geometry; these do not establish visual quality. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { buildNativeCanvas, nativeVisualExit, type NativeCanvasInput, type NativeTypeStyle } from "../native-short-composition";

function fixture(): NativeCanvasInput {
  const style: NativeTypeStyle = { size: 64, weight: 700, color: "#ffffff", background: "#171923",
    align: "center", padding: 12, radius: 8, lineHeight: 1.16 };
  return { title: "TEST native visual", frameRate: "25/1", totalFrames: 50,
    sourceSize: { w: 1920, h: 1080 }, sourceFile: `assets/${"a".repeat(64)}.mp4`, background: "#171923",
    cuts: [{ start: 10, end: 12, speed: 1 }], segments: [{ startFrame: 0, endFrameExclusive: 50 }],
    occurrences: [[0, 0, 0, 0, 20, "Actual", 0], [1, 0, 1, 20, 40, "words.", 0]], captionGroups: [[0], [1]],
    pictureViews: [{ startFrame: 0, endFrame: 50, crop: [650, 0, 607.5, 1080], box: [0, 0, 1080, 1920] }],
    captionViews: [{ startFrame: 0, endFrame: 50, box: [100, 1500, 800, 160], style }],
    text: [{ id: "opening", startFrame: 0, endFrame: 30, role: "hook", text: "TEST <not markup>",
      box: [100, 100, 880, 180], style }], shapes: [], motion: [] };
}

test("portrait and split crops fill their panes while preserving source/audio and actual captions", () => {
  const full = fixture(), html = buildNativeCanvas(full);
  assert.match(html, /data-media-start="10"/); assert.match(html, /Actual/); assert.match(html, /words\./);
  assert.match(html, /TEST &lt;not markup&gt;/); assert.doesNotMatch(html, /object-fit:contain/);
  const split = fixture(); split.pictureViews[0] = { startFrame: 0, endFrame: 50,
    crop: [400, 80, 1125, 1000], box: [0, 960, 1080, 960] };
  assert.match(buildNativeCanvas(split), /top:960px;width:1080px;height:960px/);
  assert.equal((buildNativeCanvas(split).match(/<audio /gu) ?? []).length, 1);
});

test("invalid crops, source clocks, omitted captions and malformed style never silently fall back", () => {
  const changes: Array<[(input: NativeCanvasInput) => void, RegExp]> = [
    [(input) => { input.pictureViews[0].crop[2] = 900; }, /stretch or contain/],
    [(input) => { input.pictureViews[0].crop[0] = 1800; }, /escapes/],
    [(input) => { input.cuts[0].end = 13; }, /speed-1 interval/],
    [(input) => { input.captionGroups = [[0]]; }, /omitted kept words/],
    [(input) => { input.captionViews[0].endFrame = 40; }, /omit part/],
    [(input) => { input.text[0].style.color = "red;display:none"; }, /exact hex/],
    [(input) => { input.text[0].id = "caption-0"; }, /IDs collide/],
  ];
  for (const [change, pattern] of changes) {
    const input = fixture(); change(input); assert.throws(() => buildNativeCanvas(input), pattern);
  }
});

test("motion must remain inside its actual visible clip and use finite supported poses", () => {
  const input = fixture(); input.motion = [{ id: "opening", startFrame: 0, durationFrames: 6,
    from: { y: 24, scale: .82, opacity: 0 }, to: { y: 0, scale: 1, opacity: 1 }, ease: "power2.out" }];
  assert.match(buildNativeCanvas(input), /immediateRender:false/);
  input.motion[0].startFrame = 29;
  assert.throws(() => buildNativeCanvas(input), /visible target/);
  input.motion[0].startFrame = 0; input.motion[0].from.scale = Infinity;
  assert.throws(() => buildNativeCanvas(input), /finite bounds/);
});

test("outgoing source, title and caption layers receive explicit exact-frame visual exits", () => {
  const html = buildNativeCanvas(fixture());
  assert.ok(html.includes(nativeVisualExit("source-crop-0-0", 50, "25/1")));
  assert.ok(html.includes(nativeVisualExit("opening", 30, "25/1")));
  assert.ok(html.includes(nativeVisualExit("caption-0-0", 20, "25/1")));
  assert.throws(() => nativeVisualExit('bad"selector', 12, "25/1"), /Invalid/);
  assert.throws(() => nativeVisualExit("opening", 12, "25/0"), /Invalid/);
});

test("adjacent phrases never stack when rounded source-word frames overlap", () => {
  const input = fixture();
  input.occurrences[0][4] = 21;
  const originalWords = structuredClone(input.occurrences);
  const html = buildNativeCanvas(input);
  const first = /<div[^>]+id="caption-0-0"[^>]+>/u.exec(html)?.[0];
  assert.match(first ?? "", /data-duration="0\.8"/u);
  assert.ok(html.includes(nativeVisualExit("caption-0-0", 20, "25/1")));
  assert.deepEqual(input.occurrences, originalWords, "Source word evidence must remain unchanged");
});

test("display corrections target one occurrence and preserve source words and highlight timing", () => {
  const input = fixture(); input.occurrences.forEach(row => { row[5] = "levels"; });
  const original = structuredClone(input.occurrences);
  input.captionCorrections = [{ occurrenceId: 0, expectedSourceText: "levels",
    displayText: "level is", reason: "TEST operator confirmed the displayed wording" }];
  const html = buildNativeCanvas(input);
  assert.match(html, /id="word-0-0"[^>]+data-word-start-frame="0" data-word-end-frame="20"[^>]*>level is<\/span>/u);
  assert.match(html, /id="word-1-0"[^>]*>levels<\/span>/u);
  assert.deepEqual(input.occurrences, original);
  input.captionCorrections[0].displayText = "<actual & text>";
  assert.match(buildNativeCanvas(input), /&lt;actual &amp; text&gt;<\/span>/u);
});

test("stale and malformed display corrections fail before producing captions", () => {
  const correction = { occurrenceId: 0, expectedSourceText: "Actual", displayText: "Confirmed", reason: "TEST reviewed" };
  const invalid = [
    [correction, correction], [{ ...correction, occurrenceId: 2 }],
    [{ ...correction, expectedSourceText: "wrong" }], [{ ...correction, reason: "" }],
    ...["", "Actual", " hidden", "bad\nline", "bad\u202eline", "bad\0line", "x".repeat(257)].map(displayText => [{ ...correction, displayText }]),
  ];
  for (const rows of invalid) {
    const input = fixture(); input.captionCorrections = rows;
    assert.throws(() => buildNativeCanvas(input), /caption correction/);
  }
  const input = fixture(), html = buildNativeCanvas(input);
  input.captionCorrections = [];
  assert.equal(buildNativeCanvas(input), html);
});

test("source-burned import retains source and clock without drawing duplicate captions", () => {
  const input = fixture(), original = structuredClone(input), html = buildNativeCanvas(input);
  input.captionMode = "native";
  assert.equal(buildNativeCanvas(input), html);
  input.captionViews = [];
  assert.throws(() => buildNativeCanvas(input), /omit part/);
  input.captionMode = "source-burned";
  const imported = buildNativeCanvas(input);
  assert.match(imported, /<video[^>]+id="source-0-0"/u);
  assert.match(imported, /<audio[^>]+id="dialogue-0"/u);
  assert.match(imported, /data-media-start="10"/u);
  assert.doesNotMatch(imported, /id="(?:caption-|word-)/u);
  for (const key of ["occurrences", "captionGroups", "cuts", "segments", "pictureViews"] as const) {
    assert.deepEqual(input[key], original[key]);
  }
  input.captionViews = original.captionViews;
  assert.throws(() => buildNativeCanvas(input), /cannot add native caption views/);
  input.captionViews = [];
  input.captionCorrections = [{ occurrenceId: 0, expectedSourceText: "Actual", displayText: "Changed", reason: "TEST ignored correction" }];
  assert.throws(() => buildNativeCanvas(input), /cannot apply native caption corrections/);
  input.captionCorrections = [];
  assert.doesNotThrow(() => buildNativeCanvas(input));
  for (const views of [[], [{ ...original.pictureViews[0], startFrame: 1 }],
    [{ ...original.pictureViews[0], endFrame: 49 }],
    [{ ...original.pictureViews[0], endFrame: 24 }, { ...original.pictureViews[0], startFrame: 25 }]]) {
    input.pictureViews = views;
    assert.throws(() => buildNativeCanvas(input), /continuous source picture coverage/);
  }
  input.pictureViews = [{ ...original.pictureViews[0], startFrame: 24 }, { ...original.pictureViews[0], endFrame: 25 }];
  assert.doesNotThrow(() => buildNativeCanvas(input), "Overlapping source panes may jointly cover the clock");
  Object.assign(input, { captionMode: "hidden" });
  assert.throws(() => buildNativeCanvas(input), /caption mode is unsupported/);
});
