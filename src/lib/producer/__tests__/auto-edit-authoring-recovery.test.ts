import assert from "node:assert/strict";
import {
  existsSync, mkdirSync, mkdtempSync, readFileSync,
  rmSync, unlinkSync, writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { runAuthorStage, type AuthoringStageDependencies } from
  "../../../app/api/producer/auto-edit/authoring-stage";
import { cutApprovalPath, type CutApprovalReceipt } from
  "../../../app/api/producer/auto-edit/cut-approval";
import { runAutoEditPipeline, type PipelineRuntime } from
  "../../../app/api/producer/auto-edit/pipeline";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { planContentHash } from "../../server/auto-edit-authority";
import type { AutoEditAuthoritySnapshot } from "../../server/auto-edit-authority-snapshot";
import { freshJob } from "../../server/auto-edit-job-builders";
import { fileSha256 } from "../../server/auto-edit-job-store";
import { autoEditJobPath, writeJobUnlocked } from
  "../../server/auto-edit-job-persistence";
import type { AutoEditJob, CheckpointUpdate } from "../../server/auto-edit-job-types";
interface Harness {
  runtime: PipelineRuntime;
  events: Record<string, unknown>[];
}
function fixture(root: string): AutoEditCtx {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(planPath, JSON.stringify({ planVersion: 1, target: { mode: "longform" }, old: true }));
  writeFileSync(manifestPath, JSON.stringify({ sources: [] }));
  return {
    dir, planPath, manifestPath, transcriptsDir: source, scope: "produced",
    intent: { mode: "longform", lanes: {} },
  };
}
function authority(ctx: AutoEditCtx): AutoEditAuthoritySnapshot {
  const planHash = fileSha256(ctx.planPath) ?? null;
  const contentHash = planContentHash(ctx.planPath) ?? null;
  return {
    schemaVersion: 1,
    qualityPolicyVersion: 1,
    digest: `authority:${planHash}:${contentHash}`,
    planHash,
    planContentHash: contentHash,
    manifestHash: fileSha256(ctx.manifestPath) ?? null,
    operatorIntentDigest: "intent",
    transcriptDigest: "transcript",
    referenceDigest: "reference",
    pipelineDigest: "pipeline",
  };
}
function harness(ctx: AutoEditCtx, token: string): Harness {
  const events: Record<string, unknown>[] = [];
  const runtime = {} as PipelineRuntime;
  const update = (change: CheckpointUpdate): AutoEditJob => {
    runtime.job = { ...runtime.job, ...change, updatedAt: new Date().toISOString() };
    return runtime.job;
  };
  runtime.job = freshJob({ ctx, token, snapshots: 0 }, new Date().toISOString());
  writeJobUnlocked(autoEditJobPath(ctx.dir), runtime.job);
  runtime.io = { send: (event) => events.push(event), sendRaw: () => {}, advance: update, invalidate: update };
  return { runtime, events };
}
function timedOut(): Awaited<ReturnType<AuthoringStageDependencies["author"]>> {
  return {
    code: 1, timedOut: true, errTail: "Codex timed out after 1800s", ms: 1_800_000,
    provider: "codex", authored: null,
  };
}

function success(): Awaited<ReturnType<AuthoringStageDependencies["author"]>> {
  return { code: 0, timedOut: false, errTail: "", ms: 10,
    provider: "codex", authored: null };
}

function approval(): CutApprovalReceipt {
  return {
    schemaVersion: 1, stage: "previsual", planHash: "a".repeat(64),
    manifestHash: "b".repeat(64), transcriptDigest: "c".repeat(64),
    cutTrackDigest: "d".repeat(64), cutDecisionsDigest: "e".repeat(64),
    cuts: 1, seams: [], removals: [],
  };
}

function dependencies(
  author: AuthoringStageDependencies["author"],
  order: string[] = [],
): AuthoringStageDependencies {
  return {
    exists: (item) => fileSha256(item) !== undefined,
    hashFile: fileSha256, author, authority,
    validateCut: async () => {
      order.push("validate-cut-candidate");
      return approval();
    },
    validateSavedCut: async () => {
      order.push("validate-saved-cut-candidate"); return approval(); },
    reviewCut: async () => {
      order.push("review-cut");
      return {} as Awaited<ReturnType<AuthoringStageDependencies["reviewCut"]>>;
    },
    verifyReviewCut: () => {
      order.push("verify-review-cut");
      return {} as ReturnType<AuthoringStageDependencies["verifyReviewCut"]>;
    },
    approveCut: async (ctx) => {
      order.push("approve-cut");
      writeFileSync(cutApprovalPath(ctx), JSON.stringify(approval()));
      return approval();
    },
    approveSavedCut: async (ctx) => {
      order.push("approve-saved-cut");
      writeFileSync(cutApprovalPath(ctx), JSON.stringify(approval())); return approval(); },
    verifyCut: async () => {
      order.push("verify-cut");
      return {
        gate: "transcript_cut", ok: true, errors: [], warnings: [], exit: 0,
        metrics: { receipt: { ...approval(), stage: "planning_gate" } },
      };
    },
    lockCut: async () => {
      order.push("lock-cut");
      return {
        hash: "f".repeat(64), projectionHash: "e".repeat(64), reused: true,
        lock: { timelineMapHash: "d".repeat(64) },
      } as Awaited<ReturnType<AuthoringStageDependencies["lockCut"]>>;
    },
  };
}

async function testFreshDraftRecovers(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "fresh"));
  const { runtime, events } = harness(ctx, "fresh");
  const order: string[] = [];
  await runAuthorStage(runtime, dependencies(async (_ctx, _send, stage) => {
    order.push(`author-${stage}`);
    if (stage === "cut") {
      writeFileSync(ctx.planPath, JSON.stringify({
        planVersion: 2, target: { mode: "longform" }, cutTrack: [{ sourceId: "a" }],
      }));
      return timedOut();
    }
    const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
    writeFileSync(ctx.planPath, JSON.stringify({ ...plan, graphicsTrack: [{ id: "g1" }] }));
    return success();
  }, order));
  assert.equal(runtime.job.checkpoint, "plan_authored");
  assert.equal(runtime.job.phase, "planning_review");
  assert.equal(runtime.job.planHash, fileSha256(ctx.planPath));
  assert.ok(events.some((event) => event.event === "authoring_deadline_recovered"));
  assert.ok(events.some((event) =>
    event.event === "compatibility_picture_lock"
    && event.pictureLockHash === "f".repeat(64)));
  assert.deepEqual(order, [
    "author-cut", "review-cut", "approve-cut", "verify-cut", "verify-review-cut",
    "lock-cut", "author-visual", "verify-cut", "verify-review-cut", "lock-cut",
  ]);
}

async function testFreshPathRequiresReviewProof(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "fresh-review-proof"));
  const { runtime } = harness(ctx, "fresh-review-proof");
  const order: string[] = [];
  const stages: string[] = [];
  const deps = dependencies(async (_ctx, _send, stage) => {
    stages.push(stage);
    writeFileSync(ctx.planPath, JSON.stringify({
      planVersion: 2, target: { mode: "longform" }, cutTrack: [],
    }));
    return success();
  }, order);
  deps.verifyReviewCut = () => {
    order.push("verify-review-cut");
    throw new Error("clean review approval is not independently bound");
  };
  await assert.rejects(
    runAuthorStage(runtime, deps),
    /clean review approval is not independently bound/,
  );
  assert.deepEqual(stages, ["cut"], "visual authoring must stay blocked");
  assert.deepEqual(order.slice(-4), [
    "review-cut", "approve-cut", "verify-cut", "verify-review-cut",
  ]);
}

async function rejectsUnsafeDraft(
  root: string,
  name: string,
  mutate: (ctx: AutoEditCtx) => void,
): Promise<void> {
  const ctx = fixture(path.join(root, name));
  const { runtime, events } = harness(ctx, name);
  await assert.rejects(
    runAuthorStage(runtime, dependencies(async () => {
      mutate(ctx);
      return timedOut();
    })),
    /authoring timed out after 45 min/,
  );
  assert.equal(runtime.job.checkpoint, "authoring");
  assert.equal(events.some((event) => event.event === "authoring_deadline_recovered"), false);
}

async function testPipelineStillRequiresReview(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "pipeline"));
  const { runtime } = harness(ctx, "pipeline");
  let planningReached = false;
  await assert.rejects(runAutoEditPipeline(runtime, {
    exists: existsSync,
    hashFile: fileSha256,
    authority,
    author: async (_ctx, _send, stage) => {
      writeFileSync(ctx.planPath, JSON.stringify({
        planVersion: stage === "cut" ? 2 : 3,
        target: { mode: "longform" }, cutTrack: [],
        ...(stage === "visual" ? { graphicsTrack: [] } : {}),
      }));
      return stage === "cut" ? timedOut() : success();
    },
    approveCut: async () => {
      writeFileSync(cutApprovalPath(ctx), JSON.stringify(approval()));
      return approval();
    },
    verifyCut: async () => ({
      gate: "transcript_cut", ok: true, errors: [], warnings: [], exit: 0,
      metrics: { receipt: { ...approval(), stage: "planning_gate" } },
    }),
    reviewCut: async () => ({} as Awaited<ReturnType<AuthoringStageDependencies["reviewCut"]>>),
    verifyReviewCut: () => ({} as ReturnType<AuthoringStageDependencies["verifyReviewCut"]>),
    lockCut: async () => ({
      hash: "f".repeat(64), projectionHash: "e".repeat(64), reused: true,
      lock: { timelineMapHash: "d".repeat(64) },
    } as Awaited<ReturnType<AuthoringStageDependencies["lockCut"]>>),
    checkpoint: async () => ({ status: "committed" as const }),
    planning: async (run) => {
      planningReached = true;
      assert.equal(run.job.checkpoint, "plan_authored");
      throw new Error("formal planning review reached");
    },
  }), /formal planning review reached/);
  assert.equal(planningReached, true);
}

async function testResumeKeepsApprovedCut(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "resume-cut"));
  writeFileSync(cutApprovalPath(ctx), JSON.stringify(approval()));
  const { runtime } = harness(ctx, "resume-cut");
  const order: string[] = [];
  const stages: string[] = [];
  await runAuthorStage(runtime, dependencies(async (_ctx, _send, stage) => {
    stages.push(stage);
    assert.equal(stage, "visual");
    const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
    writeFileSync(ctx.planPath, JSON.stringify({ ...plan, graphicsTrack: [] }));
    return success();
  }, order));
  assert.deepEqual(stages, ["visual"]);
  // Verify the reused cut before visual authoring and again after it, without
  // repeating unchanged deterministic checks at the guided boundary.
  assert.deepEqual(order, [
    "verify-cut", "verify-review-cut", "lock-cut",
    "verify-cut", "verify-review-cut", "lock-cut",
  ]);
  assert.equal(runtime.job.checkpoint, "plan_authored");
}

async function testReviewedResumeSkipsBothWriters(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "resume-plan"));
  writeFileSync(cutApprovalPath(ctx), JSON.stringify(approval()));
  const { runtime, events } = harness(ctx, "resume-plan");
  runtime.job = { ...runtime.job, checkpoint: "plan_authored", phase: "planning_review" };
  const order: string[] = [];
  await runAuthorStage(runtime, dependencies(async () => {
    throw new Error("writer must not run");
  }, order));
  assert.deepEqual(order, ["verify-cut", "verify-review-cut", "lock-cut"]);
  assert.ok(events.some((event) => event.event === "resume"));
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-authoring-recovery-"));
  try {
    await testFreshDraftRecovers(root);
    await rejectsUnsafeDraft(root, "unchanged", () => {});
    await rejectsUnsafeDraft(root, "malformed", (ctx) => writeFileSync(ctx.planPath, "{broken"));
    await rejectsUnsafeDraft(root, "missing", (ctx) => unlinkSync(ctx.planPath));
    await testFreshPathRequiresReviewProof(root);
    await testPipelineStillRequiresReview(root);
    await testResumeKeepsApprovedCut(root);
    await testReviewedResumeSkipsBothWriters(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("auto-edit-authoring-recovery.test.ts: all assertions passed");
}

void main();
