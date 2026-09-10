import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { test } from "node:test";
import { CAPTION_PROFILE, CAPTION_SHORT_PROFILE, SCREENED_CAPTION_PROFILE, SCREENED_CAPTION_SHORT_PROFILE,
  isCaptionProfile, isScreenedCaptionProfile, assertCaptionGraphWorkload } from "@/lib/producer/contracts/guided-caption-profile";
import { openingMediaProfileForPlan, bodyMediaProfile, isManualMediaProfile, openingMediaProfile } from "@/lib/producer/contracts/guided-media-profile";
import { assertOpeningMediaMetadata, assertFullProgramMediaMetadata } from "../guided-opening-media-input";
import { canonicalJsonSha256 as hash } from "../auto-edit-hash";
import type { GuidedFrameBindingsV1 } from "../guided-proposal-bindings";

function plan(short = false): Record<string, unknown> {
  return { target: { mode: short ? "short" : "longform", width: short ? 1080 : 1920, height: short ? 1920 : 1080 },
    ...(short ? { reframe: { layout: "fill", crop: [0, 0, 1, 1], track: false } } : {}),
    cutTrack: [{ sourceId: "TEST", start: 0, end: 2 }], graphicsTrack: [], captions: { burn: true },
    captionsTrack: { schemaVersion: 1, source: "kept-transcript", defaultPolicy: "line", groups: [] } };
}

function admitted(candidate: Record<string, unknown>): boolean {
  const bindings: GuidedFrameBindingsV1 = { schemaVersion: 1, kind: "guided-frame-presentation-bindings",
    scope: "controller-frames-and-declared-presentation-not-rendered-proof", frameRate: "30000/1001", totalFrames: 60,
    targetHash: hash(candidate.target), candidatePlanHash: hash(candidate), occurrenceEvidenceHash: "a".repeat(64),
    graphics: [], unboundInheritedGraphicIds: [] };
  try {
    assertOpeningMediaMetadata({ plan: candidate, bindings, reviewEndFrame: 30 });
    assertFullProgramMediaMetadata({ plan: candidate, bindings }); return true;
  } catch { return false; }
}

test("explicit caption presets select distinct native classes without changing the plan", () => {
  for (const [short, expected] of [[false, SCREENED_CAPTION_PROFILE], [true, SCREENED_CAPTION_SHORT_PROFILE]] as const) {
    const candidate = plan(short), before = structuredClone(candidate);
    assert.equal(openingMediaProfileForPlan(candidate), expected);
    assert.ok(bodyMediaProfile(expected).includes("caption-layout"));
    assert.ok(admitted(candidate)); assert.deepEqual(candidate, before);
  }
});

test("held historical caption classes keep exact tokens without granting new screening", () => {
  for (const [short, legacy, current] of [[false, CAPTION_PROFILE, SCREENED_CAPTION_PROFILE],
    [true, CAPTION_SHORT_PROFILE, SCREENED_CAPTION_SHORT_PROFILE]] as const) {
    const candidate = plan(short), before = structuredClone(candidate);
    assert.equal(openingMediaProfileForPlan(candidate, legacy), legacy);
    assert.equal(openingMediaProfileForPlan(candidate, current), current);
    assert.ok(isCaptionProfile(legacy)); assert.ok(isCaptionProfile(current));
    assert.equal(isScreenedCaptionProfile(legacy), false); assert.equal(isScreenedCaptionProfile(current), true);
    assert.equal(isManualMediaProfile(legacy), short); assert.equal(isManualMediaProfile(current), short);
    assert.ok(bodyMediaProfile(legacy).includes("caption-pages"));
    assert.deepEqual(candidate, before);
  }
});

test("held classes cannot cross geometry, drop captions or use body/unknown tokens", () => {
  for (const [short, other] of [[false, CAPTION_SHORT_PROFILE], [true, CAPTION_PROFILE]] as const) {
    for (const token of [other, bodyMediaProfile(other), "unity-source-float-own-screen-v1",
      "unity-source-float-manual-short-own-screen-v1", "__proto__", "constructor", null, {}, true]) {
      assert.throws(() => openingMediaProfileForPlan(plan(short), token));
    }
  }
  for (const token of [null, true, {}, "constructor", "__proto__"]) assert.throws(() => openingMediaProfile(token));
});

test("actual Python and TS agree on every fresh, held legacy, current and refused class", () => {
  const tokens = [CAPTION_PROFILE, CAPTION_SHORT_PROFILE, SCREENED_CAPTION_PROFILE, SCREENED_CAPTION_SHORT_PROFILE,
    "unity-source-float-own-screen-v1", "unity-source-float-manual-short-own-screen-v1", null, {}, true, "constructor",
    bodyMediaProfile(SCREENED_CAPTION_PROFILE), bodyMediaProfile(CAPTION_SHORT_PROFILE)];
  const plans = [plan(), plan(true), { ...plan(), captions: { burn: false }, captionsTrack: undefined },
    { ...plan(true), captions: { burn: false }, captionsTrack: undefined }];
  const cases = plans.flatMap((candidate) => [{ plan: candidate }, ...tokens.map((token) => ({ plan: candidate, token }))]);
  const expected = cases.map((row) => {
    try { return openingMediaProfileForPlan(row.plan, "token" in row ? row.token : undefined); }
    catch { return null; }
  });
  const code = "import json,sys\nfrom guided_media_profile import profile_for_plan\nout=[]\nfor row in json.load(sys.stdin):\n try:\n  out.append(profile_for_plan(row['plan'],row['token']) if 'token' in row else profile_for_plan(row['plan']))\n except (RuntimeError,ValueError,KeyError,TypeError):out.append(None)\nprint(json.dumps(out))";
  const actual = JSON.parse(execFileSync(path.resolve(".venv/bin/python"), ["-B", "-c", code], {
    input: JSON.stringify(cases), encoding: "utf8", timeout: 10_000, maxBuffer: 64 * 1024,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: path.resolve("scripts/producer") } }));
  assert.deepEqual(actual, expected);
});

test("TS and actual Python refuse every unqualified caption/custom/finishing field consistently", () => {
  const changes: Array<Record<string, unknown>> = [{}, { captionStyles: {} }, { captionChapters: [] },
    { captionCorrectionLedger: {} }, { dialogueCaptionAuthority: {} }, { chapters: [{}] }, { captions: {} },
    { captions: { burn: 1 } }, { captions: { burn: false } }, { captions: { burn: true, bandYOffsetPx: 2 } },
    { titleCards: [{}] }, { brollTrack: [{}] }, { punchIns: [{}] }, { transitions: [{}] }, { audioGain: 2 },
    { audioEnhance: { preset: "voice" } }, { baselineLook: { grade: "warm" } }, { overlays: true },
    { target: { mode: "longform", width: 1280, height: 720 } }, { reframe: { strategy: "face" } }];
  const track = plan().captionsTrack as Record<string, unknown>;
  changes.push(...[{ schemaVersion: true }, { source: "guess" }, { defaultPolicy: "off" }, { groups: [{}] },
    { transcriptCorrectionHash: "a".repeat(64) }].map((value) => ({ captionsTrack: { ...track, ...value } })));
  const values = changes.map((value) => ({ ...plan(), ...value }));
  const code = "import json,sys\nfrom guided_opening_frames import _profile\nfrom guided_media_profile import profile_for_plan\nout=[]\nfor p in json.load(sys.stdin):\n try:\n  _profile(p,profile_for_plan(p));out.append(True)\n except (RuntimeError,ValueError,KeyError,TypeError):out.append(False)\nprint(json.dumps(out))";
  const actual = JSON.parse(execFileSync(path.resolve(".venv/bin/python"), ["-c", code], { input: JSON.stringify(values),
    encoding: "utf8", timeout: 10_000, maxBuffer: 64 * 1024, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: path.resolve("scripts/producer") } }));
  assert.deepEqual(values.map(admitted), actual);
  assert.equal(actual[0], true); assert.equal(actual.slice(1).some(Boolean), false);
});

test("whole-program page upper bound is counted before any render", () => {
  const candidate = plan();
  assert.doesNotThrow(() => assertCaptionGraphWorkload(candidate, { frameRate: "30000/1001", totalFrames: 23 * 899 }, 8));
  assert.throws(() => assertCaptionGraphWorkload(candidate, { frameRate: "30000/1001", totalFrames: 24 * 899 }, 8), /workload/);
  for (const frameRate of ["0/1", "-30/1", "30/0", "30/1/2", "NaN"]) {
    assert.throws(() => assertCaptionGraphWorkload(candidate, { frameRate, totalFrames: 60 }, 0));
  }
});
