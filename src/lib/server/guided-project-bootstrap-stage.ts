/** Review an operator-supplied cut candidate without any writer, repair, or visual stage. */
import { guidedCutBoundary } from "@/app/api/producer/auto-edit/guided-cut-boundary";
import { requireCompatibilityCutAuthority } from "@/app/api/producer/auto-edit/compatibility-cut-authority";
import type { AuthoringRuntime, AuthoringStageDependencies, AuthoringStageOutcome } from "@/app/api/producer/auto-edit/authoring-stage";
import { assertExistingCutContext } from "./guided-project-bootstrap-contract";
import { assertBootstrapCurrent } from "./guided-project-bootstrap-guard";
import { assertBootstrapQuiescent } from "./guided-project-bootstrap-observer";

export const bootstrapStageGuards = { current: assertBootstrapCurrent, quiescent: assertBootstrapQuiescent,
  compatibility: requireCompatibilityCutAuthority, boundary: guidedCutBoundary };

/** Existing independent critics and previsual gate retain their actual semantics and artifacts. */
export async function runExistingCutCandidateStage(run: AuthoringRuntime, deps: AuthoringStageDependencies): Promise<AuthoringStageOutcome> {
  assertExistingCutContext(run.job.ctx);
  if (!run.job.ctx.existingCutCandidate || run.job.reviewSavedPlan || run.job.attempts !== 1
      || run.job.cutAcceptance || run.job.guidedHandoffV2) throw new Error("Existing cut candidate is not an unapproved new-only review");
  bootstrapStageGuards.current(run.job);
  await deps.validateCut(run.job.ctx, run.io.send);
  bootstrapStageGuards.current(run.job);
  await bootstrapStageGuards.quiescent();
  // runCutReviewLoop itself runs the previsual gate and requires two independent clean critics.
  await deps.reviewCut(run);
  bootstrapStageGuards.current(run.job);
  await bootstrapStageGuards.quiescent();
  await deps.approveCut(run.job.ctx, run.io.send);
  const verified = await bootstrapStageGuards.compatibility(run.job.ctx, run.io.send, deps);
  bootstrapStageGuards.current(run.job);
  await bootstrapStageGuards.quiescent();
  const result = await bootstrapStageGuards.boundary(run, deps, verified);
  if (!result || result.status !== "awaiting_cut_approval") throw new Error("Existing-cut bootstrap must stop at qualified preview PAUSE");
  bootstrapStageGuards.current(run.job);
  await bootstrapStageGuards.quiescent();
  return result;
}
