import { sameAutoEditAuthority } from "@/lib/server/auto-edit-authority-snapshot";
import type {
  PlanningLoopDependencies,
  PlanningLoopRuntime,
} from "./planning-loop";
import type { PlanningRoundResult } from "./planning-review-batch";
import type { ProducerReview } from "./review-contract";
import { mergeProducerReviewBatch } from "./review-batch";
import { requiredPlanningHash } from "./planning-loop-review";
import { AutoEditError } from "./stream";

export interface CleanPlanningState {
  rounds: number;
  hash?: string;
  authority?: string;
  required: number;
}

export function mergePlanningResults(results: PlanningRoundResult[]): ProducerReview {
  const first = results[0];
  if (!first) throw new AutoEditError("planning critic batch returned no reviews");
  if (results.some((result) => result.authority.digest !== first.authority.digest)) {
    throw new AutoEditError("planning critic batch did not share one immutable authority");
  }
  return mergeProducerReviewBatch(results.map((result) => result.review), "plan");
}

async function publishFirstClean(
  run: PlanningLoopRuntime,
  result: PlanningRoundResult,
  cleanRounds: number,
  deps: PlanningLoopDependencies,
): Promise<void> {
  if (cleanRounds !== 1) return;
  const stage = result.round === 1 ? "plan" as const : "revision" as const;
  await deps.checkpoint(run.job.ctx, { stage, round: result.round }, run.io.send);
}

export async function recordCleanPlanningResult(
  run: PlanningLoopRuntime,
  result: PlanningRoundResult,
  state: CleanPlanningState,
  deps: PlanningLoopDependencies,
): Promise<void> {
  const current = deps.authority(run.job.ctx);
  if (current.digest !== result.authority.digest) {
    throw new AutoEditError("planning authority changed before clean review was recorded");
  }
  const hash = requiredPlanningHash(current.planHash ?? undefined, "clean reviewed plan");
  state.rounds = state.hash === hash && state.authority === current.digest
    ? state.rounds + 1 : 1;
  state.hash = hash;
  state.authority = current.digest;
  // Commit the clean-round advance to the journal BEFORE the courtesy Palmier
  // publish: the publish consumes committed state and must never gate it — a
  // checkpoint hiccup must not discard the paid review. The persisted credit
  // is authority-keyed, so a drift during the publish still invalidates it on
  // resume.
  run.job = run.io.advance({
    checkpoint: "planning_review", phase: "planning_review",
    message: `Current plan has ${state.rounds}/${state.required} clean independent review(s).`,
    planningRound: result.round, planningRoundsRequired: state.required,
    planningCleanRounds: state.rounds, planningCleanPlanHash: state.hash,
    planningCleanAuthorityDigest: state.authority,
    authorityDigest: current.digest,
  });
  await publishFirstClean(run, result, state.rounds, deps);
  if (!sameAutoEditAuthority(current, deps.authority(run.job.ctx))) {
    throw new AutoEditError("planning authority changed while publishing the clean checkpoint");
  }
}
