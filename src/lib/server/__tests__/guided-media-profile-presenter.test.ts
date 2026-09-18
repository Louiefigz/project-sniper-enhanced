import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { test } from "node:test";
import { CAPTION_PROFILE, CAPTION_SHORT_PROFILE, SCREENED_CAPTION_PROFILE,
  SCREENED_CAPTION_SHORT_PROFILE } from "@/lib/producer/contracts/guided-caption-profile";
import { MANUAL_SHORT_PROFILE, assertManualCaptionShortPlan, assertManualShortPlan,
  openingMediaProfileForPlan, type OpeningMediaProfile } from "@/lib/producer/contracts/guided-media-profile";

/** Metadata-only TEST plan; no source, framing, execution or approval evidence. */
function candidate(short: boolean, captioned: boolean): Record<string, unknown> {
  return { target: { mode: short ? "short" : "longform", width: short ? 1080 : 1920, height: short ? 1920 : 1080 },
    cutTrack: [{ sourceId: "TEST", start: 0, end: 2 }], captions: { burn: captioned },
    ...(short ? { reframe: { layout: "fill", crop: [0, 0, 1, 1], track: false } } : {}),
    ...(captioned ? { captionsTrack: { schemaVersion: 1, source: "kept-transcript", defaultPolicy: "line", groups: [] } } : {}) };
}

/** Include both held historical caption tokens and their fresh screened equivalents. */
function cases(): Array<{ plan: Record<string, unknown>; held: OpeningMediaProfile; fresh: OpeningMediaProfile }> {
  return [
    { plan: candidate(false, false), held: "unity-source-float-own-screen-v1", fresh: "unity-source-float-own-screen-v1" },
    { plan: candidate(true, false), held: MANUAL_SHORT_PROFILE, fresh: MANUAL_SHORT_PROFILE },
    { plan: candidate(false, true), held: CAPTION_PROFILE, fresh: SCREENED_CAPTION_PROFILE },
    { plan: candidate(false, true), held: SCREENED_CAPTION_PROFILE, fresh: SCREENED_CAPTION_PROFILE },
    { plan: candidate(true, true), held: CAPTION_SHORT_PROFILE, fresh: SCREENED_CAPTION_SHORT_PROFILE },
    { plan: candidate(true, true), held: SCREENED_CAPTION_SHORT_PROFILE, fresh: SCREENED_CAPTION_SHORT_PROFILE },
  ];
}

test("absent presenterLayouts keeps every old fresh and held class unchanged", () => {
  for (const row of cases()) {
    const before = structuredClone(row.plan);
    assert.equal(openingMediaProfileForPlan(row.plan), row.fresh);
    assert.equal(openingMediaProfileForPlan(row.plan, row.held), row.held);
    assert.deepEqual(row.plan, before);
  }
});

test("any present presenterLayouts refuses old fresh and held selectors without mutation", () => {
  const rows = cases().flatMap((row) => [null, [], false, {}, 0, "", [{ assetId: "TEST" }], undefined]
    .map((presenterLayouts) => ({ ...row, plan: { ...row.plan, presenterLayouts } })));
  for (const row of rows) {
    const before = structuredClone(row.plan);
    assert.throws(() => openingMediaProfileForPlan(row.plan), /presenterLayouts/);
    assert.throws(() => openingMediaProfileForPlan(row.plan, row.held), /presenterLayouts/);
    assert.deepEqual(row.plan, before);
  }
});

test("direct manual validators cannot discard present but empty presenter intent", () => {
  for (const presenterLayouts of [null, [], false, undefined]) {
    assert.throws(() => assertManualShortPlan({ ...candidate(true, false), presenterLayouts }), /presenterLayouts/);
    assert.throws(() => assertManualCaptionShortPlan({ ...candidate(true, true), presenterLayouts }), /presenterLayouts/);
  }
});

test("actual Python selector and explicit held frame-profile entry reject the same property presence", () => {
  const rows = cases().flatMap((row) => [row, ...[null, [], false, {}, 0, "", [{ assetId: "TEST" }]]
    .map((presenterLayouts) => ({ ...row, plan: { ...row.plan, presenterLayouts } }))]);
  const code = ["import json,sys", "from guided_media_profile import profile_for_plan",
    "from guided_opening_frames import _profile", "out=[]", "for row in json.load(sys.stdin):", " try:",
    "  fresh=profile_for_plan(row['plan'])", "  held=profile_for_plan(row['plan'],row['held'])",
    "  _profile(row['plan'],row['held'])", "  out.append([fresh,held])",
    " except (RuntimeError,ValueError,KeyError,TypeError):out.append(None)", "print(json.dumps(out))"].join("\n");
  const observed = JSON.parse(execFileSync(path.resolve(".venv/bin/python"), ["-B", "-c", code], {
    input: JSON.stringify(rows), encoding: "utf8", timeout: 10_000, maxBuffer: 64 * 1024,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: path.resolve("scripts/producer") },
  }));
  assert.deepEqual(observed, rows.map((row) => Object.hasOwn(row.plan, "presenterLayouts") ? null : [row.fresh, row.held]));
});
