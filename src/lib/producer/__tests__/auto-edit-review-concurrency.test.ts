import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  runCutReviewLoop,
  type CutReviewLoopDependencies,
  type CutReviewLoopRuntime,
} from "../../../app/api/producer/auto-edit/cut-review-loop";
import type { CutApprovalReceipt } from "../../../app/api/producer/auto-edit/cut-approval";
import {
  runPlanningReviewLoop,
  type PlanningLoopDependencies,
  type PlanningLoopRuntime,
} from "../../../app/api/producer/auto-edit/planning-loop";
import type { GateBundleVerdict } from "../../../app/api/producer/auto-edit/planning-gates";
import type { ProducerMaterialIssue, ProducerReview } from
  "../../../app/api/producer/auto-edit/review-contract";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { autoEditAuthoritySnapshot, stableAuthorityHash } from
  "../../server/auto-edit-authority-snapshot";
import { freshJob } from "../../server/auto-edit-job-builders";
import type { CheckpointUpdate } from "../../server/auto-edit-job-types";

const PASS_GATES: GateBundleVerdict = {
  ok: true, errors: [], warnings: [],
  gates: {
    operatorIntent: { gate: "operator_intent", ok: true, errors: [], warnings: [], exit: 0 },
    transcriptCut: { gate: "transcript_cut", ok: true, errors: [], warnings: [], exit: 0 },
    planLint: { gate: "plan_lint", ok: true, errors: [], warnings: [], exit: 0 },
    hookContract: { gate: "hook_contract", ok: true, errors: [], warnings: [], exit: 0 },
    templateUsage: { gate: "template_usage", ok: true, errors: [], warnings: [], exit: 0 },
    claimsContract: { gate: "claims_contract", ok: true, errors: [], warnings: [], exit: 0 },
    referenceLint: null,
  },
};

function fixture(root: string): AutoEditCtx {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const transcriptPath = path.join(source, "raw.transcript.json");
  writeFileSync(transcriptPath, JSON.stringify({ transcript: [{
    start: 0, end: 3, text: "A complete opening thought.",
    words: [{ word: "A", start: 0, end: 0.2 }, { word: "complete", start: 0.2, end: 0.8 }],
  }] }));
  const manifestPath = path.join(source, "manifest.json");
  writeFileSync(manifestPath, JSON.stringify({
    sources: [{ id: "raw", transcriptPath: path.basename(transcriptPath) }],
  }));
  const planPath = path.join(dir, "edit_plan.json");
  writeFileSync(planPath, JSON.stringify({
    planVersion: 1, target: { mode: "longform" },
    cutTrack: [{ sourceId: "raw", start: 0, end: 2 }],
    cutDecisions: { schemaVersion: 1, removals: [] },
  }));
  return {
    dir, planPath, manifestPath, transcriptsDir: source, scope: "produced",
    intent: { mode: "longform", lanes: {} },
    templateUsage: {
      schemaVersion: 1, path: path.join(dir, "template-usage.json"), digest: "a".repeat(64),
    },
  };
}

function cutGate(ctx: AutoEditCtx): CutApprovalReceipt {
  const authority = autoEditAuthoritySnapshot(ctx);
  const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
  return {
    schemaVersion: 1, stage: "previsual", planHash: authority.planHash!,
    manifestHash: authority.manifestHash!, transcriptDigest: authority.transcriptDigest,
    cutTrackDigest: stableAuthorityHash(plan.cutTrack),
    cutDecisionsDigest: stableAuthorityHash(plan.cutDecisions),
    cuts: 1, seams: [], removals: [],
  };
}

function pass(stage: "cut" | "plan"): ProducerReview {
  return {
    schemaVersion: 1, stage, verdict: "pass", summary: "clean",
    materialIssues: [], findings: [],
  };
}

function revise(stage: "cut" | "plan", issues: ProducerMaterialIssue[]): ProducerReview {
  return {
    schemaVersion: 1, stage, verdict: "revise", summary: "repair these issues",
    materialIssues: issues, findings: [],
  };
}

function barrier(size: number): { enter: () => Promise<void>; max: () => number } {
  let arrived = 0;
  let active = 0;
  let maximum = 0;
  let release!: () => void;
  const ready = new Promise<void>((resolve) => { release = resolve; });
  return {
    enter: async () => {
      arrived += 1;
      active += 1;
      maximum = Math.max(maximum, active);
      if (arrived === size) release();
      await ready;
      active -= 1;
    },
    max: () => maximum,
  };
}

function cutRuntime(ctx: AutoEditCtx): CutReviewLoopRuntime {
  const run = {} as CutReviewLoopRuntime;
  run.job = freshJob({ ctx, token: "cut-concurrent", snapshots: 0 }, new Date().toISOString());
  run.io = {
    send: () => {},
    advance: (update: CheckpointUpdate) => {
      run.job = { ...run.job, ...update, updatedAt: new Date().toISOString() };
      return run.job;
    },
  };
  return run;
}

function planningRuntime(ctx: AutoEditCtx): PlanningLoopRuntime {
  const run = {} as PlanningLoopRuntime;
  run.job = freshJob({ ctx, token: "plan-concurrent", snapshots: 0 }, new Date().toISOString());
  const update = (value: CheckpointUpdate) => {
    run.job = { ...run.job, ...value, updatedAt: new Date().toISOString() };
    return run.job;
  };
  run.io = { send: () => {}, advance: update, invalidate: update };
  return run;
}

async function cutCriticsOverlap(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "cut"));
  const sync = barrier(2);
  const deps: Partial<CutReviewLoopDependencies> = {
    gate: async (value) => cutGate(value),
    review: async () => {
      await sync.enter();
      return { provider: "codex", ms: 1, review: pass("cut") };
    },
  };
  const receipt = await runCutReviewLoop(cutRuntime(ctx), deps);
  assert.equal(sync.max(), 2, "both cut critics must be in flight together");
  assert.deepEqual(receipt.reviews.map((item) => item.round), [1, 2]);
  const authorities = receipt.reviews.map((item) =>
    JSON.parse(readFileSync(item.path, "utf8")).inputAuthority.digest);
  assert.equal(new Set(authorities).size, 1, "approval reviews must bind one authority");
}

function issue(code: string, evidence: string, critical = false): ProducerMaterialIssue {
  return {
    code, severity: critical ? "critical" : "major", lane: "graphics",
    message: `${code} needs repair`, evidence: [evidence], requiredAction: `repair ${code}`,
  };
}

async function planningMergesConcurrentIssues(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "planning"));
  const sync = barrier(2);
  let revision: ProducerReview | undefined;
  const deps: Partial<PlanningLoopDependencies> = {
    gate: async () => PASS_GATES, approve: () => {},
    checkpoint: async () => ({ status: "committed" as const }),
    review: async (request) => {
      if (request.round <= 2) await sync.enter();
      const review = request.round === 1
        ? revise("plan", [issue("SHARED", "critic one")])
        : request.round === 2
          ? revise("plan", [issue("SHARED", "critic two", true), issue("SECOND", "critic two")])
          : pass("plan");
      return { provider: "codex", ms: 1, review };
    },
    revise: async (value, review) => {
      revision = review;
      const plan = JSON.parse(readFileSync(value.planPath, "utf8"));
      writeFileSync(value.planPath, JSON.stringify({
        ...plan, planVersion: 2,
        graphicsTrack: [{ start: 0, end: 1, template: "statement-card" }],
      }));
      return {
        provider: "codex", ms: 1,
        receipt: {
          schemaVersion: 1, changedPlan: true,
          addressedIssueCodes: review.materialIssues.map((item) => item.code),
          deferredIssueCodes: [], summary: "merged repair",
        },
      };
    },
  };
  const result = await runPlanningReviewLoop(planningRuntime(ctx), deps);
  assert.equal(sync.max(), 2, "both planning critics must be in flight together");
  assert.equal(result.rounds, 4);
  assert.deepEqual(revision?.materialIssues.map((item) => item.code), ["SHARED", "SECOND"]);
  assert.deepEqual(revision?.materialIssues[0].evidence, ["critic one", "critic two"]);
  assert.equal(revision?.materialIssues[0].severity, "critical");
}

async function authorityChangeFailsClosed(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "authority-change"));
  const deps: Partial<PlanningLoopDependencies> = {
    gate: async () => PASS_GATES, approve: () => {},
    checkpoint: async () => ({ status: "committed" as const }),
    review: async (request) => {
      if (request.round === 1) writeFileSync(ctx.planPath, '{"planVersion":99}');
      return { provider: "codex", ms: 1, review: pass("plan") };
    },
  };
  await assert.rejects(
    runPlanningReviewLoop(planningRuntime(ctx), deps),
    /planning authority changed while independent critics were running/,
  );
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-review-concurrency-"));
  try {
    await cutCriticsOverlap(root);
    await planningMergesConcurrentIssues(root);
    await authorityChangeFailsClosed(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("auto-edit-review-concurrency.test.ts: all assertions passed");
}

void main();
