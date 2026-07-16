import assert from "node:assert/strict";
import {
  buildAutoEditRequest,
  buildResumeAutoEditRequest,
  buildStarterPlan,
} from "../intent-flow";
import type { ProjectIntent } from "../intent-presets";
import type { AssetManifest } from "../types";

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

{
  const plan = buildStarterPlan(manifest, longform);
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
  assert.deepEqual(plan.audioEnhance, { preset: "voice" });
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
  assert.throws(() => buildAutoEditRequest("/tmp/job"), /requires a stored edit intent/);
  assert.throws(() => buildResumeAutoEditRequest("/tmp/job"), /requires a stored edit intent/);
}

console.log("intent-flow.test.ts: all assertions passed");
