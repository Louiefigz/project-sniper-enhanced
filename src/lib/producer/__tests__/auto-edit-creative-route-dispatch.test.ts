import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync,
  writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { dispatchAutoEditCreativeRoute } from
  "@/app/api/producer/auto-edit/creative-route-dispatch";
import { prepareVisualPlanContext } from
  "@/app/api/producer/auto-edit/visual-plan-context";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { advanceAutoEditJob, autoEditJobPath, pauseAutoEditForNativeAuthor,
  readAutoEditJob, startAutoEditJob } from "@/lib/server/auto-edit-job-store";
import { fileSha256 } from "@/lib/server/auto-edit-hash";
import { runAutoEditPipeline } from
  "@/app/api/producer/auto-edit/pipeline";
import { dependencies as pipelineDependencies, fixture as pipelineFixture,
  runtime as pipelineRuntime } from "./_auto-edit-pipeline-resume-fixture";
import { writeAdmittedMediaManifest } from "./_visual-plan-media-manifest-fixture";

function routeFixture(root: string, mode: "short" | "longform"): AutoEditCtx {
  const dir = path.join(root, "producer"), source = path.join(root, "source");
  mkdirSync(dir, { recursive: true }); mkdirSync(source, { recursive: true });
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(planPath, JSON.stringify({ planVersion: 1,
    target: { mode, scope: "produced" }, cutTrack: [{ sourceId: "source:one",
      start: 0, end: 1, speed: 1 }], cutDecisions: { schemaVersion: 1, removals: [] } }));
  writeFileSync(path.join(source, "transcript.json"), JSON.stringify({ transcript: [{
    start: 0, end: 1, text: "Hello world", words: [
      { word: "Hello", start: 0, end: 0.4 }, { word: "world", start: 0.5, end: 0.9 }],
  }] }));
  const mediaPath = path.join(source, "source.mp4");
  writeFileSync(mediaPath, "TEST source metadata authority bytes");
  writeAdmittedMediaManifest(manifestPath, { sources: [{ id: "source:one",
    path: mediaPath, transcriptPath: "transcript.json" }] });
  return { dir, scope: "produced", intent: { mode, lanes: {} }, planPath,
    manifestPath, transcriptsDir: source, visualPlanRequiredVersion: 1 };
}

function writeAllocatedPlan(ctx: AutoEditCtx, routeClass: "native" | "compatibility"): void {
  prepareVisualPlanContext(ctx);
  const context = path.join(ctx.dir, "VISUAL-PLAN-CONTEXT.json");
  const output = path.join(ctx.dir, "VISUAL-PLAN.json");
  const code = [
    "import json,os,sys",
    "from tests._visual_plan_fixture import candidate,materialize_plan_pins,opportunity,reseal_plan_receipts,reseal_search_authority,visual_plan",
    "from planner.visual_plan_allocator import allocate_visual_plan",
    "ctx=json.load(open(sys.argv[1])); root=os.path.join(os.path.dirname(sys.argv[2]),'route-pins')",
    `row=candidate('candidate:one',modality='source-footage',routeClass='${routeClass}')`,
    "media=json.load(open(ctx['mediaAuthority']['path']))['inventory'][0]",
    "row['source']={'recordId':media['recordId'],'path':media['path'],'sha256':media['sourceSha256'],'sourceSha256':media['sourceSha256']}",
    "word=json.load(open(ctx['transcriptAuthority']['path']))['words'][0]",
    "opp=opportunity('opp:one',0,[row]); opp['transcriptEvidence']={'text':word['text'],'wordIds':[word['id']]}",
    "value=materialize_plan_pins(visual_plan(opp),root)",
    "value['project']=ctx['project']; value['catalogPin']=ctx['catalogPin']",
    "value['transcriptAuthority']=ctx['transcriptAuthority']",
    "value['mediaAuthority']=ctx['mediaAuthority']",
    "value['opportunities'][0]['candidates'][0]['source']={'recordId':media['recordId'],'path':media['path'],'sha256':media['sourceSha256'],'sourceSha256':media['sourceSha256']}",
    "value['relatedUsageAuthority']=ctx['relatedUsageAuthority']; value['relatedUsage']=ctx['relatedUsage']",
    "value=reseal_search_authority(value)",
    "value=reseal_plan_receipts(value)",
    "open(sys.argv[2],'w').write(json.dumps(allocate_visual_plan(value)))",
  ].join("\n");
  execFileSync(pythonInterpreter(), ["-B", "-c", code, context, output], {
    cwd: path.join(process.cwd(), "scripts/producer"),
    env: { ...process.env, PYTHONPATH: ".", PYTHONDONTWRITEBYTECODE: "1" },
  });
}

function fakePreparation(root: string, route: "native-short" | "native-long") {
  const directory = path.join(root, `${route}-request`);
  mkdirSync(directory, { recursive: true });
  const request = path.join(directory,
    route === "native-short" ? "SHORT-REQUEST.json" : "LONG-REQUEST.json");
  writeFileSync(request, JSON.stringify({ schemaVersion: 1, route }));
  const projectDirectory = path.join(directory, "project");
  if (route === "native-long") mkdirSync(projectDirectory, { recursive: true });
  return { directory, requestHash: fileSha256(request)!,
    ...(route === "native-long" ? { projectDirectory } : {}) };
}

function dependencies(root: string) {
  return { repoRoot: () => root,
    prepareShort: () => fakePreparation(root, "native-short") as never,
    prepareLong: () => fakePreparation(root, "native-long") as never };
}

test("ordinary allocation continues without creating a native handoff", () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "route-ordinary-")));
  try {
    const ctx = routeFixture(root, "short"); writeAllocatedPlan(ctx, "compatibility");
    let called = false;
    const outcome = dispatchAutoEditCreativeRoute(ctx, {
      ...dependencies(root), prepareShort: (() => { called = true; }) as never });
    assert.deepEqual(outcome, { status: "ordinary", route: "ordinary" });
    assert.equal(called, false);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

for (const item of [
  { mode: "short", route: "native-short" },
  { mode: "longform", route: "native-long" },
] as const) test(`${item.route} persists one resumable controller handoff`, () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), `${item.route}-`)));
  try {
    const ctx = routeFixture(root, item.mode); writeAllocatedPlan(ctx, "native");
    const first = dispatchAutoEditCreativeRoute(ctx, dependencies(root));
    assert.equal(first.status, "awaiting_native_author");
    if (first.status !== "awaiting_native_author") return;
    assert.equal(first.route, item.route);
    assert.deepEqual(dispatchAutoEditCreativeRoute(ctx, dependencies(root)), first);
    const token = `${item.route}-token`;
    startAutoEditJob({ ctx, token, snapshots: 0 });
    advanceAutoEditJob(autoEditJobPath(ctx.dir), token, { checkpoint: "route_dispatched",
      phase: "planning_review", message: "waiting", nativeHandoff: first.handoff });
    pauseAutoEditForNativeAuthor(autoEditJobPath(ctx.dir), token);
    const saved = readAutoEditJob(autoEditJobPath(ctx.dir));
    assert.equal(saved?.status, "awaiting_native_author");
    assert.deepEqual(saved?.nativeHandoff, first.handoff);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("a modified native handoff cannot be regenerated or downgraded", () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "route-tamper-")));
  try {
    const ctx = routeFixture(root, "short"); writeAllocatedPlan(ctx, "native");
    const first = dispatchAutoEditCreativeRoute(ctx, dependencies(root));
    assert.equal(first.status, "awaiting_native_author");
    if (first.status !== "awaiting_native_author") return;
    const value = JSON.parse(readFileSync(first.handoff.path, "utf8"));
    value.route = "ordinary"; writeFileSync(first.handoff.path, JSON.stringify(value));
    assert.throws(() => dispatchAutoEditCreativeRoute(ctx, dependencies(root)),
      /handoff changed/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("pipeline stops native allocation before any renderer selection", async () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "route-pipeline-")));
  try {
    const ctx = pipelineFixture(root);
    ctx.scope = "produced"; ctx.visualPlanRequiredVersion = 1;
    const token = "native-route-pipeline";
    const job = startAutoEditJob({ ctx, token, snapshots: 0,
      bootstrapPlanHash: fileSha256(ctx.planPath) });
    const counts = { author: 0, planning: 0, assemble: 0, quality: 0 };
    const deps = pipelineDependencies(counts);
    let rendererSelections = 0;
    deps.palmierPrimary = async () => { rendererSelections += 1; return true; };
    deps.dispatchRoute = (() => ({ status: "awaiting_native_author",
      route: "native-short", handoff: { schemaVersion: 1,
        status: "awaiting-native-author", route: "native-short",
        path: path.join(ctx.dir, "NATIVE-AUTHOR-HANDOFF.json"), sha256: "a".repeat(64),
        requestPath: path.join(ctx.dir, "SHORT-REQUEST.json"),
        requestSha256: "b".repeat(64), requestDirectory: ctx.dir,
        visualPlan: { schemaVersion: 1, path: path.join(ctx.dir, "VISUAL-PLAN.json"),
          byteHash: "c".repeat(64), visualPlanSha256: "d".repeat(64),
          pictureInputSha256: "e".repeat(64), catalogPinSha256: "f".repeat(64),
          upstreamAuthoritySha256: "1".repeat(64) } } })) as never;
    const result = await runAutoEditPipeline(pipelineRuntime(job, []), deps);
    assert.equal(result.status, "awaiting_native_author");
    assert.equal(rendererSelections, 0);
    assert.deepEqual(counts, { author: 0, planning: 0, assemble: 0, quality: 0 });
  } finally { rmSync(root, { recursive: true, force: true }); }
});
