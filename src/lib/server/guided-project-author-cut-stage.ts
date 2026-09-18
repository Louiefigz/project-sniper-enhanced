/** New-only source/brief cut authoring; all output stops at the human preview boundary. */
import { guidedCutBoundary } from "@/app/api/producer/auto-edit/guided-cut-boundary";
import { requireCompatibilityCutAuthority } from "@/app/api/producer/auto-edit/compatibility-cut-authority";
import type { AuthoringRuntime, AuthoringStageDependencies, AuthoringStageOutcome } from "@/app/api/producer/auto-edit/authoring-stage";
import { runWriter } from "@/app/api/producer/auto-edit/authoring-writer";
import { assertExistingCutContext } from "./guided-project-bootstrap-contract";
import { assertAuthoredBootstrapSeed, assertBootstrapCurrent } from "./guided-project-bootstrap-guard";
import { assertBootstrapQuiescent } from "./guided-project-bootstrap-observer";

export const authoredCutStageGuards = { current: assertBootstrapCurrent, seed: assertAuthoredBootstrapSeed,
  quiescent: assertBootstrapQuiescent, compatibility: requireCompatibilityCutAuthority, boundary: guidedCutBoundary };

/** Revalidate after every asynchronous phase, including actual process quiescence. */
async function settled(run: AuthoringRuntime): Promise<void> {
  authoredCutStageGuards.current(run.job);
  await authoredCutStageGuards.quiescent();
  authoredCutStageGuards.current(run.job);
}

/** No saved-plan, human-accepted, repeated, or ordinary resumed writer is eligible. */
function assertNewAuthoring(run: AuthoringRuntime): void {
  assertExistingCutContext(run.job.ctx);
  const job = run.job;
  if (!job.ctx.authoredCut || job.reviewSavedPlan || job.attempts !== 1 || job.status !== "running" || job.checkpoint !== "queued"
      || job.cutAcceptance || job.cutAcceptanceAttempt || job.cutApprovalRequest || job.cutPreview || job.cutApprovalWaitStartedAt
      || job.guidedHandoffV2) throw new Error("Authored cut requires an unapproved new-only empty-seed attempt");
}

/** Existing critics may revise evidence-backed cut defects, never infer human acceptance. */
export async function runAuthoredCutStage(run: AuthoringRuntime, deps: AuthoringStageDependencies): Promise<AuthoringStageOutcome> {
  assertNewAuthoring(run);
  await settled(run);
  assertNewAuthoring(run);
  authoredCutStageGuards.seed(run.job);
  await runWriter(run, deps, "cut", "start");
  await settled(run);
  await deps.validateCut(run.job.ctx, run.io.send);
  await settled(run);
  await deps.reviewCut(run);
  await settled(run);
  await deps.approveCut(run.job.ctx, run.io.send);
  await settled(run);
  const verified = await authoredCutStageGuards.compatibility(run.job.ctx, run.io.send, deps);
  await settled(run);
  const result = await authoredCutStageGuards.boundary(run, deps, verified);
  if (!result || result.status !== "awaiting_cut_approval") throw new Error("Authored-cut bootstrap must stop at qualified preview PAUSE");
  await settled(run);
  return result;
}
