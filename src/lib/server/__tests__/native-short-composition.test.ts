/** Failure boundaries for native geometry; these do not establish visual quality. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { buildNativeCanvas, nativeVisualExit, type NativeCanvasInput, type NativeTypeStyle } from "../native-short-composition";
import { missingStudioHostIds } from "../native-studio-host-ids";

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

test("serialized media timing ends on the authored frame instead of drifting past the composition", () => {
  const input = fixture(); input.totalFrames = 828;
  input.cuts = [{ start: 10, end: 36.44, speed: 1 }, { start: 60, end: 66.68, speed: 1 }];
  input.segments = [{ startFrame: 0, endFrameExclusive: 661 }, { startFrame: 661, endFrameExclusive: 828 }];
  input.pictureViews[0].endFrame = 828; input.captionViews[0].endFrame = 828;
  input.occurrences.push([2, 1, 0, 661, 828, "End.", 0]); input.captionGroups.push([2]);
  const original = structuredClone(input), html = buildNativeCanvas(input);
  assert.ok(26.44 + 6.68 > 33.12, "This reproduces the decimal-addition boundary failure");
  for (const id of ["dialogue-1", "source-1-0"]) {
    const element = new RegExp(`<[^>]+id="${id}"[^>]+>`, "u").exec(html)?.[0] ?? "";
    const start = Number(/data-start="([^"]+)"/u.exec(element)?.[1]);
    const duration = Number(/data-duration="([^"]+)"/u.exec(element)?.[1]);
    assert.equal(start, 26.44); assert.equal(start + duration, 33.12);
    assert.equal(Math.round(duration * 25), 167);
  }
  assert.deepEqual(input, original, "Authoring must preserve source cuts and word-frame evidence");
  assert.ok(html.includes(nativeVisualExit("source-crop-1-0", 828, "25/1")));
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

test("a nested final word preserves the full phrase lifetime and original highlight windows", () => {
  const input = fixture();
  input.occurrences = [[0, 0, 0, 0, 30, "Outer", 0], [1, 0, 1, 10, 20, "nested.", 0]];
  input.captionGroups = [[0, 1]];
  const originalWords = structuredClone(input.occurrences), html = buildNativeCanvas(input);
  assert.match(/<div[^>]+id="caption-0-0"[^>]+>/u.exec(html)?.[0] ?? "", /data-duration="1\.2"/u);
  assert.ok(html.includes(nativeVisualExit("caption-0-0", 30, "25/1")));
  assert.match(html, /id="word-0-0"[^>]+data-word-start-frame="0" data-word-end-frame="30"/u);
  assert.match(html, /id="word-1-0"[^>]+data-word-start-frame="10" data-word-end-frame="20"/u);
  assert.deepEqual(input.occurrences, originalWords);
  input.occurrences.push([2, 0, 2, 25, 40, "Next.", 0]); input.captionGroups.push([2]);
  const clamped = buildNativeCanvas(input);
  assert.match(/<div[^>]+id="caption-0-0"[^>]+>/u.exec(clamped)?.[0] ?? "", /data-duration="1"/u);
  assert.ok(clamped.includes(nativeVisualExit("caption-0-0", 25, "25/1")));
  assert.deepEqual(input.occurrences.slice(0, 2), originalWords, "Phrase clamping must not retime its words");
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

/** Opening title holds frames 0-24: captions resume at 25 in the only caption view. */
function suppressedOpening(input = fixture()): NativeCanvasInput {
  input.captionSuppressions = [{ startFrame: 0, endFrame: 25, reason: "TEST opening title card holds these frames" }];
  input.captionViews[0].startFrame = 25; input.captionViews[0].activeColor = "#ffe44d";
  return input;
}

/** Exact caption element windows on the output frame clock, read back from generated HTML. */
function captionWindows(html: string) {
  return [...html.matchAll(/<div id="(caption-[^"]+)"[^>]* data-start="([^"]+)" data-duration="([^"]+)"/gu)]
    .map(([, id, start, duration]) => ({ id, startFrame: Math.round(Number(start) * 25),
      endFrame: Math.round((Number(start) + Number(duration)) * 25) }));
}

const media = (html: string) => html.match(/<(?:audio|video)\b[^>]*>/gu);

test("a reasoned suppression removes captions for exact frames and keeps words, groups and the clock", () => {
  const plain = fixture(); plain.captionViews[0].activeColor = "#ffe44d";
  const input = suppressedOpening(), original = structuredClone(input);
  const before = buildNativeCanvas(plain), html = buildNativeCanvas(input);
  assert.deepEqual(input, original, "Suppression must not rewrite words, groups, cuts or views");
  assert.deepEqual(captionWindows(html), [{ id: "caption-1-0", startFrame: 25, endFrame: 40 }]);
  assert.match(html, /id="word-1-0"[^>]+data-word-start-frame="20" data-word-end-frame="40"/u,
    "A word spanning the resume frame keeps its source window");
  assert.ok(html.includes('tl.fromTo("#word-1-0",{color:"#ffffff"},{color:"#ffe44d",duration:0,immediateRender:false},1);'),
    "The spanning word highlights from the resume frame");
  assert.doesNotMatch(html, /#word-0-0/u);
  assert.ok(html.includes(nativeVisualExit("caption-1-0", 40, "25/1")));
  assert.deepEqual(media(html), media(before), "Dialogue and source picture timing are unchanged");
  assert.match(html, /data-composition-id="native-canvas"[^>]+data-duration="2"/u);
  assert.ok(html.includes("<!--native-caption-mount-->") && !before.includes("<!--native-caption-mount-->"));
  assert.deepEqual(missingStudioHostIds(html), [], "Every emitted element keeps a Studio selection id");
  plain.captionSuppressions = [];
  assert.equal(buildNativeCanvas(plain), before, "An empty suppression list keeps historical HTML");
});

test("a mid-phrase suppression splits only the display and keeps both highlight windows exact", () => {
  const input = fixture();
  input.captionGroups = [[0, 1]]; input.captionSuppressions = [{ startFrame: 10, endFrame: 30, reason: "TEST full-frame chart" }];
  input.captionViews = [{ ...input.captionViews[0], endFrame: 10, activeColor: "#ffe44d" },
    { ...input.captionViews[0], startFrame: 30, activeColor: "#ffe44d" }];
  const html = buildNativeCanvas(input);
  assert.deepEqual(captionWindows(html), [{ id: "caption-0-0", startFrame: 0, endFrame: 10 },
    { id: "caption-0-1", startFrame: 30, endFrame: 40 }]);
  for (const [id, end] of [["caption-0-0", 10], ["caption-0-1", 40]] as const) {
    assert.ok(html.includes(nativeVisualExit(id, end, "25/1")), `${id} exits on its exact frame forward and backward`);
  }
  assert.ok(html.includes('tl.set("#word-0-0",{color:"#ffffff"},0.4);'));
  assert.ok(html.includes('tl.fromTo("#word-1-1",{color:"#ffffff"},{color:"#ffe44d",duration:0,immediateRender:false},1.2);'));
  assert.doesNotMatch(html, /#word-1-0"|#word-0-1"/u, "No highlight is scheduled inside the suppressed window");
});

test("invalid, overlapping, out-of-range, unreasoned and ineffective suppressions fail closed", () => {
  const row = (startFrame: number, endFrame: number, reason = "TEST title holds") => ({ startFrame, endFrame, reason });
  const changes: Array<[(input: NativeCanvasInput) => void, RegExp]> = [
    [i => { i.captionSuppressions = [row(0, 25), row(20, 30)]; }, /overlap or are out of order/],
    [i => { i.captionSuppressions = [row(25, 30), row(0, 25)]; }, /overlap or are out of order/],
    [i => { i.captionSuppressions = [row(0, 51)]; }, /exact in-range/],
    [i => { i.captionSuppressions = [row(-1, 25)]; }, /exact in-range/],
    [i => { i.captionSuppressions = [row(0, 24.5)]; }, /exact in-range/],
    [i => { i.captionSuppressions = [row(25, 25)]; }, /exact in-range/],
    ...["", "  ", "bad\nreason", "x".repeat(501), "\u200b\u200b", "\u200d\ufeff", "TEST\u0085reason", "TEST\u009breason",
      "TEST \u202eholds", "\u2066TEST\u2069"].map((reason): [(input: NativeCanvasInput) => void, RegExp] =>
      [i => { i.captionSuppressions = [row(0, 25, reason)]; }, /bounded, readable editorial reason/]),
    [i => { i.captionSuppressions = [{ ...row(0, 25), kind: "title" } as never]; }, /caption suppression/],
    [i => { i.captionSuppressions = [{ startFrame: 0, endFrame: 25 } as never]; }, /caption suppression/],
    [i => { i.captionSuppressions = ["0-25" as never]; }, /caption suppression must be an object/],
    [i => { i.captionSuppressions = {} as never; }, /unbounded or malformed/],
    [i => { i.captionSuppressions = Array.from({ length: 129 }, (_, n) => row(n, n + 1)); }, /unbounded or malformed/],
    [i => { i.captionViews[0].startFrame = 20; }, /must partition/],
    [i => { i.captionViews[0].startFrame = 30; }, /omit part of the Short; caption-free frames need a reasoned/],
    [i => { i.captionSuppressions = [row(30, 35)]; i.captionViews[0].startFrame = 0; }, /must partition/],
    [i => { i.captionSuppressions = [row(40, 50)]; i.captionViews[0] = { ...i.captionViews[0], startFrame: 0, endFrame: 40 }; },
      /hides no caption phrase/],
    [i => { i.captionSuppressions = [row(0, 50)]; i.captionViews = []; }, /cannot hide every caption/],
    [i => { i.captionMode = "source-burned"; i.captionViews = []; }, /Source-burned captions cannot suppress/],
  ];
  for (const [change, pattern] of changes) {
    const input = suppressedOpening(); change(input);
    assert.throws(() => buildNativeCanvas(input), pattern, String(pattern));
  }
  const burned = fixture(); burned.captionMode = "source-burned"; burned.captionViews = []; burned.captionSuppressions = [];
  assert.doesNotThrow(() => buildNativeCanvas(burned), "An empty list is not a suppression");
});

/** Alpha[0,10) Beta[10,30) Gamma[25,40): Beta's tail runs past the resume frame into Gamma's phrase. */
function tailPastResume(): NativeCanvasInput {
  const input = suppressedOpening();
  input.occurrences = [[0, 0, 0, 0, 10, "Alpha", 0], [1, 0, 1, 10, 30, "Beta", 0], [2, 0, 2, 25, 40, "Gamma.", 0]];
  input.captionGroups = [[0, 1], [2]];
  return input;
}

test("a suppressed build schedules word highlights only for rendered spans", () => {
  const html = buildNativeCanvas(tailPastResume());
  assert.deepEqual(captionWindows(html), [{ id: "caption-1-0", startFrame: 25, endFrame: 40 }]);
  const targets = [...html.matchAll(/tl\.(?:fromTo|set)\("#(word-[^"]+)"/gu)].map(([, id]) => id);
  assert.deepEqual([...new Set(targets)], ["word-2-0"], "Beta's hidden phrase has no span, so no tween targets it");
  assert.ok(targets.every(id => html.includes(`<span id="${id}"`)), "Every tween target exists");
  const historical = tailPastResume();
  delete historical.captionSuppressions;
  historical.captionViews = [{ ...historical.captionViews[0], startFrame: 0, endFrame: 25 }, { ...historical.captionViews[0] }];
  assert.match(buildNativeCanvas(historical), /tl\.fromTo\("#word-1-1"/u,
    "Unsuppressed multi-view HTML keeps its historical tween list byte for byte (cold reads compare it)");
});

test("a word spoken wholly outside every window cannot lose its whole phrase; readable reasons apply to corrections", () => {
  const input = suppressedOpening();
  input.occurrences = [[0, 0, 0, 0, 10, "Alpha", 0], [1, 0, 1, 20, 30, "Beta", 0], [2, 0, 2, 20, 40, "Gamma.", 0]];
  input.captionGroups = [[0, 1], [2]];
  input.captionSuppressions![0].endFrame = 20; input.captionViews[0].startFrame = 20;
  assert.throws(() => buildNativeCanvas(input), /hides word 1's whole phrase although the word is spoken wholly outside every window/);
  assert.doesNotThrow(() => buildNativeCanvas(tailPastResume()), "A tail partly inside the window is reported, not refused");
  const corrected = fixture();
  corrected.captionCorrections = [{ occurrenceId: 0, expectedSourceText: "Actual", displayText: "Confirmed", reason: "\u200b" }];
  assert.throws(() => buildNativeCanvas(corrected), /bounded review reason/);
  corrected.captionCorrections[0].reason = "TEST \u202econfirmed";
  assert.throws(() => buildNativeCanvas(corrected), /bounded review reason/);
});
