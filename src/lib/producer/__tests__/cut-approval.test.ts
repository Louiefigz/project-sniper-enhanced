import assert from "node:assert/strict";
import {
  existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  approvePrevisualCut,
  approveSavedPlanCut,
  cutAuthorityEvidence,
  cutApprovalPath,
  validatePrevisualCut,
  validateSavedPlanCut,
  verifyApprovedCut,
} from "../../../app/api/producer/auto-edit/cut-approval";
import {
  runAuthorStage,
  type AuthoringStageDependencies,
} from "../../../app/api/producer/auto-edit/authoring-stage";
import { runCutReviewLoop } from
  "../../../app/api/producer/auto-edit/cut-review-loop";
import { verifyCutReviewApproval } from
  "../../../app/api/producer/auto-edit/cut-review-approval";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { autoEditAuthoritySnapshot } from "../../server/auto-edit-authority-snapshot";
import { freshJob } from "../../server/auto-edit-job-builders";
import { fileSha256 } from "../../server/auto-edit-hash";
import type { AutoEditJob, CheckpointUpdate } from "../../server/auto-edit-job-types";

interface StageHarness {
  runtime: {
    job: AutoEditJob;
    io: {
      send: (event: Record<string, unknown>) => void;
      advance: (update: CheckpointUpdate) => AutoEditJob;
      invalidate: (update: CheckpointUpdate) => AutoEditJob;
    };
  };
  events: Record<string, unknown>[];
}

function fixture(root: string): AutoEditCtx {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(path.join(source, "raw.transcript.json"), JSON.stringify({
    transcript: [{
      start: 0.2, end: 2.9, text: "Hello world um Restart now", words: [
      { word: "Hello", start: 0.2, end: 0.5 },
      { word: "world", start: 0.6, end: 1.0 },
      { word: "um", start: 1.5, end: 1.7 },
      { word: "Restart", start: 2.2, end: 2.5 },
      { word: "now", start: 2.6, end: 2.9 },
    ] }],
  }));
  writeFileSync(manifestPath, JSON.stringify({ sources: [{
    id: "raw-1", duration: 4, transcriptPath: "raw.transcript.json",
  }] }));
  writeFileSync(planPath, JSON.stringify({
    planVersion: 1,
    target: { mode: "longform", scope: "produced" },
    cutTrack: [
      { sourceId: "raw-1", start: 0, end: 1.1, speed: 1,
        rationale: "Keep the complete opening statement." },
      { sourceId: "raw-1", start: 2.1, end: 3.0, speed: 1,
        rationale: "Keep the clean restarted statement." },
    ],
    cutDecisions: { schemaVersion: 1, removals: [{
      sourceId: "raw-1", start: 1.1, end: 2.1, kind: "filler",
      rationale: "Remove the abandoned filler restart.",
      evidence: { beforeWord: "world", afterWord: "Restart", removedText: "um" },
    }] },
  }));
  return {
    dir, planPath, manifestPath, transcriptsDir: source, scope: "produced",
    intent: { mode: "longform", lanes: {} },
  };
}

async function savedPlanPreservesExactBytes(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "saved-plan"));
  const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
  Object.assign(plan, {
    audioEnhance: { preset: "voice-strong" },
    captions: { burn: true, style: "karaoke" },
    titleCards: [{ text: "EXACT TITLE", outStart: 0, outEnd: 1 }],
    graphicsTrack: [{
      id: "g1", kind: "text-element", anchor: "free-band",
      outStart: 0.2, outEnd: 1, reason: "Populate a real downstream visual lane.",
      spec: { text: "HELLO", fontSize: 42 },
    }],
  });
  writeFileSync(ctx.planPath, `${JSON.stringify(plan, null, 2)}\n`);
  const before = readFileSync(ctx.planPath);
  const beforeHash = fileSha256(ctx.planPath);
  await assert.rejects(approvePrevisualCut(ctx), /populated downstream fields/);
  const receipt = await approveSavedPlanCut(ctx);
  assert.equal(receipt.planHash, beforeHash);
  assert.deepEqual(readFileSync(ctx.planPath), before,
    "saved-plan cut approval must not rewrite complete plan bytes");
  assert.equal((await verifyApprovedCut(ctx)).ok, true);

  plan.cutTrack[1].start = 2.3;
  plan.cutDecisions.removals[0].end = 2.3;
  writeFileSync(ctx.planPath, `${JSON.stringify(plan, null, 2)}\n`);
  const badBytes = readFileSync(ctx.planPath);
  await assert.rejects(approveSavedPlanCut(ctx), /cuts through word/);
  assert.deepEqual(readFileSync(ctx.planPath), badBytes,
    "a rejected saved-plan cut must remain untouched, not be laundered");
}

function stageHarness(ctx: AutoEditCtx): StageHarness {
  const events: Record<string, unknown>[] = [];
  const runtime = {} as StageHarness["runtime"];
  runtime.job = freshJob({
    ctx, token: "saved-plan-stage", snapshots: 0,
    bootstrapPlanHash: fileSha256(ctx.planPath), reviewSavedPlan: true,
  }, new Date().toISOString());
  const update = (value: CheckpointUpdate) => {
    runtime.job = { ...runtime.job, ...value };
    return runtime.job;
  };
  runtime.io = { send: (event) => events.push(event), advance: update, invalidate: update };
  return { runtime, events };
}

function stageDependencies(): AuthoringStageDependencies {
  return {
    exists: existsSync, hashFile: fileSha256,
    authority: autoEditAuthoritySnapshot,
    validateCut: validatePrevisualCut, validateSavedCut: validateSavedPlanCut,
    approveCut: approvePrevisualCut, approveSavedCut: approveSavedPlanCut,
    verifyCut: verifyApprovedCut,
    author: async () => { throw new Error("saved-plan writers must not run"); },
    reviewCut: (run) => runCutReviewLoop(run, {
      review: async () => ({
        provider: "codex", ms: 1,
        review: {
          schemaVersion: 1, stage: "cut", verdict: "pass",
          summary: "The saved transcript cut is coherent.",
          materialIssues: [], findings: [],
        },
      }),
    }),
    verifyReviewCut: verifyCutReviewApproval,
    lockCut: async () => ({
      hash: "a".repeat(64), projectionHash: "b".repeat(64), reused: false,
      lock: { timelineMapHash: "c".repeat(64) },
    } as Awaited<ReturnType<AuthoringStageDependencies["lockCut"]>>),
  };
}

async function savedPlanReviewSkipsWriters(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "saved-plan-stage"));
  const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
  plan.graphicsTrack = [{ id: "g1", kind: "text-element", outStart: 0, outEnd: 1 }];
  plan.captions = { burn: true, style: "karaoke" };
  writeFileSync(ctx.planPath, `${JSON.stringify(plan, null, 2)}\n`);
  const before = readFileSync(ctx.planPath);
  const beforeHash = fileSha256(ctx.planPath);
  const { runtime, events } = stageHarness(ctx);
  await runAuthorStage(runtime, stageDependencies());
  assert.deepEqual(readFileSync(ctx.planPath), before);
  assert.equal(fileSha256(ctx.planPath), beforeHash);
  assert.equal(runtime.job.checkpoint, "plan_authored");
  assert.ok(events.some((event) =>
    event.event === "resume" && event.stage === "visual"));
}

async function interruptedSavedPlanReviewSkipsWriters(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "saved-plan-resume"));
  const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
  plan.graphicsTrack = [{ id: "g1", kind: "text-element", outStart: 0, outEnd: 1 }];
  plan.captions = { burn: true, style: "karaoke" };
  writeFileSync(ctx.planPath, `${JSON.stringify(plan, null, 2)}\n`);
  const before = readFileSync(ctx.planPath);
  const beforeHash = fileSha256(ctx.planPath);
  const { runtime } = stageHarness(ctx);
  runtime.job = {
    ...runtime.job, checkpoint: "authoring", phase: "authoring", attempts: 2,
  };
  await runAuthorStage(runtime, stageDependencies());
  assert.deepEqual(readFileSync(ctx.planPath), before);
  assert.equal(fileSha256(ctx.planPath), beforeHash);
  assert.equal(runtime.job.checkpoint, "plan_authored");
}

async function badSavedPlanFailsWithoutWriters(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "bad-saved-plan-stage"));
  const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
  plan.graphicsTrack = [{ id: "g1", kind: "text-element", outStart: 0, outEnd: 1 }];
  plan.captions = { burn: true, style: "karaoke" };
  plan.cutTrack[1].start = 2.3;
  plan.cutDecisions.removals[0].end = 2.3;
  writeFileSync(ctx.planPath, `${JSON.stringify(plan, null, 2)}\n`);
  const before = readFileSync(ctx.planPath);
  const beforeHash = fileSha256(ctx.planPath);
  const { runtime } = stageHarness(ctx);
  await assert.rejects(
    runAuthorStage(runtime, stageDependencies()),
    /cuts through word/,
  );
  assert.deepEqual(readFileSync(ctx.planPath), before);
  assert.equal(fileSha256(ctx.planPath), beforeHash);
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-cut-approval-"));
  try {
    const ctx = fixture(root);
    const receipt = await approvePrevisualCut(ctx);
    assert.equal(receipt.stage, "previsual");
    assert.equal(JSON.parse(readFileSync(cutApprovalPath(ctx), "utf8")).cutTrackDigest,
      receipt.cutTrackDigest);
    assert.match(receipt.cutDecisionsDigest, /^[a-f0-9]{64}$/);
    const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
    plan.graphicsTrack = [{ id: "g1", outStart: 0, outEnd: 2 }];
    writeFileSync(ctx.planPath, JSON.stringify(plan));
    const approved = await verifyApprovedCut(ctx);
    assert.equal(approved.ok, true);
    assert.equal(cutAuthorityEvidence(approved).cutTrackDigest, receipt.cutTrackDigest);
    const originalRationale = plan.cutDecisions.removals[0].rationale;
    plan.cutDecisions.removals[0].rationale = `${originalRationale} Changed.`;
    writeFileSync(ctx.planPath, JSON.stringify(plan));
    await assert.rejects(verifyApprovedCut(ctx), /cutDecisionsDigest changed/);
    plan.cutDecisions.removals[0].rationale = originalRationale;
    plan.cutTrack[1].start = 2.15;
    plan.cutDecisions.removals[0].end = 2.15;
    writeFileSync(ctx.planPath, JSON.stringify(plan));
    await assert.rejects(verifyApprovedCut(ctx), /cutTrackDigest changed/);
    await savedPlanPreservesExactBytes(root);
    await savedPlanReviewSkipsWriters(root);
    await interruptedSavedPlanReviewSkipsWriters(root);
    await badSavedPlanFailsWithoutWriters(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("cut-approval.test.ts: all assertions passed");
}

void main();
