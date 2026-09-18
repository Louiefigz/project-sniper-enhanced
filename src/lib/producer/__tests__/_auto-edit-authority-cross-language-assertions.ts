import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { claudeArgs } from
  "../../../app/api/producer/auto-edit/authoring";
import { claudeCutAuthoringBashPatterns } from
  "../../../app/api/producer/auto-edit/cut-authoring-prompt";
import type { AutoEditCtx } from
  "../../../app/api/producer/auto-edit/stream";
import { autoEditAuthoritySnapshot } from
  "../../server/auto-edit-authority-snapshot";
import { canonicalJsonSha256 } from "../../server/auto-edit-hash";
import { restoreAutoEditPipeline } from
  "../../server/auto-edit-pipeline-authority";

const PRELOAD_PATH = "scripts/producer/headless/node_isolated_user.cjs";

interface InputFixture {
  transcript: string;
  frame: string;
}

export function assertInputFreshness(
  fix: InputFixture,
  ctx: AutoEditCtx,
  initial: string,
): void {
  const plan = readFileSync(ctx.planPath, "utf8");
  writeFileSync(ctx.planPath,
    "{\"planVersion\":2,\"cutTrack\":[{\"sourceId\":\"clip\",\"in\":0,\"out\":1}]}\n");
  assert.notEqual(autoEditAuthoritySnapshot(ctx).digest, initial);
  writeFileSync(ctx.planPath, plan);
  const manifest = readFileSync(ctx.manifestPath, "utf8");
  writeFileSync(ctx.manifestPath, manifest.replace("media", "changed-media"));
  assert.notEqual(autoEditAuthoritySnapshot(ctx).digest, initial);
  writeFileSync(ctx.manifestPath, manifest);
  writeFileSync(fix.transcript,
    "{\"transcript\":[{\"text\":\"changed\"}]}\n");
  assert.notEqual(autoEditAuthoritySnapshot(ctx).digest, initial);
  writeFileSync(fix.transcript,
    "{\"transcript\":[{\"text\":\"héllo 🎬\"}]}\n");
  writeFileSync(fix.frame, "changed-frame");
  assert.notEqual(autoEditAuthoritySnapshot(ctx).digest, initial);
  writeFileSync(fix.frame, "golden-frame");
  const projectPath = path.join(path.dirname(ctx.dir), "project.json");
  const project = JSON.parse(readFileSync(projectPath, "utf8"));
  writeFileSync(projectPath, JSON.stringify({
    ...project, intent: { ...project.intent, brief: "changed" },
  }));
  assert.notEqual(autoEditAuthoritySnapshot(ctx).digest, initial);
  writeFileSync(projectPath, JSON.stringify(project));
  assert.notEqual(autoEditAuthoritySnapshot({
    ...ctx, intent: { ...ctx.intent!, brief: "changed requested intent" },
  }).digest, initial);
  assert.equal(autoEditAuthoritySnapshot(ctx).digest, initial);
}

export function assertSnapshotTamper(ctx: AutoEditCtx): void {
  const pipeline = ctx.pipeline!;
  const first = pipeline.files[0];
  const copy = path.join(pipeline.snapshotRoot, ...first.path.split("/"));
  const bytes = readFileSync(copy);
  writeFileSync(copy, "tampered");
  assert.throws(() => restoreAutoEditPipeline(pipeline), /copy was changed/);
  writeFileSync(copy, bytes);
  const lock = readFileSync(pipeline.lockPath);
  const value = JSON.parse(lock.toString("utf8"));
  value.digest = "0".repeat(64);
  writeFileSync(pipeline.lockPath, JSON.stringify(value));
  assert.throws(() => restoreAutoEditPipeline(pipeline), /does not match/);
  writeFileSync(pipeline.lockPath, lock);
  const missing = JSON.parse(lock.toString("utf8")) as {
    digest: string;
    files: Array<{ path: string; hash: string }>;
  };
  missing.files = missing.files.filter((row) => row.path !== PRELOAD_PATH);
  missing.digest = canonicalJsonSha256(missing.files);
  writeFileSync(pipeline.lockPath, JSON.stringify(missing));
  assert.throws(
    () => restoreAutoEditPipeline({
      ...pipeline, digest: missing.digest, files: missing.files,
    }),
    /Required Producer pipeline asset is missing/,
    "a self-consistent receipt may not erase a required runtime asset",
  );
  writeFileSync(pipeline.lockPath, lock);
}

export function assertPinnedPythonResolver(ctx: AutoEditCtx): void {
  const moduleUrl = pathToFileURL(path.join(
    process.cwd(), "src", "app", "api", "_lib", "spawn-python.ts",
  )).href;
  const code = `import helper from ${JSON.stringify(moduleUrl)}; console.log(helper.SCRIPTS_DIR);`;
  const result = spawnSync(process.execPath, [
    "--import", "tsx", "--input-type=module", "-e", code,
  ], {
    encoding: "utf8",
    env: { ...process.env, SNIPER_PIPELINE_ROOT: ctx.pipeline!.snapshotRoot },
  });
  if (result.status !== 0) throw new Error(result.stderr || result.stdout);
  assert.equal(result.stdout.trim(),
    path.join(ctx.pipeline!.snapshotRoot, "scripts"));
}

export function assertPinnedTemplateResolver(ctx: AutoEditCtx): void {
  const runtime = "/runtime/repository";
  const result = spawnSync(
    path.join(process.cwd(), ".venv", "bin", "python3"),
    [
      "-c",
      "from graphics.graphics_render import MOTION_DIR, RUNTIME_ROOT; print(MOTION_DIR); print(RUNTIME_ROOT)",
    ],
    {
      encoding: "utf8",
      env: {
        ...process.env,
        PYTHONPATH: path.join(process.cwd(), "scripts", "producer"),
        SNIPER_PIPELINE_ROOT: ctx.pipeline!.snapshotRoot,
        SNIPER_RUNTIME_REPO_ROOT: runtime,
      },
    },
  );
  if (result.status !== 0) throw new Error(result.stderr || result.stdout);
  assert.deepEqual(result.stdout.trim().split("\n"), [
    path.join(ctx.pipeline!.snapshotRoot, "templates", "motion"), runtime,
  ]);
}

export function assertPinnedRuntimeAssets(ctx: AutoEditCtx): void {
  const root = ctx.pipeline!.snapshotRoot;
  const code = [
    "import json, os",
    "from render_effect_registry import load_registry",
    `preload = os.path.join(${JSON.stringify(root)}, *${JSON.stringify(PRELOAD_PATH.split("/"))})`,
    "print(json.dumps({'registry': load_registry()['registryId'], 'preload': os.path.isfile(preload)}))",
  ].join("; ");
  const result = spawnSync(path.join(process.cwd(), ".venv", "bin", "python3"), [
    "-c", code,
  ], {
    encoding: "utf8",
    env: {
      ...process.env,
      PYTHONPATH: path.join(root, "scripts", "producer"),
      SNIPER_PIPELINE_ROOT: root,
    },
  });
  if (result.status !== 0) throw new Error(result.stderr || result.stdout);
  assert.deepEqual(JSON.parse(result.stdout), {
    registry: "sniper-current-render-effects-v1",
    preload: true,
  });
}

function cutAllowedTools(ctx: AutoEditCtx): string {
  const args = claudeArgs(ctx, "cut");
  return args[args.indexOf("--allowedTools") + 1];
}

export function assertPinnedCutPermissions(
  initial: AutoEditCtx,
  resumed: AutoEditCtx,
): void {
  const initialCommands = claudeCutAuthoringBashPatterns(initial);
  const resumedCommands = claudeCutAuthoringBashPatterns(resumed);
  assert.deepEqual(resumedCommands, initialCommands,
    "resume must preserve the exact immutable command spellings");
  assert.equal(cutAllowedTools(resumed), cutAllowedTools(initial));
  for (const command of resumedCommands) {
    assert.ok(command.includes(resumed.pipeline!.snapshotRoot));
    assert.equal(
      command.includes(`${process.cwd()}/scripts/producer/`), false,
      "authoring must never fall back to mutable Producer scripts");
  }
}
