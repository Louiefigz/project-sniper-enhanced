import assert from "node:assert/strict";
import path from "node:path";
import { draftArgs } from "../../../app/api/producer/palmier/workspace/runner";

const args = draftArgs({
  manifestPath: "/project/source/asset_manifest.json",
  dir: "/project/producer",
  name: "Project title",
  mode: "short",
  workingPath: "/project/producer/base_final.mp4",
});

assert.ok(args[0].endsWith(path.join("producer", "palmier", "draft.py")));
assert.deepEqual(args.slice(1), [
  "/project/source/asset_manifest.json",
  "/project/producer",
  "--require-source-set-admission",
  "--name",
  "Project title",
  "--mode",
  "short",
  "--working-media",
  "/project/producer/base_final.mp4",
]);

console.log("palmier-draft-runner.test.ts: all assertions passed");
