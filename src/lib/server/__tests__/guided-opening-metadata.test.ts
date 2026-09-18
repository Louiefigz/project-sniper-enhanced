import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { test } from "node:test";
import { assertOpeningMediaMetadata, assertFullProgramMediaMetadata } from "../guided-opening-media-input";
import type { GuidedFrameBindingsV1 } from "../guided-proposal-bindings";

/** Pure untrusted metadata fixture, not a ready proposal, source admission or render proof. */
function metadata() {
  const entry = { id: "g1", kind: "statement-card", anchor: "own-screen", outStart: 0, outEnd: 1, spec: {} };
  const presentation = { schemaVersion: 1, anchor: "own-screen", placement: "full-canvas", compositeMode: "normal",
    baseTreatment: "preserve", rationale: "TEST ONLY full canvas card" } as const;
  const bindings: GuidedFrameBindingsV1 = { schemaVersion: 1, kind: "guided-frame-presentation-bindings",
    scope: "controller-frames-and-declared-presentation-not-rendered-proof", frameRate: "30/1", totalFrames: 300,
    targetHash: "a".repeat(64), candidatePlanHash: "b".repeat(64), occurrenceEvidenceHash: "c".repeat(64),
    graphics: [{ graphicId: "g1", operationIndex: 0, order: 0, startFrame: 0, endFrameExclusive: 30,
      presentation, entryHash: "d".repeat(64) }], unboundInheritedGraphicIds: [] };
  return { plan: { target: { mode: "longform", width: 1920, height: 1080 },
    cutTrack: [{ sourceId: "s", start: 0, end: 10 }], graphicsTrack: [entry] } as Record<string, unknown>,
  bindings, reviewEndFrame: 120 };
}

function passes(value: ReturnType<typeof metadata>): boolean {
  try { assertOpeningMediaMetadata(value); return true; } catch { return false; }
}

test("known profile lanes reject before materialization and do not alter authored intent", () => {
  for (const key of ["captionsTrack", "titleCards", "brollTrack", "baselineLook", "punchIns", "transitions", "audioEnhance", "audioGain"]) {
    const value = metadata(); value.plan[key] = [{ testOnly: true }];
    const before = structuredClone(value);
    assert.throws(() => assertOpeningMediaMetadata(value), /requested lanes/, key);
    assert.deepEqual(value, before);
  }
  for (const cut of [{ speed: 1.1 }, { speed: true }, { speed: null }, { audioLeadMs: 80 }]) {
    const value = metadata(); value.plan.cutTrack = [{ sourceId: "s", start: 0, end: 10, ...cut }];
    assert.throws(() => assertOpeningMediaMetadata(value), /speed\/J-cut/);
  }
});

test("selected free-band, inherited, presenter-hole and additional effects are unavailable", () => {
  const inherited = metadata(); inherited.bindings.unboundInheritedGraphicIds = ["old"];
  assert.throws(() => assertOpeningMediaMetadata(inherited), /inherited/);
  assert.throws(() => assertOpeningMediaMetadata({ ...metadata(), bindings: null }), /bindings/);
  const free = metadata(); free.bindings.graphics[0].presentation = { ...free.bindings.graphics[0].presentation,
    anchor: "free-band", placement: "measured-free-region" };
  assert.throws(() => assertOpeningMediaMetadata(free), /presentation/);
  for (const entry of [{ takeoverBase: "blur" }, { exitOnCut: true }, { placement: { x: 20 } }, { kind: "nateherk-takeover" },
    { kind: "nateherk-scoreboard", spec: { presenterFrame: true } }, { kind: "nateherk-pipeline", spec: { presenterFrame: "yes" } },
    { kind: "nateherk-ledger-dark", spec: { presenterFrame: true } }]) {
    const value = metadata(); Object.assign((value.plan.graphicsTrack as object[])[0], entry);
    assert.throws(() => assertOpeningMediaMetadata(value), /presentation/);
  }
});

test("body-only presentation belongs to the body renderer, not the private opening exclusion", () => {
  const value = metadata(); value.bindings.graphics[0].startFrame = 150;
  value.bindings.graphics[0].endFrameExclusive = 180;
  value.bindings.graphics[0].presentation = { ...value.bindings.graphics[0].presentation,
    anchor: "free-band", placement: "measured-free-region" };
  Object.assign((value.plan.graphicsTrack as object[])[0], { kind: "nateherk-takeover", anchor: "free-band" });
  assertOpeningMediaMetadata(value);
  assert.throws(() => assertFullProgramMediaMetadata(value), /presentation/);
  assert.throws(() => assertOpeningMediaMetadata({ ...value, reviewEndFrame: 151 }), /presentation/);
});

test("all-row metadata screening preserves later rows and refuses unsupported body lanes", () => {
  const value = metadata(), graphic = value.bindings.graphics[0], entry = (value.plan.graphicsTrack as object[])[0];
  value.bindings.graphics = Array.from({ length: 12 }, (_, index) => ({ ...graphic, order: index,
    graphicId: `TEST-${index}`, startFrame: 10 * index, endFrameExclusive: 10 * index + 30 }));
  value.plan.graphicsTrack = Array.from({ length: 12 }, (_, index) => ({ ...entry, id: `TEST-${index}` }));
  const before = structuredClone(value);
  assertFullProgramMediaMetadata(value);
  assert.deepEqual(value, before);
  assert.throws(() => assertOpeningMediaMetadata(value), /eight-graphic/);
  for (const patch of [{ kind: "nateherk-takeover" }, { exitOnCut: true },
    { kind: "nateherk-scoreboard", spec: { presenterFrame: true } }]) {
    const later = structuredClone(value);
    Object.assign((later.plan.graphicsTrack as object[])[11], patch);
    assert.throws(() => assertFullProgramMediaMetadata(later), /presentation/);
  }
  assert.throws(() => assertFullProgramMediaMetadata({ ...value, plan: { ...value.plan, captionsTrack: [{}] } }), /requested lanes/);
  assert.throws(() => assertFullProgramMediaMetadata({ ...value, bindings: null }), /bindings/);
});

test("eight selected graphics are the initial bound without deleting later exact bindings", () => {
  const value = metadata(), graphic = value.bindings.graphics[0], entry = (value.plan.graphicsTrack as object[])[0];
  value.bindings.graphics = Array.from({ length: 9 }, (_, index) => ({ ...graphic, graphicId: `TEST-${index}`,
    order: index, startFrame: 10 * index }));
  value.plan.graphicsTrack = Array.from({ length: 9 }, (_, index) => ({ ...entry, id: `TEST-${index}` }));
  assert.throws(() => assertOpeningMediaMetadata(value), /eight-graphic/);
  value.bindings.graphics[8].startFrame = value.reviewEndFrame;
  assertOpeningMediaMetadata(value);
  value.plan.graphicsTrack = [];
  assert.throws(() => assertOpeningMediaMetadata(value), /whole-candidate/);
});

test("duplicate order or identity cannot hide an unqualified later body template", () => {
  for (const field of ["order", "graphicId"] as const) {
    const value = metadata(), first = value.bindings.graphics[0];
    value.bindings.graphics.push({ ...first, graphicId: "g2", order: 1, startFrame: 150,
      endFrameExclusive: 180, [field]: first[field] });
    (value.plan.graphicsTrack as object[]).push({ id: "g2", kind: "nateherk-takeover", anchor: "own-screen" });
    assert.throws(() => assertFullProgramMediaMetadata(value), /ordered unique/);
  }
});

test("TS metadata lane/default screening agrees with the actual Python profile without media", () => {
  const patches: Array<Record<string, unknown>> = [{}, { captionsTrack: [] }, { baselineLook: {} }, { audioEnhance: false },
    { music: { enabled: true } }, { captions: { burn: true } }, { captions: { burn: false } },
    { reframe: {} }, { reframe: { strategy: "none" } }, { reframe: { strategy: "none", x: 0 } },
    { reframe: { strategy: "face" } }, { transitions: [{ outTime: 1 }] }, { punchIns: [{}] },
    { target: { mode: "short", width: 1080, height: 1920 } },
    { target: { mode: "short", width: 1080, height: 1920 }, reframe: { strategy: "none" }, captions: { burn: false } },
    { cutTrack: [{ sourceId: "s", start: 0, end: 10, speed: 1.2 }] },
    { cutTrack: [{ sourceId: "s", start: 0, end: 10, audioLeadMs: 80 }] }];
  const values = patches.map((patch) => { const value = metadata(); Object.assign(value.plan, patch); return value; });
  const code = "import json,sys\nfrom guided_opening_frames import _profile\nresult=[]\nfor plan in json.load(sys.stdin):\n try:\n  _profile(plan)\n  result.append(True)\n except (RuntimeError,ValueError,KeyError,TypeError):\n  result.append(False)\nprint(json.dumps(result))";
  const observed = JSON.parse(execFileSync(path.resolve(".venv/bin/python"), ["-c", code], {
    input: JSON.stringify(values.map((value) => value.plan)), encoding: "utf8", timeout: 10_000, maxBuffer: 64 * 1024,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: path.resolve("scripts/producer") },
  }));
  assert.deepEqual(values.map(passes), observed);
  assert.equal(observed[4], true, "Existing v2 music support is not silently forbidden");
});

test("selected presentation and conditional presenter-hole screening agree with Python", () => {
  const patches: Array<Record<string, unknown>> = [{}, { exitOnCut: false }, { exitOnCut: true }, { placement: {} },
    { placement: { x: 0 } }, { takeoverBase: null }, { takeoverBase: false }, { kind: "nateherk-takeover" },
    { kind: "nateherk-scoreboard", spec: { presenterFrame: false } },
    { kind: "nateherk-scoreboard", spec: { presenterFrame: true } },
    { kind: "nateherk-pipeline", spec: { presenterFrame: true } },
    { kind: "nateherk-ledger-dark", spec: { presenterFrame: true } }];
  const values = patches.map((patch) => {
    const value = metadata(); Object.assign((value.plan.graphicsTrack as object[])[0], patch); return value;
  });
  const code = "import json,sys\nfrom guided_opening_frames import _presentation\nresult=[]\nfor value in json.load(sys.stdin):\n try:\n  _presentation(value['binding'],value['entry'])\n  result.append(True)\n except (RuntimeError,ValueError,KeyError,TypeError):\n  result.append(False)\nprint(json.dumps(result))";
  const observed = JSON.parse(execFileSync(path.resolve(".venv/bin/python"), ["-c", code], {
    input: JSON.stringify(values.map((value) => ({ binding: value.bindings.graphics[0], entry: (value.plan.graphicsTrack as object[])[0] }))),
    encoding: "utf8", timeout: 10_000, maxBuffer: 64 * 1024,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: path.resolve("scripts/producer") },
  }));
  assert.deepEqual(values.map(passes), observed);
});

test("current shared-master finishing agrees with Python for long, short and captioned metadata", () => {
  const cases: Array<[Record<string, unknown>, boolean]> = [
    [{ audioEnhance: { preset: "voice" } }, true], [{ audioEnhance: { preset: "voice-rnn" } }, true],
    [{ audioEnhance: { preset: "voice-strong", rationale: "TEST cleanup" } }, true],
    [{ audioEnhance: null, audioGain: null }, true], [{ audioGain: [] }, true],
    [{ audioGain: [{ outStart: 0.5, outEnd: 1, dB: -12 }, { outStart: 1, outEnd: 2, dB: 12 }] }, true],
    [{ audioEnhance: { preset: "voice" }, audioGain: [{ outStart: 1, outEnd: 2, dB: 6, rationale: "TEST lift" }] }, true],
    [{ audioEnhance: false }, false], [{ audioEnhance: {} }, false], [{ audioEnhance: "voice" }, false],
    [{ audioEnhance: { preset: "separate" } }, false], [{ audioEnhance: { preset: "unknown" } }, false],
    [{ audioEnhance: { preset: "voice", extra: true } }, false], [{ audioGain: false }, false],
    [{ audioGain: 2 }, false], [{ audioGain: {} }, false], [{ audioGain: [{}] }, false],
    [{ audioGain: [{ outStart: 1, outEnd: 1, dB: 0 }] }, false],
    [{ audioGain: [{ outStart: 0, outEnd: 1, dB: 13 }] }, false],
    [{ audioGain: [{ outStart: 0, outEnd: 2, dB: 1 }, { outStart: 1, outEnd: 3, dB: 2 }] }, false],
  ];
  for (const field of ["outStart", "outEnd", "dB"]) {
    for (const value of [true, false, null, "2", "NaN"]) {
      cases.push([{ audioGain: [{ outStart: 0, outEnd: 1, dB: 2, [field]: value }] }, false]);
    }
  }
  const values = [false, true].flatMap(short => [false, true].flatMap(captioned => cases.map(([patch, expected]) => {
    const value = metadata();
    value.plan = { ...value.plan, ...patch, target: { mode: short ? "short" : "longform",
      width: short ? 1080 : 1920, height: short ? 1920 : 1080 }, captions: { burn: captioned },
      ...(short ? { reframe: { layout: "fill", crop: [0, 0, 1, 1], track: false } } : {}),
      ...(captioned ? { captionsTrack: { schemaVersion: 1, source: "kept-transcript", defaultPolicy: "line", groups: [] } } : {}) };
    return { value, expected };
  })));
  const code = "import json,sys\nfrom guided_opening_frames import _profile\nfrom guided_media_profile import profile_for_plan\nout=[]\nfor p in json.load(sys.stdin):\n try:\n  _profile(p,profile_for_plan(p));out.append(True)\n except (RuntimeError,ValueError,KeyError,TypeError):out.append(False)\nprint(json.dumps(out))";
  const actual = JSON.parse(execFileSync(path.resolve(".venv/bin/python"), ["-B", "-c", code], {
    input: JSON.stringify(values.map(row => row.value.plan)), encoding: "utf8", timeout: 10_000,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: path.resolve("scripts/producer") } }));
  assert.deepEqual(actual, values.map(row => row.expected));
  for (const [index, row] of values.entries()) {
    const before = structuredClone(row.value);
    assert.equal(passes(row.value), actual[index], `case ${index}`);
    if (row.expected) assertFullProgramMediaMetadata(row.value);
    else assert.throws(() => assertFullProgramMediaMetadata(row.value));
    assert.deepEqual(row.value, before);
  }
});

test("finishing preflight never coerces gain fields or admits nonfinite numbers", () => {
  for (const invalid of [true, false, null, "2", NaN, Infinity, -Infinity]) {
    for (const field of ["outStart", "outEnd", "dB"]) {
      const value = metadata();
      value.plan.audioGain = [{ outStart: 0, outEnd: 1, dB: 2, [field]: invalid }];
      assert.throws(() => assertOpeningMediaMetadata(value), /finite numeric/);
    }
  }
});
