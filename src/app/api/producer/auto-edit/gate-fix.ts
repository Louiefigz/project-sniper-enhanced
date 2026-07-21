import type { ProducerRevisionResult } from "./brain-review-runner";
import type {
  PlanningLoopDependencies,
  PlanningLoopRuntime,
} from "./planning-loop";
import { planningReviewArtifactPath } from "./planning-loop-review";
import type { ProducerReview } from "./review-contract";

const MAX_GATE_FIX_ATTEMPTS = 2;
// The mechanical gate fixer makes the SMALLEST change to pass a handful of
// named diagnostics — it is not a repair path for a structurally-broken plan.
// A deadline-salvaged partial can fail 25-30 deterministic gates at once; the
// fixer then spends two doomed spawns "deferring" them as non-mechanical
// (~10 min observed) before falling through to the full revision it should
// have gone straight to. Above this many gate errors, skip the fixer and route
// directly to the strictly-more-capable revision writer. Set generously so
// genuinely-mechanical batches still take the fast path.
export const MAX_GATE_FIX_ISSUES = 8;
// Run-scoped ceiling on fixer spawns (never reset): per-cycle attempts reset
// after every paid revision, so a plan that keeps regressing into gate
// failures could otherwise fund MAX_GATE_FIX_ATTEMPTS fresh spawns every
// cycle. Gate errors that survive this many spawns are not mechanical.
const MAX_GATE_FIX_TOTAL = 3;

export interface GateFixBudget {
  attempts: number; // within the current unpaid chain; the loop resets it per paid cycle
  totalAttempts: number; // run-scoped; never reset
  lastIssueCount?: number; // gate errors at this chain's previous funded spawn
}

/**
 * Extracts the deferred-issue failure message from a revision/fix receipt,
 * or null when the writer deferred nothing. Shared by the gate fixer and the
 * full revision path.
 */
export function deferredFailure(receipt: ProducerRevisionResult): string | null {
  if (!receipt.receipt.deferredIssueCodes.length) return null;
  return `review writer deferred non-plan issues: ${receipt.receipt.deferredIssueCodes.join(", ")}`;
}

/**
 * Funds one fixer spawn within budget: the per-cycle attempt cap, the
 * run-scoped total cap, and a no-progress guard — a consecutive spawn is paid
 * only when the gate-error count strictly shrank (gate issue codes are
 * positional, so the count is the stable identity across attempts). A denial
 * makes the caller fall through to the strictly-more-capable revision writer,
 * exactly like the MAX_GATE_FIX_ISSUES route.
 */
export function fundGateFix(budget: GateFixBudget, issueCount: number): boolean {
  if (budget.attempts >= MAX_GATE_FIX_ATTEMPTS) return false;
  if (budget.totalAttempts >= MAX_GATE_FIX_TOTAL) return false;
  if (budget.lastIssueCount !== undefined && issueCount >= budget.lastIssueCount) return false;
  budget.attempts += 1;
  budget.totalAttempts += 1;
  budget.lastIssueCount = issueCount;
  return true;
}

/**
 * Bounded fixer for gate-only failures (no critic ran): never charges the
 * cycle budget and never zeroes clean credit — stale credit is already
 * hash-fenced by recordCleanPlanningResult. Returns false when the fixer
 * itself failed so the caller falls through to the full revision path.
 */
export async function fixGateFailure(
  run: PlanningLoopRuntime,
  review: ProducerReview,
  spawn: { round: number; attempt: number },
  deps: PlanningLoopDependencies,
): Promise<boolean> {
  const { round, attempt } = spawn;
  run.io.send({ event: "gate_fix_started", stage: "plan", round, attempt });
  deps.snapshot(run.job.ctx.planPath);
  let result: ProducerRevisionResult;
  try {
    result = await deps.gateFix(run.job.ctx, review, round);
  } catch (error) {
    run.io.send({
      event: "gate_fix_failed", stage: "plan", round, attempt,
      message: `Gate fixer failed (${(error as Error).message}); falling back to a full revision round.`,
    });
    return false;
  }
  deps.writeJson(
    planningReviewArtifactPath(run.job, round, `gate-fix-receipt-${attempt}.json`),
    result,
  );
  const deferred = deferredFailure(result);
  if (deferred || !result.receipt.changedPlan) {
    run.io.send({
      event: "gate_fix_failed", stage: "plan", round, attempt,
      message: deferred
        ?? "Gate fixer did not change edit_plan.json; falling back to a full revision round.",
    });
    return false;
  }
  run.job = run.io.advance({
    checkpoint: "planning_review", phase: "planning_review",
    message: `Gate fixer attempt ${attempt} revised the plan; rerunning deterministic gates without charging the review budget.`,
    planHash: deps.hash(run.job.ctx.planPath),
    authorityDigest: deps.authority(run.job.ctx).digest,
  });
  run.io.send({
    event: "gate_fix_completed", stage: "plan", round, attempt, provider: result.provider,
  });
  return true;
}
