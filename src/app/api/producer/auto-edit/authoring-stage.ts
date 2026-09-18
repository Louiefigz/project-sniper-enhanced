import { checkpointReached, type AutoEditJob, type CheckpointUpdate } from
  "@/lib/server/auto-edit-job-store";
import type { AutoEditAuthoritySnapshot } from "@/lib/server/auto-edit-authority-snapshot";
import type { AuthoringResult, AuthoringSessionMode, AuthoringStage } from "./authoring";
import {
  approvePrevisualCut, approveSavedPlanCut,
  validatePrevisualCut, validateSavedPlanCut, verifyApprovedCut,
} from "./cut-approval";
import { AutoEditError, type AutoEditCtx, type Send } from "./stream";
import { runCutReviewLoop } from "./cut-review-loop";
import { verifyCutReviewApproval } from "./cut-review-approval";
import { requireCompatibilityCutAuthority } from "./compatibility-cut-authority";
import type { CompatibilityPictureLockResult, mintCompatibilityPictureLock } from "./compatibility-picture-lock";
import { markAuthoringSessionEstablished } from "./authoring-session-state";
import type {
  PalmierCheckpointOutcome,
  PalmierCheckpointSpec,
} from "./palmier-checkpoints";
import {
  currentCutPlanState,
  mintRetroactiveCutApproval,
  resumableCutCandidate,
  reusableApprovedCut,
  unchangedSavedPlanState,
  type CutPlanState,
} from "./authoring-cut-state";
import { guidedCutBoundary, type GuidedCutDependencies } from "./guided-cut-boundary";
import type { CutApprovalPauseOutcome } from "./cut-approval-request";
import { runExistingCutCandidateStage } from "@/lib/server/guided-project-bootstrap-stage";
import { runAuthoredCutStage } from "@/lib/server/guided-project-author-cut-stage";
import { runWriter } from "./authoring-writer";

export type AuthoringStageOutcome = { status: "authored" } | CutApprovalPauseOutcome;

export interface AuthoringRuntime {
  job: AutoEditJob;
  io: {
    send: Send;
    advance: (update: CheckpointUpdate) => AutoEditJob;
    invalidate: (update: CheckpointUpdate) => AutoEditJob;
  };
}

export type StagedAuthor = (
  ctx: AutoEditCtx,
  send: Send,
  stage: AuthoringStage,
  sessionMode: AuthoringSessionMode,
) => Promise<AuthoringResult>;

export interface AuthoringStageDependencies {
  exists: (filePath: string) => boolean;
  hashFile: (filePath: string) => string | undefined;
  author: StagedAuthor;
  authority: (ctx: AutoEditJob["ctx"]) => AutoEditAuthoritySnapshot;
  validateCut: typeof validatePrevisualCut;
  validateSavedCut: typeof validateSavedPlanCut;
  reviewCut: typeof runCutReviewLoop;
  verifyReviewCut: typeof verifyCutReviewApproval;
  approveCut: typeof approvePrevisualCut;
  approveSavedCut: typeof approveSavedPlanCut;
  verifyCut: typeof verifyApprovedCut;
  lockCut: typeof mintCompatibilityPictureLock;
  cutApprovalAccepted?: GuidedCutDependencies["cutApprovalAccepted"];
  prepareCutPreview?: GuidedCutDependencies["prepareCutPreview"];
  bindSession?: typeof markAuthoringSessionEstablished;
  /** Courtesy Palmier publish — three-valued outcome, never throws. */
  checkpoint?: (
    ctx: AutoEditCtx,
    spec: PalmierCheckpointSpec,
    send: Send,
  ) => Promise<PalmierCheckpointOutcome>;
}

function advanceAuthored(
  run: AuthoringRuntime,
  state: CutPlanState,
  message = "Cuts were approved before visual planning; the complete plan now starts independent review.",
): void {
  run.job = run.io.advance({
    checkpoint: "plan_authored", phase: "planning_review",
    message,
    planHash: state.fileHash, planningRound: 0, planningCycles: 0,
    authorityDigest: state.authority.digest,
  });
}

function invalidateForCut(run: AuthoringRuntime, reason: string): void {
  run.job = run.io.invalidate({
    checkpoint: "authoring", phase: "authoring", message: reason,
    planningRound: 0, planningCycles: 0,
  });
  run.io.send({ event: "checkpoint_invalidated", reason: "cut_approval_missing", message: reason });
}

function reuseUnchangedSavedPlan(
  run: AuthoringRuntime,
  deps: AuthoringStageDependencies,
  expectedHash: string | undefined,
): boolean {
  const state = unchangedSavedPlanState(run, deps, expectedHash);
  if (!state) return false;
  advanceAuthored(run, state,
    "The complete saved plan kept its exact bytes through cut review; starting planning review.");
  run.io.send({
    event: "resume", stage: "visual", checkpoint: "plan_authored",
    message: "Saved-plan cut authority passed; visual re-authoring was skipped.",
  });
  return true;
}

async function resumeBootstrappedPlan(
  run: AuthoringRuntime,
  deps: AuthoringStageDependencies,
): Promise<CompatibilityPictureLockResult | null> {
  let verified = await reusableApprovedCut(run, deps);
  if (verified) {
    run.io.send({
      event: "resume", stage: "authoring", checkpoint: run.job.checkpoint,
      message: "Using the saved visual plan and its controller-approved cut authority.",
    });
    return verified;
  }
  if (await mintRetroactiveCutApproval(run, deps)) verified = await reusableApprovedCut(run, deps);
  if (verified) {
    run.io.send({
      event: "resume", stage: "authoring", checkpoint: run.job.checkpoint,
      message: "Saved plan re-passed the deterministic cut wall with its clean reviews intact; both writers are skipped.",
    });
    return verified;
  }
  invalidateForCut(run,
    "Saved plan has no valid controller cut approval; revalidating the cut before any re-authoring.");
  return null;
}

async function continueAcceptedCut(run: AuthoringRuntime, deps: AuthoringStageDependencies): Promise<AuthoringStageOutcome> {
  if (!deps.cutApprovalAccepted) throw new AutoEditError("Human accepted cut continuation requires its independent verifier");
  const verified = await requireCompatibilityCutAuthority(run.job.ctx, run.io.send, deps);
  if (await deps.cutApprovalAccepted(run.job, verified) !== true) throw new AutoEditError("Human accepted cut authority is invalid");
  if (checkpointReached(run.job.checkpoint, "plan_authored")) return { status: "authored" };
  if (run.job.reviewSavedPlan) {
    const state = currentCutPlanState(run, deps);
    if (!state) throw new AutoEditError("The human-accepted saved plan is missing");
    advanceAuthored(run, state);
    return { status: "authored" };
  }
  const mode = run.job.ctx.brainSessionId ? "resume" : "start";
  const state = await runWriter(run, deps, "visual", mode);
  const after = await requireCompatibilityCutAuthority(run.job.ctx, run.io.send, deps);
  if (await deps.cutApprovalAccepted(run.job, after) !== true) throw new AutoEditError("Visual authoring changed the human-accepted cut");
  advanceAuthored(run, state);
  return { status: "authored" };
}

export async function runAuthorStage(run: AuthoringRuntime,
  deps: AuthoringStageDependencies): Promise<AuthoringStageOutcome> {
  if (run.job.ctx.authoredCut !== undefined) return runAuthoredCutStage(run, deps);
  if (run.job.ctx.existingCutCandidate !== undefined) return runExistingCutCandidateStage(run, deps);
  // Accepted-cut drift must throw before legacy catch-to-null fallback can pay
  // for another cut writer/critic or mint retroactive cut authority.
  if (run.job.cutAcceptance) return continueAcceptedCut(run, deps);
  const bootstrapped = run.job.reviewSavedPlan
    || checkpointReached(run.job.checkpoint, "plan_authored");
  const savedPlanHash = bootstrapped && run.job.reviewSavedPlan
    ? deps.hashFile(run.job.ctx.planPath) : undefined;
  const resumed = bootstrapped ? await resumeBootstrappedPlan(run, deps) : null;
  if (resumed) {
    return await guidedCutBoundary(run, deps, resumed) ?? { status: "authored" };
  }
  let sessionMode: AuthoringSessionMode = run.job.attempts > 1
      && Boolean(run.job.ctx.brainSessionId)
    ? "resume" : "start";
  let verified = await reusableApprovedCut(run, deps);
  if (!verified) {
    const reusedCandidate = await resumableCutCandidate(run, deps, bootstrapped);
    if (!reusedCandidate && run.job.reviewSavedPlan) {
      throw new AutoEditError("saved-plan review may not invoke the cut writer");
    }
    if (!reusedCandidate) {
      await runWriter(run, deps, "cut", sessionMode);
      sessionMode = "resume";
    }
    await deps.reviewCut(run);
    const approve = run.job.reviewSavedPlan ? deps.approveSavedCut : deps.approveCut;
    await approve(run.job.ctx, run.io.send);
    verified = await requireCompatibilityCutAuthority(run.job.ctx, run.io.send, deps);
    await deps.checkpoint?.(run.job.ctx, { stage: "cut", round: 0 }, run.io.send);
  } else {
    run.io.send({
      event: "resume", stage: "cut_approval",
      message: "Approved cut authority is intact; resuming downstream visual authoring.",
    });
  }
  const boundary = await guidedCutBoundary(run, deps, verified);
  if (boundary) return boundary;
  if (run.job.reviewSavedPlan) {
    if (reuseUnchangedSavedPlan(run, deps, savedPlanHash)) return { status: "authored" };
    throw new AutoEditError("complete saved plan changed during cut review");
  }
  const state = await runWriter(run, deps, "visual", sessionMode);
  await requireCompatibilityCutAuthority(run.job.ctx, run.io.send, deps);
  advanceAuthored(run, state);
  return { status: "authored" };
}
