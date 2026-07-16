import assert from "node:assert/strict";
import {
  existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  runCutReviewLoop,
  type CutReviewLoopDependencies,
  type CutReviewLoopRuntime,
} from "../../../app/api/producer/auto-edit/cut-review-loop";
import { cutReviewApprovalPath } from
  "../../../app/api/producer/auto-edit/cut-review-approval";
import type { CutApprovalReceipt } from
  "../../../app/api/producer/auto-edit/cut-approval";
import type { ProducerReview } from
  "../../../app/api/producer/auto-edit/review-contract";
import { RevisionNoChangeError } from
  "../../../app/api/producer/auto-edit/revision-staging";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import {
  autoEditAuthoritySnapshot,
  stableAuthorityHash,
  type AutoEditAuthoritySnapshot,
} from "../../server/auto-edit-authority-snapshot";
import { freshJob } from "../../server/auto-edit-job-builders";
import { fileSha256 } from "../../server/auto-edit-hash";
import type { CheckpointUpdate } from "../../server/auto-edit-job-types";
import { writeQualityJson } from "../../server/auto-edit-quality-artifacts";

function fixture(root: string): AutoEditCtx {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const transcriptPath = path.join(source, "raw-1.transcript.json");
  writeFileSync(transcriptPath, JSON.stringify({ transcript: [{
    start: 0, end: 4, text: "We can make this much clearer today.",
    words: [
      { word: "We", start: 0, end: 0.3 }, { word: "can", start: 0.3, end: 0.6 },
      { word: "make", start: 0.6, end: 1 }, { word: "this", start: 1, end: 1.3 },
      { word: "much", start: 1.3, end: 1.7 }, { word: "clearer", start: 1.7, end: 2.3 },
      { word: "today.", start: 2.3, end: 3 },
    ],
  }] }));
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(manifestPath, JSON.stringify({
    sources: [{ id: "raw-1", transcriptPath: path.basename(transcriptPath) }],
  }));
  const planPath = path.join(dir, "edit_plan.json");
  writeFileSync(planPath, JSON.stringify({
    planVersion: 1, target: { mode: "longform" },
    cutTrack: [{ sourceId: "raw-1", start: 0, end: 3, speed: 1, rationale: "Complete opening thought." }],
    cutDecisions: { schemaVersion: 1, removals: [] },
  }));
  return {
    dir, planPath, manifestPath, transcriptsDir: source, scope: "produced",
    intent: { mode: "longform", lanes: {} },
  };
}

function authority(ctx: AutoEditCtx): AutoEditAuthoritySnapshot {
  return autoEditAuthoritySnapshot(ctx);
}

function gate(ctx: AutoEditCtx): CutApprovalReceipt {
  const current = autoEditAuthoritySnapshot(ctx);
  const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
  return {
    schemaVersion: 1, stage: "previsual", planHash: current.planHash!,
    manifestHash: current.manifestHash!, transcriptDigest: current.transcriptDigest,
    cutTrackDigest: stableAuthorityHash(plan.cutTrack),
    cutDecisionsDigest: stableAuthorityHash(plan.cutDecisions),
    cuts: 1, seams: [], removals: [],
  };
}

function review(verdict: "pass" | "revise" | "block"): ProducerReview {
  const materialIssues = verdict === "pass" ? [] : [{
    code: "CUT_DUPLICATE_01", severity: "major" as const, lane: "cuts",
    message: "The opening repeats a phrase.", evidence: ["output 00:00.3"],
    requiredAction: "Remove the weaker repeated delivery.",
  }];
  return {
    schemaVersion: 1, stage: "cut", verdict,
    summary: verdict === "pass" ? "The cut is coherent." : "The cut needs repair.",
    materialIssues, findings: [],
  };
}

function runtime(ctx: AutoEditCtx): { run: CutReviewLoopRuntime; events: Record<string, unknown>[] } {
  const events: Record<string, unknown>[] = [];
  const run = {} as CutReviewLoopRuntime;
  run.job = freshJob({ ctx, token: "cut-loop", snapshots: 0 }, new Date().toISOString());
  run.io = {
    send: (event) => events.push(event),
    advance: (update: CheckpointUpdate) => {
      run.job = { ...run.job, ...update, updatedAt: new Date().toISOString() };
      return run.job;
    },
  };
  return { run, events };
}

function dependencies(
  verdicts: Array<"pass" | "revise" | "block">,
  counters: { gates: number; reviews: number; revisions: number },
): Partial<CutReviewLoopDependencies> {
  return {
    authority,
    gate: async (ctx) => { counters.gates += 1; return gate(ctx); },
    review: async () => {
      const verdict = verdicts[counters.reviews] ?? "pass";
      counters.reviews += 1;
      return { provider: "codex", ms: 5, review: review(verdict) };
    },
    revise: async (ctx, critique) => {
      counters.revisions += 1;
      const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
      writeFileSync(ctx.planPath, JSON.stringify({ ...plan, planVersion: plan.planVersion + 1 }));
      return {
        provider: "codex", ms: 6,
        receipt: {
          schemaVersion: 1, changedPlan: true,
          addressedIssueCodes: critique.materialIssues.map((item) => item.code),
          deferredIssueCodes: [], summary: "Repaired the transcript cut.",
        },
      };
    },
    hash: fileSha256,
    writeJson: writeQualityJson,
    snapshot: () => 1,
  };
}

async function passesTwice(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "pass"));
  const { run, events } = runtime(ctx);
  const counts = { gates: 0, reviews: 0, revisions: 0 };
  const receipt = await runCutReviewLoop(run, dependencies(["pass", "pass"], counts));
  assert.deepEqual(counts, { gates: 1, reviews: 2, revisions: 0 });
  assert.equal(receipt.reviews.length, 2);
  assert.ok(existsSync(cutReviewApprovalPath(ctx)));
  assert.match(run.job.message, /2\/2 clean independent reviews/);
  assert.equal(events.filter((event) => event.event === "cut_review_completed").length, 2);
}

async function revisesThenPasses(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "revise"));
  const { run } = runtime(ctx);
  const counts = { gates: 0, reviews: 0, revisions: 0 };
  const receipt = await runCutReviewLoop(
    run, dependencies(["revise", "pass", "pass"], counts),
  );
  assert.deepEqual(counts, { gates: 2, reviews: 4, revisions: 1 });
  assert.deepEqual(receipt.reviews.map((item) => item.round), [3, 4]);
  assert.equal(JSON.parse(readFileSync(ctx.planPath, "utf8")).planVersion, 2);
}

async function blocksBeforeApproval(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "block"));
  const { run } = runtime(ctx);
  const counts = { gates: 0, reviews: 0, revisions: 0 };
  await assert.rejects(
    runCutReviewLoop(run, dependencies(["block"], counts)),
    /cut critic blocked visual planning/,
  );
  assert.equal(existsSync(cutReviewApprovalPath(ctx)), false);
  assert.deepEqual(counts, { gates: 1, reviews: 2, revisions: 0 });
}

async function noChangeGetsOneFreshReview(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "no-change"));
  const { run, events } = runtime(ctx);
  const counts = { gates: 0, reviews: 0, revisions: 0 };
  const deps = dependencies(["revise", "pass", "pass"], counts);
  deps.revise = async () => {
    counts.revisions += 1;
    throw new RevisionNoChangeError();
  };
  const receipt = await runCutReviewLoop(run, deps);
  assert.deepEqual(receipt.reviews.map((item) => item.round), [3, 4]);
  assert.deepEqual(counts, { gates: 2, reviews: 4, revisions: 1 });
  assert.equal(events.filter((event) => event.event === "cut_revision_conflict").length, 1);
}

async function deferredGetsOneFreshReview(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "deferred"));
  const { run, events } = runtime(ctx);
  const counts = { gates: 0, reviews: 0, revisions: 0 };
  const deps = dependencies(["revise", "pass", "pass"], counts);
  deps.revise = async (_ctx, critique) => {
    counts.revisions += 1;
    return {
      provider: "codex", ms: 6,
      receipt: {
        schemaVersion: 1, changedPlan: false, addressedIssueCodes: [],
        deferredIssueCodes: critique.materialIssues.map((item) => item.code),
        summary: "Critique conflicts with deterministic evidence.",
      },
    };
  };
  await runCutReviewLoop(run, deps);
  assert.deepEqual(counts, { gates: 2, reviews: 4, revisions: 1 });
  assert.equal(events.find((event) => event.event === "cut_revision_conflict")?.reason,
    "writer_deferred");
}

async function repeatedConflictFailsExplicitly(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "repeated-conflict"));
  const { run } = runtime(ctx);
  const counts = { gates: 0, reviews: 0, revisions: 0 };
  const deps = dependencies(["revise", "revise", "revise", "revise"], counts);
  deps.revise = async () => {
    counts.revisions += 1;
    throw new RevisionNoChangeError();
  };
  await assert.rejects(runCutReviewLoop(run, deps),
    /cut critic\/revision conflict repeated for unchanged deterministic cut/);
  assert.deepEqual(counts, { gates: 2, reviews: 4, revisions: 1 });
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-cut-review-loop-"));
  try {
    await passesTwice(root);
    await revisesThenPasses(root);
    await blocksBeforeApproval(root);
    await noChangeGetsOneFreshReview(root);
    await deferredGetsOneFreshReview(root);
    await repeatedConflictFailsExplicitly(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("cut-review-loop.test.ts: all assertions passed");
}

void main();
