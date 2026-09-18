import assert from "node:assert/strict";
import {
  CURRENT_RENDER_GRAPH,
  currentRenderGraphArgs,
  editorReadyRenderGraphArgs,
} from "../current-render-graph-command";
import { approvedRenderGraphReady } from
  "../current-render-graph-candidate";

const renderer = [
  "/repo/scripts/producer/assemble.py",
  "/project/base_final.mp4",
  "/project/edit_plan.json",
  "/project/final.mp4",
];
const args = currentRenderGraphArgs({
  phase: "assemble",
  producerDir: "/project",
  planPath: "/project/edit_plan.json",
  manifestPath: "/project/source/asset_manifest.json",
  basePath: "/project/base_final.mp4",
  outputPath: "/project/final.mp4",
  deferActive: true,
  rendererArgs: renderer,
});

assert.equal(args[0], CURRENT_RENDER_GRAPH);
assert.deepEqual(args.slice(args.indexOf("--") + 1), renderer);
assert.deepEqual(args.slice(1, args.indexOf("--")), [
  "--phase", "assemble",
  "--producer-dir", "/project",
  "--plan", "/project/edit_plan.json",
  "--manifest", "/project/source/asset_manifest.json",
  "--base", "/project/base_final.mp4",
  "--output", "/project/final.mp4",
  "--defer-active",
]);

const base = currentRenderGraphArgs({
  phase: "base",
  producerDir: "/project",
  planPath: "/attempt/edit_plan.json",
  nextPlanPath: "/project/edit_plan.json",
  manifestPath: "/project/source/asset_manifest.json",
  basePath: "/project/base_final.mp4",
  outputPath: "/project/final.mp4",
  forceFull: true,
  rendererArgs: ["/repo/scripts/producer/render.py"],
});
assert.deepEqual(base.slice(base.indexOf("--next-plan"), base.indexOf("--")), [
  "--next-plan", "/project/edit_plan.json", "--force-full",
]);

const privateCandidate = currentRenderGraphArgs({
  phase: "assemble", producerDir: "/project",
  artifactDir: "/private/candidate", planPath: "/private/candidate/edit_plan.json",
  manifestPath: "/project/source/asset_manifest.json",
  basePath: "/private/candidate/base_final.mp4",
  outputPath: "/private/candidate/final.mp4",
  rendererArgs: ["/repo/scripts/producer/assemble.py"],
});
const artifactIndex = privateCandidate.indexOf("--artifact-dir");
assert.deepEqual(
  privateCandidate.slice(artifactIndex, artifactIndex + 2),
  ["--artifact-dir", "/private/candidate"],
);

const editorReady = editorReadyRenderGraphArgs({
  producerDir: "/project",
  sourcePlanPath: "/request/edit_plan.json",
  outputPlanPath: "/project/edit_plan.json",
  manifestPath: "/source/asset_manifest.json",
  basePath: "/project/base_final.mp4",
  outputPath: "/project/final.mp4",
  fingerprintPath: "/project/base.fingerprint.json",
  workDir: "/tmp/work",
  renderScript: "/scripts/render.py",
  assembleScript: "/scripts/assemble.py",
});
assert.deepEqual(
  editorReady.baseArgs.slice(editorReady.baseArgs.indexOf("--") + 1),
  [
    "/scripts/render.py", "/request/edit_plan.json",
    "/source/asset_manifest.json", "/project", "--workdir", "/tmp/work",
    "--skip-graphics", "--require-source-set-admission",
  ],
);
assert.deepEqual(
  editorReady.assembleArgs.slice(editorReady.assembleArgs.indexOf("--") + 1),
  [
    "/scripts/assemble.py", "/project/base_final.mp4",
    "/project/edit_plan.json", "/project/final.mp4", "--fingerprint",
    "/project/base.fingerprint.json", "--auto-base", "--manifest",
    "/source/asset_manifest.json", "--require-source-set-admission",
  ],
);

const privateEditorReady = editorReadyRenderGraphArgs({
  producerDir: "/project",
  artifactDir: "/private/candidate",
  sourcePlanPath: "/private/input/edit_plan.json",
  outputPlanPath: "/private/candidate/edit_plan.json",
  manifestPath: "/source/asset_manifest.json",
  basePath: "/private/candidate/base_final.mp4",
  outputPath: "/private/candidate/final.mp4",
  fingerprintPath: "/private/candidate/base.fingerprint.json",
  workDir: "/private/work",
  renderScript: "/scripts/render.py",
  assembleScript: "/scripts/assemble.py",
  deferActive: true,
});
assert.ok(privateEditorReady.baseArgs.includes("/private/candidate"));
assert.ok(privateEditorReady.assembleArgs.includes("--defer-active"));

const exactAudio = editorReadyRenderGraphArgs({
  producerDir: "/project", artifactDir: "/private/audio-candidate",
  sourcePlanPath: "/request/plan.json", outputPlanPath: "/private/audio-candidate/edit_plan.json",
  manifestPath: "/source/asset_manifest.json", basePath: "/private/audio-candidate/base.mp4",
  outputPath: "/private/audio-candidate/final.mp4", fingerprintPath: "/private/audio-candidate/base.fingerprint.json",
  workDir: "/private/work", renderScript: "/scripts/render.py", assembleScript: "/scripts/assemble.py",
  audioClockPolicy: "source-float-v2", deferActive: true,
});
for (const command of [exactAudio.baseArgs, exactAudio.assembleArgs]) {
  const separator = command.indexOf("--");
  const wrapper = command.slice(0, separator);
  const child = command.slice(separator + 1);
  assert.equal(wrapper.filter((value) => value === "--audio-clock-policy").length, 1);
  assert.equal(child.filter((value) => value === "--audio-clock-policy").length, 1);
  assert.equal(wrapper[wrapper.indexOf("--audio-clock-policy") + 1], "source-float-v2");
  assert.equal(child[child.indexOf("--audio-clock-policy") + 1], "source-float-v2");
}
assert.ok(!editorReady.baseArgs.includes("--audio-clock-policy"), "default renderer remains unchanged");
assert.ok(!editorReady.assembleArgs.includes("--audio-clock-policy"), "no implicit GUI/default rollout");

assert.equal(
  approvedRenderGraphReady(
    "/project",
    "/project/edit_plan.json",
    "/project/source/asset_manifest.json",
    "a".repeat(64),
  ),
  false,
);

console.log("current-render-graph-command tests passed");
