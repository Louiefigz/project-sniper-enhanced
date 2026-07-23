import { snapshotPlan } from "../../_lib/plan-snapshots";
import { planContentHash } from "@/lib/server/auto-edit-authority";
import {
  autoEditAuthoritySnapshot,
} from "@/lib/server/auto-edit-authority-snapshot";
import {
  fileSha256,
  checkpointReached,
  type AutoEditJob,
  type CheckpointUpdate,
} from "@/lib/server/auto-edit-job-store";
import { writeQualityJson } from "@/lib/server/auto-edit-quality-artifacts";
import {
  runProducerGateFix,
  runProducerReview,
  runProducerRevision,
} from "./brain-review-runner";
import {
  MAX_GATE_FIX_ISSUES,
  deferredFailure,
  fixGateFailure,
  fundGateFix,
  type GateFixBudget,
} from "./gate-fix";
import {
  runPlanningGateBundle,
} from "./planning-gates";
import {
  planningReviewArtifactPath,
  requiredPlanningHash,
} from "./planning-loop-review";
import {
  runPlanningReviewBatch,
} from "./planning-review-batch";
import {
  mergePlanningResults,
  recordCleanPlanningResult,
} from "./planning-clean-progress";
import {
  MAX_PLANNING_REVIEW_ROUNDS,
  planningBudgetViable,
  planningCanConverge,
  requiredPlanningRounds,
} from "./round-policy";
import type { ProducerReview } from "./review-contract";
import { timedStage } from "@/lib/server/stage-timing";
import { AutoEditError, type Send } from "./stream";
import { publishPalmierWorkingCheckpoint } from "./palmier-checkpoints";
import { writeTemplateUsageApproval } from "@/lib/server/template-usage-approval";

export interface PlanningLoopIo {
  send: Send;
  advance: (update: CheckpointUpdate) => AutoEditJob;
  invalidate: (update: CheckpointUpdate) => AutoEditJob;
}

export interface PlanningLoopRuntime {
  job: AutoEditJob;
  io: PlanningLoopIo;
}

export interface PlanningLoopDependencies {
  gate: typeof runPlanningGateBundle;
  review: typeof runProducerReview;
  revise: typeof runProducerRevision;
  gateFix: typeof runProducerGateFix;
  hash: typeof fileSha256;
  contentHash: typeof planContentHash;
  snapshot: typeof snapshotPlan;
  writeJson: typeof writeQualityJson;
  authority: typeof autoEditAuthoritySnapshot;
  checkpoint: typeof publishPalmierWorkingCheckpoint;
  approve: typeof writeTemplateUsageApproval;
}

export interface PlanningLoopResult {
  rounds: number;
  reviewPaths: string[];
  reviewedPlanHash: string;
}

const DEFAULT_DEPS: PlanningLoopDependencies = {
  gate: runPlanningGateBundle,
  review: runProducerReview,
  revise: runProducerRevision,
  gateFix: runProducerGateFix,
  hash: fileSha256,
  contentHash: planContentHash,
  snapshot: snapshotPlan,
  writeJson: writeQualityJson,
  authority: autoEditAuthoritySnapshot,
  checkpoint: publishPalmierWorkingCheckpoint,
  approve: writeTemplateUsageApproval,
};

function planningReusable(job: AutoEditJob, deps: PlanningLoopDependencies): boolean {
  if (!checkpointReached(job.checkpoint, "plan_reviewed")) return false;
  const current = deps.authority(job.ctx);
  return !!current.planHash && current.planHash === job.reviewedPlanHash
    && current.digest === job.reviewedAuthorityDigest;
}

function invalidateChangedReview(run: PlanningLoopRuntime, deps: PlanningLoopDependencies): void {
  if (!checkpointReached(run.job.checkpoint, "plan_reviewed")) return;
  if (planningReusable(run.job, deps)) return;
  const current = deps.authority(run.job.ctx);
  const message = "Plan, source, intent, reference, renderer, or QC policy changed after review; restarting bounded planning review.";
  run.job = run.io.invalidate({
    checkpoint: "plan_authored",
    phase: "planning_review",
    message,
    planningRound: 0,
    planningCycles: 0,
    planHash: current.planHash ?? undefined,
    manifestHash: current.manifestHash ?? undefined,
    authorityDigest: current.digest,
    referenceProfileHash: run.job.ctx.referenceStudy
      ? deps.hash(run.job.ctx.referenceStudy.profilePath) : undefined,
  });
  run.io.send({ event: "checkpoint_invalidated", reason: "review_authority_changed", message });
}

async function revisePlan(
  run: PlanningLoopRuntime,
  review: ProducerReview,
  round: number,
  deps: PlanningLoopDependencies,
): Promise<void> {
  if (review.verdict === "block") {
    throw new AutoEditError(`planning critic blocked render: ${review.materialIssues.map((x) => x.code).join(", ")}`);
  }
  const before = requiredPlanningHash(deps.contentHash(run.job.ctx.planPath), "edit plan content");
  deps.snapshot(run.job.ctx.planPath);
  run.io.send({ event: "revision_started", stage: "plan", round });
  const result = await timedStage(
    run.job.ctx.dir, "planning_revision", () => deps.revise(run.job.ctx, review, round),
  );
  deps.writeJson(planningReviewArtifactPath(run.job, round, "revision-receipt.json"), result);
  const deferred = deferredFailure(result);
  if (deferred) throw new AutoEditError(deferred);
  const after = requiredPlanningHash(deps.contentHash(run.job.ctx.planPath), "revised edit plan content");
  if (!result.receipt.changedPlan || before === after) {
    throw new AutoEditError("planning revision reported addressed issues but did not change edit_plan.json");
  }
  run.io.send({ event: "revision_completed", stage: "plan", round, provider: result.provider });
}

function advanceAfterRevision(
  run: PlanningLoopRuntime,
  rounds: { criticRound: number; cycle: number },
  deps: PlanningLoopDependencies,
): void {
  run.job = run.io.invalidate({
    checkpoint: "plan_authored",
    phase: "planning_review",
    message: `Planning cycle ${rounds.cycle} revised the plan; starting a fresh review cycle.`,
    planningRound: rounds.criticRound,
    planningCycles: rounds.cycle,
    planningCleanRounds: 0,
    planHash: deps.hash(run.job.ctx.planPath),
    authorityDigest: deps.authority(run.job.ctx).digest,
  });
}

function completePlanning(
  run: PlanningLoopRuntime,
  rounds: { criticRound: number; cycle: number },
  reviewPaths: string[],
  deps: PlanningLoopDependencies,
): PlanningLoopResult {
  const { ctx } = run.job;
  const authority = deps.authority(ctx);
  const reviewedPlanHash = requiredPlanningHash(authority.planHash ?? undefined, "reviewed edit plan");
  run.job = run.io.advance({
    checkpoint: "plan_reviewed",
    phase: "validating",
    message: `Current plan passed ${run.job.planningCleanRounds} clean independent review round(s); confirming render authority.`,
    planningRound: rounds.criticRound,
    planningCycles: rounds.cycle,
    planningRoundsRequired: requiredPlanningRounds(ctx.scope),
    planningCleanRounds: run.job.planningCleanRounds,
    planningCleanPlanHash: reviewedPlanHash,
    planHash: reviewedPlanHash,
    reviewedPlanHash,
    manifestHash: authority.manifestHash ?? undefined,
    authorityDigest: authority.digest,
    reviewedAuthorityDigest: authority.digest,
    planningCleanAuthorityDigest: authority.digest,
    referenceProfileHash: ctx.referenceStudy ? deps.hash(ctx.referenceStudy.profilePath) : undefined,
  });
  return { rounds: rounds.criticRound, reviewPaths, reviewedPlanHash };
}

export async function runPlanningReviewLoop(
  run: PlanningLoopRuntime,
  dependencies: Partial<PlanningLoopDependencies> = {},
): Promise<PlanningLoopResult> {
  const deps = { ...DEFAULT_DEPS, ...dependencies };
  invalidateChangedReview(run, deps);
  if (planningReusable(run.job, deps)) {
    return {
      rounds: run.job.planningRound ?? requiredPlanningRounds(run.job.ctx.scope),
      reviewPaths: [],
      reviewedPlanHash: run.job.reviewedPlanHash!,
    };
  }
  const required = requiredPlanningRounds(run.job.ctx.scope);
  const reviewPaths: string[] = [];
  // planningRound stays the per-critic artifact-dir high-water (review
  // evidence enumerates it); the budget is paid in CYCLES — one
  // author→review→revise pass, however wide the critic batch.
  let criticRound = run.job.planningRound ?? 0;
  let cycle = run.job.planningCycles ?? run.job.planningRound ?? 0;
  const gateFixBudget: GateFixBudget = { attempts: 0, totalAttempts: 0 };
  const initialAuthority = deps.authority(run.job.ctx);
  let cleanRounds = run.job.planningCleanPlanHash === initialAuthority.planHash
      && run.job.planningCleanAuthorityDigest === initialAuthority.digest
    ? run.job.planningCleanRounds ?? 0 : 0;
  let cleanPlanHash = cleanRounds ? run.job.planningCleanPlanHash : undefined;
  let cleanAuthorityDigest = cleanRounds ? run.job.planningCleanAuthorityDigest : undefined;
  while (cycle < MAX_PLANNING_REVIEW_ROUNDS) {
    const firstRound = criticRound + 1;
    const batchSize = Math.max(1, required - cleanRounds);
    run.job = run.io.advance({
      checkpoint: "planning_review", phase: "planning_review",
      message: `Planning cycle ${cycle + 1}/${MAX_PLANNING_REVIEW_ROUNDS}; deterministic gates run before ${batchSize} independent critic(s) inspect the same immutable plan.`,
      planningRound: criticRound, planningRoundsRequired: required,
      planningCycles: cycle,
    });
    const results = await timedStage(
      run.job.ctx.dir, "planning_round",
      () => runPlanningReviewBatch(run, firstRound, batchSize, deps),
    );
    criticRound += results.length;
    reviewPaths.push(...results.map((result) => result.path));
    const review = mergePlanningResults(results);
    // Gate-only failure — no critic ran (the batch returns before launching
    // critics when the deterministic bundle fails). A bounded low-effort
    // fixer handles the machine diagnostics without charging the cycle
    // budget or zeroing clean credit; when its budget denies a spawn
    // (per-cycle cap, run total, or no progress) the failure falls through
    // to the full revision path below.
    const gateOnly = results.length === 1 && !results[0].gates.ok;
    // For a gate-only failure the review's materialIssues ARE the gate errors,
    // so their count gates whether the mechanical fixer is even worth trying.
    const gateFixable = review.materialIssues.length <= MAX_GATE_FIX_ISSUES;
    if (gateOnly && gateFixable && fundGateFix(gateFixBudget, review.materialIssues.length)) {
      const fixed = await fixGateFailure(
        run, review, { round: firstRound, attempt: gateFixBudget.attempts }, deps,
      );
      if (fixed) continue;
    }
    cycle += 1;
    gateFixBudget.attempts = 0;
    gateFixBudget.lastIssueCount = undefined;
    if (review.materialIssues.length) {
      cleanRounds = 0;
      cleanPlanHash = undefined;
      cleanAuthorityDigest = undefined;
      // Refuse to pay for a revision the remaining budget can no longer
      // convert into the required clean count — stop with the exhaustion
      // verdict BEFORE funding a doomed revision, not after.
      if (!planningBudgetViable(MAX_PLANNING_REVIEW_ROUNDS - cycle, required, required)) {
        run.io.send({ event: "max_rounds_exhausted", stage: "planning", round: cycle });
        throw new AutoEditError(`planning review exhausted ${cycle} rounds: ${review.materialIssues.map((x) => x.code).join(", ")}`);
      }
      await revisePlan(run, review, criticRound, deps);
      advanceAfterRevision(run, { criticRound, cycle }, deps);
      continue;
    }
    const state = {
      rounds: cleanRounds, hash: cleanPlanHash,
      authority: cleanAuthorityDigest, required,
    };
    for (const result of results) {
      await recordCleanPlanningResult(run, result, state, deps);
    }
    cleanRounds = state.rounds;
    cleanPlanHash = state.hash;
    cleanAuthorityDigest = state.authority;
    if (planningCanConverge(run.job.ctx.scope, cleanRounds, 0)) {
      const currentAuthority = deps.authority(run.job.ctx);
      if (currentAuthority.digest !== cleanAuthorityDigest) {
        throw new AutoEditError("planning authority changed before review approval was committed");
      }
      const finalResult = results.at(-1)!;
      if (run.job.ctx.templateUsage) deps.approve({
        producerDir: run.job.ctx.dir, planPath: run.job.ctx.planPath,
        manifestPath: run.job.ctx.manifestPath, transcriptsDir: run.job.ctx.transcriptsDir,
        templateUsage: run.job.ctx.templateUsage,
        verdict: finalResult.gates.gates.templateUsage,
        operatorIntentVerdict: finalResult.gates.gates.operatorIntent,
      });
      return completePlanning(run, { criticRound, cycle }, reviewPaths, deps);
    }
  }
  throw new AutoEditError("planning review ended without an approved plan");
}
