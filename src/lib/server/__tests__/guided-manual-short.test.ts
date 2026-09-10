import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { test } from "node:test";
import { MANUAL_SHORT_PROFILE, assertManualShortPlan, openingMediaProfileForPlan } from "@/lib/producer/contracts/guided-media-profile";
import { OPENING_DOCUMENT_NAMES, parseGuidedOpeningMediaInput, parseCurrentOpeningMediaInput } from "@/lib/producer/contracts/guided-opening-media-v1";
import { assertOpeningMediaMetadata, assertFullProgramMediaMetadata } from "../guided-opening-media-input";
import { canonicalJsonSha256 as hash } from "../auto-edit-hash";
import type { GuidedFrameBindingsV1 } from "../guided-proposal-bindings";

function plan(): Record<string, unknown> {
  return { target: { mode: "short", width: 1080, height: 1920, fps: 30 },
    cutTrack: [{ sourceId: "TEST", start: 0, end: 2 }], graphicsTrack: [],
    reframe: { layout: "fill", crop: [0.25, 0, 0.5, 1], track: false }, captions: { burn: false } };
}

function metadata(candidate: Record<string, unknown>) {
  const bindings: GuidedFrameBindingsV1 = { schemaVersion: 1, kind: "guided-frame-presentation-bindings",
    scope: "controller-frames-and-declared-presentation-not-rendered-proof", frameRate: "30000/1001", totalFrames: 60,
    targetHash: hash(candidate.target), candidatePlanHash: hash(candidate), occurrenceEvidenceHash: "a".repeat(64),
    graphics: [], unboundInheritedGraphicIds: [] };
  return { plan: candidate, bindings, reviewEndFrame: 60 };
}

function admitted(candidate: Record<string, unknown>) {
  try { assertOpeningMediaMetadata(metadata(candidate)); assertFullProgramMediaMetadata(metadata(candidate)); return true; }
  catch { return false; }
}

test("manual short selects a new explicit geometry class without mutating the submitted plan", () => {
  const value = plan(), before = structuredClone(value);
  assert.equal(openingMediaProfileForPlan(value), MANUAL_SHORT_PROFILE);
  assert.equal(admitted(value), true);
  assert.deepEqual(value, before);
  assert.equal(openingMediaProfileForPlan({ ...value, reframe: { strategy: "none" } }), "unity-source-float-own-screen-v1");
});

test("TS and actual Python profile agree on manual crop and every unchanged finishing exclusion", () => {
  const changes: Array<Record<string, unknown>> = [{}, { captions: {} }, { captions: { burn: 0 } }, { captions: { burn: true } },
    { target: { mode: "longform", width: 1080, height: 1920 } }, { target: { mode: "short", width: 720, height: 1280 } },
    { captionsTrack: [{}] }, { punchIns: [{}] }, { transitions: [{}] }, { baselineLook: { grade: "warm" } },
    { audioEnhance: { preset: "separate" } }, { audioGain: [{}] }, { overlays: true }, { presenter: { animatedPip: true } },
    { cutTrack: [{ sourceId: "TEST", start: 0, end: 1, speed: 1.1 }] },
    { cutTrack: [{ sourceId: "TEST", start: 0, end: 1, audioLeadMs: 50 }] },
    { cutTrack: [{ sourceId: "TEST", start: 0, end: 1 }, { sourceId: "other", start: 1, end: 2 }] }];
  const crops = [[true, 0, 0.5, 1], [0.8, 0, 0.5, 1], [0, 0, 0.049, 1], [0, 0, 1], [0, 0, null, 1]];
  changes.push(...crops.map((crop) => ({ reframe: { layout: "fill", crop, track: false } })));
  const values = changes.map((change) => ({ ...plan(), ...change }));
  const code = "import json,sys\nfrom guided_opening_frames import _profile\nfrom guided_media_profile import profile_for_plan\nresult=[]\nfor plan in json.load(sys.stdin):\n try:\n  _profile(plan,profile_for_plan(plan))\n  result.append(True)\n except (RuntimeError,ValueError,TypeError,KeyError):\n  result.append(False)\nprint(json.dumps(result))";
  const observed = JSON.parse(execFileSync(path.resolve(".venv/bin/python"), ["-c", code], {
    input: JSON.stringify(values), encoding: "utf8", timeout: 10_000, maxBuffer: 64 * 1024,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: path.resolve("scripts/producer") },
  }));
  assert.deepEqual(values.map(admitted), observed);
  assert.equal(observed[0], true);
  assert.equal(observed.slice(1).some(Boolean), false);
});

test("no unknown tracker/layout/default caption allowance or nonfinite geometry", () => {
  for (const reframe of [{ layout: "split", crop: [0, 0, 1, 1], track: false },
    { layout: "fill", crop: [0, 0, 1, 1], track: true }, { layout: "fill", crop: [0, 0, 1, 1], track: false, strategy: "face" },
    { layout: "fill", crop: [NaN, 0, 1, 1], track: false }, { layout: "fill", crop: [0, 0, Infinity, 1], track: false }]) {
    assert.throws(() => assertManualShortPlan({ ...plan(), reframe }));
  }
});

test("historical invocation parser refuses new class while current dispatcher retains exact new bytes", () => {
  const core = { schemaVersion: 1, kind: "guided-opening-media-input", profile: MANUAL_SHORT_PROFILE,
    executionId: "12345678-1234-4234-8234-123456789abc",
    documents: Object.fromEntries(OPENING_DOCUMENT_NAMES.map((name) => [name, { path: `/private/tmp/TEST/${name}.json`, sha256: "a".repeat(64) }])),
    pipeline: { snapshotRoot: "/private/tmp/TEST/files", lockPath: "/private/tmp/TEST/pipeline-lock.json", lockSha256: "b".repeat(64), digest: "c".repeat(64) } };
  const value = { ...core, executionInputHash: hash(core) };
  assert.throws(() => parseGuidedOpeningMediaInput(value), /class/);
  assert.deepEqual(parseCurrentOpeningMediaInput(value), value);
  assert.throws(() => parseCurrentOpeningMediaInput({ ...value, profile: "automatic" }), /unsupported/);
  assert.throws(() => parseCurrentOpeningMediaInput({ ...value, tracked: true }), /unsupported/);
});
