import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { palmierNativePlanHash } from
  "../../../app/api/producer/ai-edit/palmier-native-authority";

const parent = {
  projectId: "project-1",
  timelineId: "timeline-1",
  fingerprint: "a".repeat(64),
  timeline: {
    totalFrames: 10,
    tracks: [{ clips: [{ id: "clip-1" }] }],
  },
};
const plan = {
  schemaVersion: 1,
  parent: {
    projectId: parent.projectId,
    timelineId: parent.timelineId,
    fingerprint: parent.fingerprint,
  },
  requestHash: "b".repeat(64),
  lanes: ["motion"],
  operations: [{
    tool: "set_keyframes",
    args: {
      clipId: "clip-1",
      property: "position",
      keyframes: [[0, { "10": 1e-6, "2": 1e-7 }]],
    },
    reason: "Move the selected clip at the requested beat.",
  }],
};
const script = [
  "import json, sys",
  "from palmier.native_plan import validate_native_plan",
  "from palmier.quality_hash import stable_hash",
  "value = json.load(sys.stdin)",
  "plan = validate_native_plan(value['plan'], value['parent'])",
  "print(stable_hash(plan))",
].join("; ");
const result = spawnSync(
  path.join(process.cwd(), ".venv", "bin", "python3"),
  ["-c", script],
  {
    encoding: "utf8",
    input: JSON.stringify({ parent, plan }),
    env: {
      ...process.env,
      PYTHONPATH: path.join(process.cwd(), "scripts", "producer"),
    },
  },
);

assert.equal(result.status, 0, result.stderr);
assert.equal(palmierNativePlanHash(plan), result.stdout.trim());

console.log("palmier-native-plan-hash-cross-runtime.test.ts: passed");
