import assert from "node:assert/strict";
import {
  buildAutoEditRequest,
  buildResumeAutoEditRequest,
  buildStarterPlan,
} from "../intent-flow";
import type { ProjectIntent } from "../intent-presets";
import type { AssetManifest } from "../types";
import { targetStep } from "@/app/api/producer/auto-edit/authoring-prompt";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";

const manifest: AssetManifest = {
  generatedAt: "2026-07-12T00:00:00.000Z",
  input: "/tmp/C0679.mp4",
  sources: [{
    id: "raw-1",
    path: "/tmp/C0679.mp4",
    duration: 834.34,
    fps: 23.976,
    vfr: false,
    resolution: [3840, 2160],
    rotation: 0,
    audio: { present: true, channels: 2, sampleRate: 48000 },
    contentHash: "fixture",
    transcriptPath: "/tmp/C0679.transcript.json",
    role: "source",
  }],
  broll: [],
  music: [],
};

const longform: ProjectIntent = {
  mode: "longform",
  scope: "produced",
  lanes: { broll: "off" },
  music: false,
  audioEnhance: { preset: "voice" },
  preset: "longform-produced",
};

const shortTrim: ProjectIntent = {
  mode: "short",
  scope: "trim",
  lanes: {},
  preset: "trim-only",
};

function promptContext(intent: ProjectIntent): AutoEditCtx {
  return { scope: intent.scope, intent, dir: "/TEST-unused", planPath: "/TEST-unused/plan.json",
    manifestPath: "/TEST-unused/manifest.json", transcriptsDir: "/TEST-unused/transcripts" };
}

{
  const plan = buildStarterPlan(manifest, longform);
  assert.equal(plan.audioAuthorityMode, "mastered-stereo");
  assert.equal(plan.target.mode, "longform");
  assert.equal(plan.target.scope, "produced");
  assert.deepEqual(plan.target.lanes, { broll: "off" });
  assert.deepEqual(plan.target.platforms, ["youtube"]);
  assert.equal(plan.target.durationTargetS, 834.34);
  assert.equal(plan.cutTrack[0].end, 834.34);
  assert.equal(plan.cutTrack[0].speed, 1);
  assert.deepEqual(plan.reframe, { strategy: "none" });
  assert.deepEqual(plan.captions, { burn: false, style: "line" });
  assert.deepEqual(plan.music, { enabled: false });
  assert.equal(plan.target.music, false);
  assert.deepEqual(plan.audioEnhance, { preset: "voice" });
}

{
  const plan = buildStarterPlan(manifest, shortTrim);
  assert.deepEqual(plan.titleCards, []);
  assert.deepEqual(plan.captions, { burn: false, style: "karaoke" });
  assert.deepEqual(plan.target.platforms, ["tiktok", "reels", "shorts"]);
  assert.equal(Object.hasOwn(plan.target, "music"), false);
}

{
  for (const music of [true, false]) {
    const intent = { ...shortTrim, music }, original = structuredClone(intent);
    const plan = buildStarterPlan(manifest, intent);
    assert.equal(plan.target.music, music);
    assert.deepEqual(plan.music, { enabled: music });
    const prompt = targetStep(promptContext(intent));
    assert.ok(prompt.includes(`"music": ${String(music)}`));
    assert.deepEqual(intent, original);
  }
  const prompt = targetStep(promptContext(shortTrim));
  assert.equal(prompt.includes('"music"'), false);
}

{
  assert.deepEqual(buildAutoEditRequest("/tmp/job", longform), {
    dir: "/tmp/job",
    scope: "produced",
    mode: "longform",
    lanes: { broll: "off" },
    music: false,
    audioEnhance: { preset: "voice" },
  });
  assert.deepEqual(buildResumeAutoEditRequest("/tmp/job", longform), {
    dir: "/tmp/job",
    scope: "produced",
    mode: "longform",
    lanes: { broll: "off" },
    music: false,
    audioEnhance: { preset: "voice" },
    resume: true,
  });
  assert.equal(
    buildAutoEditRequest("/tmp/job", longform, "mp4-only").deliveryPolicy,
    "mp4-only",
  );
  assert.equal(
    buildResumeAutoEditRequest(
      "/tmp/job", longform, "mp4-only",
    ).deliveryPolicy,
    "mp4-only",
  );
  assert.throws(() => buildAutoEditRequest("/tmp/job"), /requires a stored edit intent/);
  assert.throws(() => buildResumeAutoEditRequest("/tmp/job"), /requires a stored edit intent/);
  assert.equal(buildResumeAutoEditRequest("/tmp/job", longform, "mp4-only", "cut-first").workflowPolicy, "cut-first");
  assert.equal(buildResumeAutoEditRequest("/tmp/job", longform, "mp4-only").workflowPolicy, undefined);
  assert.throws(() => buildResumeAutoEditRequest("/tmp/job", longform, "palmier-hybrid", "cut-first"), /saved MP4-only workflow/);
}

console.log("intent-flow.test.ts: all assertions passed");
