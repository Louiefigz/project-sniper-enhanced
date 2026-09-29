import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { pythonInterpreter } from "../../../app/api/_lib/spawn-python";
import { ordinaryVisualPlanGateAuthority } from
  "../../../app/api/producer/auto-edit/ordinary-visual-plan-authority";
import { prepareVisualPlanContext, type VisualPlanContext } from
  "../../../app/api/producer/auto-edit/visual-plan-context";
import { prepareSavedPlanReview } from
  "../../../app/api/producer/auto-edit/saved-plan-request";
import type { AutoEditCtx } from
  "../../../app/api/producer/auto-edit/stream";
import {
  captureAutoEditPipeline,
  prepareAutoEditRunContext,
  restoreProjectAutoEditPipeline,
} from "../../server/auto-edit-pipeline-authority";
import {
  autoEditJobPath,
  failAutoEditJob,
  fileSha256,
  readAutoEditJob,
  startAutoEditJob,
} from "../../server/auto-edit-job-store";
import {
  projectVisualPlanBinding,
  visualPlanValidationAuthority,
} from "../../server/visual-plan-binding";
import { canonicalJsonSha256 } from "../../server/auto-edit-hash";
import { writeAdmittedMediaManifest } from "./_visual-plan-media-manifest-fixture";

interface Fixture {
  root: string;
  producer: string;
  ctx: AutoEditCtx;
}

function fixture(): Fixture {
  const root = realpathSync(mkdtempSync(
    path.join(os.tmpdir(), "sniper-visual-snapshot-"),
  ));
  const project = path.join(root, "workspace", "project");
  const producer = path.join(project, "producer");
  const source = path.join(project, "source");
  mkdirSync(producer, { recursive: true });
  mkdirSync(source);
  const planPath = path.join(producer, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  const transcriptPath = path.join(source, "transcript.json");
  writeFileSync(planPath, JSON.stringify({ planVersion: 1,
    cutTrack: [{ sourceId: "source:one", start: 0, end: 1, speed: 1,
      rationale: "Keep one complete source-grounded sentence." }],
    cutDecisions: { schemaVersion: 1, removals: [] } }));
  writeFileSync(transcriptPath, JSON.stringify({ transcript: [{
    start: 0, end: 1, text: "Hello world",
    words: [{ word: "Hello", start: 0, end: 0.45 },
      { word: "world", start: 0.5, end: 0.95 }],
  }] }));
  const mediaPath = path.join(source, "source.mp4");
  writeFileSync(mediaPath, "TEST source metadata authority bytes");
  writeAdmittedMediaManifest(manifestPath, { sources: [{
    id: "source:one", path: mediaPath, transcriptPath: "transcript.json",
  }] });
  writeFileSync(path.join(project, "project.json"), JSON.stringify({
    origin: "raw", history: [],
    visualPlanPolicy: { schemaVersion: 1, ordinaryAutoEdit: "required" },
    intent: {
      mode: "longform", scope: "produced", lanes: {},
      brief: "Retain the saved visual plan.", music: false,
      preset: "longform-produced",
    },
  }));
  return { root, producer, ctx: {
    dir: producer, scope: "produced", deliveryPolicy: "palmier-hybrid",
    intent: { mode: "longform", lanes: { broll: "off" },
      brief: "Retain the saved visual plan.", music: false },
    visualPlanRequiredVersion: 1,
    planPath, manifestPath, transcriptsDir: source,
  } };
}

function snapshotCli(ctx: AutoEditCtx): string {
  return path.join(ctx.pipeline!.snapshotRoot,
    "scripts/producer/planner/visual_plan_cli.py");
}

function catalogPin(ctx: AutoEditCtx): Record<string, unknown> {
  const trustedCli = path.join(process.cwd(),
    "scripts/producer/planner/visual_plan_cli.py");
  const raw = execFileSync(pythonInterpreter(), [
    "-B", trustedCli, "catalog-authority",
    path.join(ctx.dir, "CATALOG-AUTHORITY.json"),
  ], { encoding: "utf8", env: { ...process.env,
    PYTHONDONTWRITEBYTECODE: "1",
    SNIPER_PIPELINE_ROOT: process.cwd() } });
  return JSON.parse(raw) as Record<string, unknown>;
}

function writePresenterPlan(ctx: AutoEditCtx, context: VisualPlanContext): void {
  const output = path.join(ctx.dir, "VISUAL-PLAN.json");
  const contextPath = path.join(ctx.dir, "VISUAL-PLAN-CONTEXT.json");
  const code = [
    "import json,sys",
    "from _visual_plan_fixture import candidate,opportunity,reseal_search_authority,visual_plan",
    "from planner.visual_plan_allocator import allocate_visual_plan",
    "ctx=json.load(open(sys.argv[1])); authority=json.load(open(ctx['transcriptAuthority']['path']))",
    "word=authority['words'][0]; opp=opportunity('opp:one',0,[candidate('candidate:one','presenter')])",
    "opp['transcriptEvidence']={'text':word['text'],'wordIds':[word['id']]}",
    "value=visual_plan(opp); value['project']=ctx['project']; value['catalogPin']=ctx['catalogPin']",
    "value['transcriptAuthority']=ctx['transcriptAuthority']; value['mediaAuthority']=ctx['mediaAuthority']",
    "value['relatedUsageAuthority']=ctx['relatedUsageAuthority']",
    "value['relatedUsage']=ctx['relatedUsage']; reseal_search_authority(value)",
    "open(sys.argv[2],'w').write(json.dumps(allocate_visual_plan(value)))",
  ].join("\n");
  execFileSync(pythonInterpreter(), ["-B", "-c", code, contextPath, output], {
    cwd: path.join(process.cwd(), "scripts/producer"),
    env: { ...process.env, PYTHONPATH: ".:tests", PYTHONDONTWRITEBYTECODE: "1" },
  });
  void context;
}

function assertSnapshotPaths(pin: Record<string, unknown>, root: string): void {
  const canonicalRoot = realpathSync(root);
  for (const key of ["registryPath", "snapshotIndexPath", "capabilityPath", "studyPath"]) {
    assert.equal(typeof pin[key], "string");
    assert.ok((pin[key] as string).startsWith(`${canonicalRoot}${path.sep}`), key);
  }
}

function forgeSnapshotValidator(ctx: AutoEditCtx): void {
  const pipeline = ctx.pipeline!;
  const cli = snapshotCli(ctx);
  writeFileSync(cli, "raise RuntimeError('historical snapshot code executed')\n");
  const files = pipeline.files.map((row) => row.path.endsWith("visual_plan_cli.py")
    ? { ...row, hash: fileSha256(cli)! } : row)
    .sort((left, right) => left.path < right.path ? -1 : left.path > right.path ? 1 : 0);
  const digest = canonicalJsonSha256(files);
  writeFileSync(pipeline.lockPath, `${JSON.stringify({
    schemaVersion: 1, state: "pinned", runId: pipeline.runId, digest, files,
  }, null, 2)}\n`);
  ctx.pipeline = { ...pipeline, digest, files };
}

function main(): void {
  const fix = fixture();
  try {
    fix.ctx.pipeline = captureAutoEditPipeline(
      fix.ctx, "TEST-visual-plan-original", process.cwd(),
    );
    const pin = catalogPin(fix.ctx);
    assertSnapshotPaths(pin, process.cwd());
    const context = prepareVisualPlanContext(fix.ctx)!;
    assertSnapshotPaths(context.catalogPin, process.cwd());
    writePresenterPlan(fix.ctx, context);
    assert.ok(projectVisualPlanBinding(fix.producer));
    const authority = visualPlanValidationAuthority(fix.ctx);
    fix.ctx.visualPlan = projectVisualPlanBinding(fix.producer, authority)!;
    assert.ok(fix.ctx.visualPlan);
    assert.equal(ordinaryVisualPlanGateAuthority(fix.ctx).visualPlanRequired, true);

    const attackCtx = { ...fix.ctx, pipeline: captureAutoEditPipeline(
      fix.ctx, "TEST-forged-visual-plan", process.cwd(),
    ) };
    forgeSnapshotValidator(attackCtx);
    assert.throws(() => projectVisualPlanBinding(
      fix.producer, visualPlanValidationAuthority(attackCtx),
    ), /not the installed executable runtime/);

    const first = startAutoEditJob({
      ctx: fix.ctx, token: "visual-plan-original", snapshots: 0,
      bootstrapPlanHash: fileSha256(fix.ctx.planPath), reviewSavedPlan: true,
    });
    failAutoEditJob(autoEditJobPath(fix.producer), first.token, "test handoff");
    const saved = prepareSavedPlanReview(fix.producer);
    assert.equal(saved.ctx.visualPlanPipeline?.digest, fix.ctx.pipeline.digest);
    const next = prepareAutoEditRunContext({
      ctx: saved.ctx, runId: "TEST-visual-plan-saved-review", resume: false,
    });
    assert.notEqual(next.pipeline?.snapshotRoot, next.visualPlanPipeline?.snapshotRoot);
    assert.equal(ordinaryVisualPlanGateAuthority(next).visualPlanRequired, true);
    startAutoEditJob({
      ctx: next, token: "visual-plan-saved-review", snapshots: 0,
      bootstrapPlanHash: saved.bootstrapPlanHash, reviewSavedPlan: true,
    });
    const persisted = readAutoEditJob(autoEditJobPath(fix.producer))!;
    assert.equal(persisted.ctx.pipeline?.digest, next.pipeline?.digest);
    assert.equal(persisted.ctx.visualPlanPipeline?.digest, fix.ctx.pipeline.digest);

    assert.throws(() => restoreProjectAutoEditPipeline(fix.producer, {
      ...fix.ctx.pipeline!, snapshotRoot: path.join(fix.root, "copied", "files"),
      lockPath: path.join(fix.root, "copied", "pipeline-lock.json"),
    }), /outside its controller-owned project run/);
  } finally {
    rmSync(fix.root, { recursive: true, force: true });
  }
}

main();
console.log("visual-plan snapshot authority tests passed");
