import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { claudeArgs } from "../../../app/api/producer/auto-edit/authoring";
import { claudeCutAuthoringBashPatterns } from
  "../../../app/api/producer/auto-edit/cut-authoring-prompt";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { autoEditAuthoritySnapshot } from "../../server/auto-edit-authority-snapshot";
import {
  captureAutoEditDoctrine,
  PRODUCER_CORE_DOCTRINE_PATHS,
  PRODUCER_REFERENCED_DOCTRINE_PATHS,
} from "../../server/auto-edit-doctrine";
import { autoEditRequestKey } from "../../server/auto-edit-hash";
import {
  captureAutoEditPipeline,
  prepareAutoEditRunContext,
  restoreAutoEditPipeline,
} from "../../server/auto-edit-pipeline-authority";

interface Fixture {
  repo: string;
  ctx: AutoEditCtx;
  transcript: string;
  frame: string;
  probe: string;
}

interface Golden {
  requestKey: string;
  snapshot: ReturnType<typeof autoEditAuthoritySnapshot>;
}

function write(root: string, relative: string, content: string | Buffer): string {
  const destination = path.join(root, relative);
  mkdirSync(path.dirname(destination), { recursive: true });
  writeFileSync(destination, content);
  return destination;
}

function doctrineFiles(repo: string): void {
  for (const relative of [
    ...PRODUCER_CORE_DOCTRINE_PATHS,
    ...PRODUCER_REFERENCED_DOCTRINE_PATHS,
    "docs/studies/CALEB_STYLE.md",
  ]) write(repo, relative, `DOCTRINE ${relative} — café\n`);
}

function pipelineFiles(repo: string): string {
  const probe = write(repo, "scripts/producer/probe.py", "print('PINNED-PIPELINE')\n");
  write(repo, "scripts/producer/producer_config.py", "# deterministic café config\n");
  const modelPath = path.join(process.cwd(), "scripts/producer/audio/models/bd.rnnn");
  write(repo, "scripts/producer/audio/models/bd.rnnn", readFileSync(modelPath));
  write(repo, "scripts/producer/audio/models/not-allowlisted.rnnn", "do not capture\n");
  write(repo, "templates/motion/tokens.css", ":root { --accent: #abcdef; }\n");
  write(repo, "src/app/api/producer/auto-edit/example.ts", "export const value = 1;\n");
  write(repo, "src/app/api/producer/ai-edit/native.ts", "export const native = 1;\n");
  write(repo, "src/app/api/producer/palmier/qc.ts", "export const qc = 1;\n");
  write(repo, "src/app/api/_lib/audit-gate.ts", "export const audit = true;\n");
  write(repo, "src/lib/server/auto-edit-authority.ts", "export const authority = 1;\n");
  write(repo, "src/lib/server/auto-edit-quality-artifacts.ts", "export const quality = 1;\n");
  write(repo, "package.json", "{\"name\":\"golden\"}\n");
  write(repo, "package-lock.json", "{\"lockfileVersion\":3}\n");
  return probe;
}

function fixture(root: string): Fixture {
  const repo = path.join(root, "repo");
  const project = path.join(root, "project");
  const dir = path.join(project, "producer");
  const source = path.join(project, "source");
  const reference = path.join(project, "reference");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  mkdirSync(reference, { recursive: true });
  doctrineFiles(repo);
  const probe = pipelineFiles(repo);
  const planPath = write(project, "producer/edit_plan.json",
    "{\"planVersion\":1,\"target\":{\"durationTargetS\":1.0},\"cutTrack\":[]}\n");
  const transcript = write(project, "source/clip.transcript.json",
    "{\"transcript\":[{\"text\":\"héllo 🎬\"}]}\n");
  const manifestPath = write(project, "source/asset_manifest.json",
    "{\"sources\":[{\"path\":\"clip.mp4\",\"contentHash\":\"media\",\"transcriptPath\":\"clip.transcript.json\"}]}\n");
  const profilePath = write(project, "reference/style_profile.json", "{\"style\":\"measured\"}\n");
  const deepStudyPath = write(project, "reference/deep_study.json", "{\"study\":\"deep\"}\n");
  const frame = write(project, "reference/frame.jpg", "golden-frame");
  write(project, "reference/reference.json", "{\"strategy\":\"mimic\"}\n");
  write(project, "reference/fingerprint.json", "{\"sha256\":\"source\"}\n");
  write(project, "reference/reference-source.json", "{\"source\":\"local\"}\n");
  const intent = { mode: "short" as const, style: "caleb" as const, brief: "café 🎬", lanes: {} };
  write(project, "project.json", JSON.stringify({ origin: "raw", history: [], intent }));
  return { repo, transcript, frame, probe, ctx: {
    dir, scope: "produced", intent, planPath, manifestPath, transcriptsDir: source,
    referenceStudy: {
      id: "golden-ref", title: "Référence", mode: "short", dir: reference,
      profilePath, deepStudyPath, representativeFrames: [frame],
    },
  } };
}

function pinned(fix: Fixture, runId: string): AutoEditCtx {
  const doctrine = captureAutoEditDoctrine(fix.ctx, runId, fix.repo);
  const pipeline = captureAutoEditPipeline(fix.ctx, runId, fix.repo);
  return { ...fix.ctx, doctrine, pipeline };
}

function pythonResult(ctx: AutoEditCtx, requestCtx: AutoEditCtx): {
  snapshot: ReturnType<typeof autoEditAuthoritySnapshot>;
  requestKey: string;
} {
  const script = [
    "import json, sys",
    "from palmier.quality_hash import authority_snapshot, request_key",
    "value = json.load(sys.stdin)",
    "print(json.dumps({'snapshot': authority_snapshot(value['ctx']), 'requestKey': request_key(value['requestCtx'])}, sort_keys=True))",
  ].join("; ");
  const result = spawnSync(path.join(process.cwd(), ".venv", "bin", "python3"), ["-c", script], {
    input: JSON.stringify({ ctx, requestCtx }), encoding: "utf8",
    env: { ...process.env, PYTHONPATH: path.join(process.cwd(), "scripts", "producer") },
  });
  if (result.status !== 0) throw new Error(result.stderr || result.stdout);
  return JSON.parse(result.stdout) as ReturnType<typeof pythonResult>;
}

function fixedRequestContext(ctx: AutoEditCtx): AutoEditCtx {
  return {
    ...ctx,
    dir: "/golden/project/producer", planPath: "/golden/project/producer/edit_plan.json",
    manifestPath: "/golden/project/source/asset_manifest.json",
    transcriptsDir: "/golden/project/source",
    referenceStudy: undefined,
  };
}

function assertInputFreshness(fix: Fixture, ctx: AutoEditCtx, initial: string): void {
  const plan = readFileSync(ctx.planPath, "utf8");
  writeFileSync(ctx.planPath, "{\"planVersion\":2,\"cutTrack\":[{\"sourceId\":\"clip\",\"in\":0,\"out\":1}]}\n");
  assert.notEqual(autoEditAuthoritySnapshot(ctx).digest, initial);
  writeFileSync(ctx.planPath, plan);
  const manifest = readFileSync(ctx.manifestPath, "utf8");
  writeFileSync(ctx.manifestPath, manifest.replace("media", "changed-media"));
  assert.notEqual(autoEditAuthoritySnapshot(ctx).digest, initial);
  writeFileSync(ctx.manifestPath, manifest);
  writeFileSync(fix.transcript, "{\"transcript\":[{\"text\":\"changed\"}]}\n");
  assert.notEqual(autoEditAuthoritySnapshot(ctx).digest, initial);
  writeFileSync(fix.transcript, "{\"transcript\":[{\"text\":\"héllo 🎬\"}]}\n");
  writeFileSync(fix.frame, "changed-frame");
  assert.notEqual(autoEditAuthoritySnapshot(ctx).digest, initial);
  writeFileSync(fix.frame, "golden-frame");
  const projectPath = path.join(path.dirname(ctx.dir), "project.json");
  const project = JSON.parse(readFileSync(projectPath, "utf8"));
  writeFileSync(projectPath, JSON.stringify({ ...project, intent: { ...project.intent, brief: "changed" } }));
  assert.notEqual(autoEditAuthoritySnapshot(ctx).digest, initial);
  writeFileSync(projectPath, JSON.stringify(project));
  assert.notEqual(autoEditAuthoritySnapshot({
    ...ctx, intent: { ...ctx.intent!, brief: "changed requested intent" },
  }).digest, initial);
  assert.equal(autoEditAuthoritySnapshot(ctx).digest, initial);
}

function assertSnapshotTamper(ctx: AutoEditCtx): void {
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
}

function assertPinnedPythonResolver(ctx: AutoEditCtx): void {
  const moduleUrl = pathToFileURL(path.join(
    process.cwd(), "src", "app", "api", "_lib", "spawn-python.ts",
  )).href;
  const code = `import helper from ${JSON.stringify(moduleUrl)}; console.log(helper.SCRIPTS_DIR);`;
  const result = spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "-e", code], {
    encoding: "utf8",
    env: { ...process.env, SNIPER_PIPELINE_ROOT: ctx.pipeline!.snapshotRoot },
  });
  if (result.status !== 0) throw new Error(result.stderr || result.stdout);
  assert.equal(result.stdout.trim(), path.join(ctx.pipeline!.snapshotRoot, "scripts"));
}

function assertPinnedTemplateResolver(ctx: AutoEditCtx): void {
  const runtime = "/runtime/repository";
  const result = spawnSync(path.join(process.cwd(), ".venv", "bin", "python3"), [
    "-c",
    "from graphics.graphics_render import MOTION_DIR, RUNTIME_ROOT; print(MOTION_DIR); print(RUNTIME_ROOT)",
  ], {
    encoding: "utf8",
    env: {
      ...process.env,
      PYTHONPATH: path.join(process.cwd(), "scripts", "producer"),
      SNIPER_PIPELINE_ROOT: ctx.pipeline!.snapshotRoot,
      SNIPER_RUNTIME_REPO_ROOT: runtime,
    },
  });
  if (result.status !== 0) throw new Error(result.stderr || result.stdout);
  assert.deepEqual(result.stdout.trim().split("\n"), [
    path.join(ctx.pipeline!.snapshotRoot, "templates", "motion"), runtime,
  ]);
}

function cutAllowedTools(ctx: AutoEditCtx): string {
  const args = claudeArgs(ctx, "cut");
  return args[args.indexOf("--allowedTools") + 1];
}

function assertPinnedCutPermissions(initial: AutoEditCtx, resumed: AutoEditCtx): void {
  const initialCommands = claudeCutAuthoringBashPatterns(initial);
  const resumedCommands = claudeCutAuthoringBashPatterns(resumed);
  assert.deepEqual(resumedCommands, initialCommands,
    "resume must preserve the exact immutable command spellings");
  assert.equal(cutAllowedTools(resumed), cutAllowedTools(initial));
  for (const command of resumedCommands) {
    assert.ok(command.includes(resumed.pipeline!.snapshotRoot));
    assert.equal(command.includes(`${process.cwd()}/scripts/producer/`), false,
      "authoring must never fall back to mutable Producer scripts");
  }
}

function main(): void {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-authority-cross-language-"));
  try {
    const fix = fixture(root);
    const ctx = pinned(fix, "golden-run");
    const modelPath = "scripts/producer/audio/models/bd.rnnn";
    assert.ok(ctx.pipeline?.files.some((row) => row.path === modelPath));
    assert.ok(!ctx.pipeline?.files.some((row) => row.path.endsWith("not-allowlisted.rnnn")));
    assert.deepEqual(readFileSync(path.join(ctx.pipeline!.snapshotRoot, ...modelPath.split("/"))),
      readFileSync(path.join(process.cwd(), ...modelPath.split("/"))));
    const requestCtx = fixedRequestContext(ctx);
    assert.equal(autoEditRequestKey({ ...requestCtx,
      brainSessionId: "runtime-only", brainSessionEstablished: true }),
    autoEditRequestKey(requestCtx));
    const ts = { snapshot: autoEditAuthoritySnapshot(ctx), requestKey: autoEditRequestKey(requestCtx) };
    const py = pythonResult(ctx, requestCtx);
    assert.deepEqual(py, ts, "TypeScript and Python must produce the same complete authority");
    const legacy = { ...ctx, doctrine: undefined, pipeline: undefined };
    assert.deepEqual(
      pythonResult(legacy, fixedRequestContext(legacy)).snapshot,
      autoEditAuthoritySnapshot(legacy),
      "legacy managed markers must use the same completely sorted row contract",
    );
    const golden = JSON.parse(readFileSync(path.join(__dirname, "fixtures", "auto-edit-authority-golden.json"), "utf8")) as Golden;
    assert.deepEqual(ts, golden);
    const sourceDigest = ts.snapshot.pipelineDigest;
    writeFileSync(fix.probe, "print('LIVE-CHANGED')\n");
    assert.equal(autoEditAuthoritySnapshot(ctx).pipelineDigest, sourceDigest);
    const execution = spawnSync(path.join(process.cwd(), ".venv", "bin", "python3"), [
      path.join(ctx.pipeline!.snapshotRoot, "scripts", "producer", "probe.py"),
    ], { encoding: "utf8" });
    assert.equal(execution.stdout.trim(), "PINNED-PIPELINE");
    assertPinnedPythonResolver(ctx);
    assertPinnedTemplateResolver(ctx);
    const next = pinned(fix, "next-run");
    assert.notEqual(next.pipeline?.digest, ctx.pipeline?.digest);
    const sourceModel = path.join(fix.repo, ...modelPath.split("/"));
    const modelBytes = readFileSync(sourceModel);
    writeFileSync(sourceModel, "tampered model");
    assert.throws(
      () => captureAutoEditPipeline(fix.ctx, "bad-model", fix.repo),
      /failed verification/,
    );
    writeFileSync(sourceModel, modelBytes);
    const resumed = prepareAutoEditRunContext({
      ctx: fix.ctx, runId: "resume-token", resume: true,
      savedDoctrine: ctx.doctrine, savedPipeline: ctx.pipeline,
    });
    assert.equal(resumed.pipeline?.digest, ctx.pipeline?.digest);
    assertPinnedCutPermissions(ctx, resumed);
    assertInputFreshness(fix, ctx, ts.snapshot.digest);
    assertSnapshotTamper(ctx);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("auto-edit-authority-cross-language.test.ts: all assertions passed");
}

main();
