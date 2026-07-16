import {
  sameAutoEditAuthority,
  type AutoEditAuthoritySnapshot,
} from "@/lib/server/auto-edit-authority-snapshot";
import type { ProducerReviewResult } from "./brain-review-runner";
import {
  planningGateBundleEvent,
  type GateBundleVerdict,
} from "./planning-gates";
import {
  combinePlanningReview,
  persistPlanningGateFailureRound,
  persistPlanningReviewInputs,
  persistPlanningRound,
  planningGateInput,
} from "./planning-loop-review";
import type {
  PlanningLoopDependencies,
  PlanningLoopRuntime,
} from "./planning-loop";
import type { ProducerReview } from "./review-contract";
import { rejectedBatchResult } from "./review-batch";
import { AutoEditError } from "./stream";

export interface PlanningRoundResult {
  round: number;
  review: ProducerReview;
  path: string;
  gates: GateBundleVerdict;
  authority: AutoEditAuthoritySnapshot;
}

interface PlanningPacketEntry {
  round: number;
  packet: ReturnType<typeof persistPlanningReviewInputs>;
}

interface PlanningBatchContext {
  run: PlanningLoopRuntime;
  gates: GateBundleVerdict;
  authority: AutoEditAuthoritySnapshot;
  deps: PlanningLoopDependencies;
}

function launchCritics(
  context: PlanningBatchContext,
  entries: PlanningPacketEntry[],
): Promise<PromiseSettledResult<ProducerReviewResult>[]> {
  const { run, deps } = context;
  for (const { round } of entries) {
    // round numbers artifact dirs (one per critic spawn); the budget is the
    // CYCLE cap, reported per-cycle by the loop — so no maxRounds here.
    run.io.send({ event: "planning_review_started", round });
  }
  return Promise.allSettled(entries.map(({ round, packet }) =>
    deps.review({ stage: "plan", ctx: run.job.ctx, round, packet })));
}

function persistCriticResults(
  context: PlanningBatchContext,
  entries: PlanningPacketEntry[],
  settled: PromiseSettledResult<ProducerReviewResult>[],
): PlanningRoundResult[] {
  const { run, gates, authority, deps } = context;
  return settled.flatMap((value, index) => {
    if (value.status === "rejected") return [];
    const { round, packet } = entries[index];
    const result = value.value;
    const review = combinePlanningReview(result.review, gates);
    const reviewPath = persistPlanningRound({
      job: run.job, round, gates, result, authority, packet,
    }, deps);
    run.io.send({
      event: "planning_review_completed", round, verdict: review.verdict,
      materialIssues: review.materialIssues.length, provider: result.provider,
      ms: result.ms,
    });
    return { round, review, path: reviewPath, gates, authority };
  });
}

/** Persist the machine critique as this round's dirty result. No critic ran;
 * the loop routes this gate-only failure to the bounded gate fixer first and
 * only falls back to the full revision writer when the fixer fails. */
function gateFailure(
  context: PlanningBatchContext,
  round: number,
): PlanningRoundResult {
  const { run, gates, authority, deps } = context;
  const packet = persistPlanningReviewInputs({ job: run.job, round, gates, authority }, deps);
  const failure = persistPlanningGateFailureRound({
    job: run.job, round, gates, authority, packet,
  }, deps);
  if (!sameAutoEditAuthority(authority, deps.authority(run.job.ctx))) {
    throw new AutoEditError("planning authority changed before gate-failure evidence was committed");
  }
  run.io.send({
    event: "planning_gate_revision_required", round,
    materialIssues: failure.review.materialIssues.length,
  });
  return { round, ...failure, gates, authority };
}

/** Gate once, then run N read-only critics against separately bound packets. */
export async function runPlanningReviewBatch(
  run: PlanningLoopRuntime,
  firstRound: number,
  count: number,
  deps: PlanningLoopDependencies,
): Promise<PlanningRoundResult[]> {
  const authority = deps.authority(run.job.ctx);
  const gates = await deps.gate(planningGateInput(run.job));
  if (!sameAutoEditAuthority(authority, deps.authority(run.job.ctx))) {
    throw new AutoEditError("planning authority changed while deterministic gates were running");
  }
  run.io.send(planningGateBundleEvent(gates));
  const context = { run, gates, authority, deps };
  if (!gates.ok) return [gateFailure(context, firstRound)];
  const entries = Array.from({ length: count }, (_, index) => {
    const round = firstRound + index;
    return {
      round,
      packet: persistPlanningReviewInputs({ job: run.job, round, gates, authority }, deps),
    };
  });
  const settled = await launchCritics(context, entries);
  if (!sameAutoEditAuthority(authority, deps.authority(run.job.ctx))) {
    throw new AutoEditError("planning authority changed while independent critics were running");
  }
  const persisted = persistCriticResults(context, entries, settled);
  if (!sameAutoEditAuthority(authority, deps.authority(run.job.ctx))) {
    throw new AutoEditError("planning authority changed before review evidence was committed");
  }
  const failure = rejectedBatchResult(settled);
  if (failure) throw failure.reason;
  return persisted;
}
