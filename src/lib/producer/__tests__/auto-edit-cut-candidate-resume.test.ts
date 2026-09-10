import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  runAuthorStage,
  type AuthoringStageDependencies,
} from "../../../app/api/producer/auto-edit/authoring-stage";
import { cutApprovalPath, type CutApprovalReceipt } from
  "../../../app/api/producer/auto-edit/cut-approval";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { planContentHash } from "../../server/auto-edit-authority";
import type { AutoEditAuthoritySnapshot } from "../../server/auto-edit-authority-snapshot";
import { freshJob, resumedJob } from "../../server/auto-edit-job-builders";
import { fileSha256 } from "../../server/auto-edit-job-store";
import type { AutoEditJob, CheckpointUpdate } from "../../server/auto-edit-job-types";

function fixture(root: string): AutoEditCtx {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(planPath, JSON.stringify({
    planVersion: 1, target: { mode: "longform" }, cutTrack: [{ sourceId: "a" }],
  }));
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
    schemaVersion: 1, qualityPolicyVersion: 1,
    digest: `authority:${planHash}:${contentHash}`,
    planHash, planContentHash: contentHash,
    manifestHash: fileSha256(ctx.manifestPath) ?? null,
    operatorIntentDigest: "intent", transcriptDigest: "transcript",
    referenceDigest: "reference", pipelineDigest: "pipeline",
  };
}

function approval(): CutApprovalReceipt {
  return {
    schemaVersion: 1, stage: "previsual", planHash: "a".repeat(64),
    manifestHash: "b".repeat(64), transcriptDigest: "c".repeat(64),
    cutTrackDigest: "d".repeat(64), cutDecisionsDigest: "e".repeat(64),
    cuts: 1, seams: [], removals: [],
  };
}

function runtime(ctx: AutoEditCtx, attempts = 2): {
  run: Parameters<typeof runAuthorStage>[0]; events: Record<string, unknown>[];
} {
  const events: Record<string, unknown>[] = [];
  const initial = freshJob({ ctx, token: "initial", snapshots: 0 }, new Date().toISOString());
  const job = attempts > 1
    ? resumedJob(
      { ctx, token: "resume", snapshots: 0, resume: initial },
      { ...initial, status: "failed" },
      new Date().toISOString(),
    )
    : initial;
  const run = { job } as
    Parameters<typeof runAuthorStage>[0];
  const update = (change: CheckpointUpdate): AutoEditJob => {
    run.job = { ...run.job, ...change, updatedAt: new Date().toISOString() };
    return run.job;
  };
  run.io = {
    send: (event) => events.push(event), advance: update, invalidate: update,
  };
  return { run, events };
}

function dependencies(order: string[]): AuthoringStageDependencies {
  return {
    exists: (item) => fileSha256(item) !== undefined,
    hashFile: fileSha256, authority,
    author: async (ctx, _send, stage) => {
      order.push(`author-${stage}`);
      const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
      writeFileSync(ctx.planPath, JSON.stringify({
        ...plan, planVersion: plan.planVersion + 1,
        ...(stage === "cut" ? { cutTrack: [{ sourceId: "rewritten" }] } : { graphicsTrack: [] }),
      }));
      return { code: 0, timedOut: false, errTail: "", ms: 1, provider: "codex", authored: null };
    },
    validateCut: async () => {
      order.push("validate-cut-candidate");
      return approval();
    },
    validateSavedCut: async () => approval(),
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
    approveSavedCut: async () => approval(),
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

async function testValidatedCandidateSkipsCutWriter(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "valid"));
  const { run, events } = runtime(ctx);
  const order: string[] = [];
  await runAuthorStage(run, dependencies(order));
  assert.deepEqual(order, [
    "validate-cut-candidate", "review-cut", "approve-cut", "verify-cut", "verify-review-cut",
    "lock-cut", "author-visual", "verify-cut", "verify-review-cut", "lock-cut",
  ]);
  assert.ok(events.some((event) => event.event === "cut_candidate_reused"));
}

async function testFirstAttemptStillAuthorsCut(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "first-attempt"));
  const { run } = runtime(ctx, 1);
  const order: string[] = [];
  await runAuthorStage(run, dependencies(order));
  assert.deepEqual(order.slice(0, 2), ["author-cut", "review-cut"]);
  assert.equal(order.includes("validate-cut-candidate"), false);
}

async function testInvalidCandidateFallsBack(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "invalid"));
  const { run, events } = runtime(ctx);
  const order: string[] = [];
  const deps = dependencies(order);
  deps.validateCut = async () => {
    order.push("validate-cut-candidate");
    throw new Error("saved cut is partial");
  };
  await runAuthorStage(run, deps);
  assert.deepEqual(order.slice(0, 4), [
    "validate-cut-candidate", "author-cut", "review-cut", "approve-cut",
  ]);
  assert.ok(events.some((event) => event.event === "cut_candidate_rejected"));
}

async function testCriticFailurePropagates(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "critic-failure"));
  const { run } = runtime(ctx);
  const order: string[] = [];
  const deps = dependencies(order);
  deps.reviewCut = async () => {
    order.push("review-cut");
    throw new Error("independent critic failed");
  };
  await assert.rejects(runAuthorStage(run, deps), /independent critic failed/);
  assert.deepEqual(order, ["validate-cut-candidate", "review-cut"]);
}

async function testAuthorityChangeFallsBack(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "authority-change"));
  const { run, events } = runtime(ctx);
  const order: string[] = [];
  const deps = dependencies(order);
  deps.validateCut = async () => {
    order.push("validate-cut-candidate");
    const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
    writeFileSync(ctx.planPath, JSON.stringify({ ...plan, changedDuringGate: true }));
    return approval();
  };
  await runAuthorStage(run, deps);
  assert.deepEqual(order.slice(0, 2), ["validate-cut-candidate", "author-cut"]);
  assert.ok(events.some((event) => event.event === "cut_candidate_rejected"));
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-cut-resume-"));
  try {
    await testValidatedCandidateSkipsCutWriter(root);
    await testFirstAttemptStillAuthorsCut(root);
    await testInvalidCandidateFallsBack(root);
    await testCriticFailurePropagates(root);
    await testAuthorityChangeFallsBack(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("auto-edit-cut-candidate-resume.test.ts: all assertions passed");
}

void main();
