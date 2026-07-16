import { planContentHash } from "@/lib/server/auto-edit-authority";
import { readFileSync } from "fs";
import { reconcileGraphicIds, type EditPlan } from "@/lib/producer/edit-plan";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import {
  checkpointReached,
  type AutoEditJob,
  type CheckpointUpdate,
} from "@/lib/server/auto-edit-job-store";
import type { AutoEditAuthoritySnapshot } from "@/lib/server/auto-edit-authority-snapshot";
import { brainModel, brainProvider, brainProviderLabel } from "../../_lib/ai-provider";
import type {
  AuthoringResult,
  AuthoringSessionMode,
  AuthoringStage,
} from "./authoring";
import { AUTHORING_TIMEOUT_MIN } from "./claude-authoring-process";
import {
  approvePrevisualCut,
  cutAuthorityEvidence,
  cutApprovalPath,
  validatePrevisualCut,
  verifyApprovedCut,
} from "./cut-approval";
import { AutoEditError, type AutoEditCtx, type Send } from "./stream";
import { runCutReviewLoop } from "./cut-review-loop";
import { verifyCutReviewApproval } from "./cut-review-approval";
import { markAuthoringSessionEstablished } from "./authoring-session-state";
import type {
  PalmierCheckpointOutcome,
  PalmierCheckpointSpec,
} from "./palmier-checkpoints";

interface AuthoringRuntime {
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
  reviewCut: typeof runCutReviewLoop;
  verifyReviewCut: typeof verifyCutReviewApproval;
  approveCut: typeof approvePrevisualCut;
  verifyCut: typeof verifyApprovedCut;
  bindSession?: typeof markAuthoringSessionEstablished;
  /** Courtesy Palmier publish — three-valued outcome, never throws. */
  checkpoint?: (
    ctx: AutoEditCtx,
    spec: PalmierCheckpointSpec,
    send: Send,
  ) => Promise<PalmierCheckpointOutcome>;
}

interface PlanState {
  fileHash: string;
  contentHash: string;
  authority: AutoEditAuthoritySnapshot;
}

function planState(run: AuthoringRuntime, deps: AuthoringStageDependencies): PlanState | null {
  const { planPath } = run.job.ctx;
  if (!deps.exists(planPath)) return null;
  const fileHash = deps.hashFile(planPath);
  const contentHash = planContentHash(planPath);
  if (!fileHash || !contentHash) return null;
  const authority = deps.authority(run.job.ctx);
  if (authority.planHash !== fileHash || authority.planContentHash !== contentHash) return null;
  return { fileHash, contentHash, authority };
}

function normalizeGraphicBindings(planPath: string): void {
  try {
    const value = JSON.parse(readFileSync(planPath, "utf8")) as EditPlan;
    if (!value || typeof value !== "object" || Array.isArray(value)) return;
    const normalized = reconcileGraphicIds(value).plan;
    if (normalized !== value) atomicWriteJsonSync(planPath, normalized);
  } catch {
    // Preserve the authoring result as the controlling failure. A malformed or
    // partial timeout draft is rejected by planState instead of masking the
    // deadline with a JSON parse error.
  }
}

function advanceAuthored(run: AuthoringRuntime, state: PlanState): void {
  run.job = run.io.advance({
    checkpoint: "plan_authored", phase: "planning_review",
    message: "Cuts were approved before visual planning; the complete plan now starts independent review.",
    planHash: state.fileHash, planningRound: 0, planningCycles: 0,
    authorityDigest: state.authority.digest,
  });
}

function timeoutMessage(result: AuthoringResult, stage: AuthoringStage): string {
  const brain = brainProviderLabel(result.provider);
  return `${stage} authoring timed out after ${AUTHORING_TIMEOUT_MIN} min — ${brain} was killed. ${result.errTail.slice(-300)}`;
}

function recoveredState(
  run: AuthoringRuntime,
  deps: AuthoringStageDependencies,
  beforeContentHash: string | undefined,
  result: AuthoringResult,
  stage: AuthoringStage,
): PlanState | null {
  const state = planState(run, deps);
  if (!state || state.contentHash === beforeContentHash) return null;
  run.io.send({
    event: "authoring_deadline_recovered", stage,
    provider: result.provider, model: brainModel(result.provider), ms: result.ms,
    planHash: state.fileHash, planContentHash: state.contentHash,
    note: `${stage} draft recovered only as a pre-approval candidate.`,
  });
  return state;
}

async function runWriter(
  run: AuthoringRuntime,
  deps: AuthoringStageDependencies,
  stage: AuthoringStage,
  sessionMode: AuthoringSessionMode,
): Promise<PlanState> {
  const { ctx } = run.job;
  const beforeContentHash = planContentHash(ctx.planPath);
  const provider = brainProvider();
  const brain = brainProviderLabel(provider);
  run.job = run.io.advance({
    checkpoint: "authoring", phase: "authoring",
    message: stage === "cut"
      ? `${brain} is approving transcript-safe cuts before any visual planning.`
      : `${brain} is adding retention and visual treatment without changing approved cuts.`,
  });
  run.io.send({
    event: "authoring_started", stage, provider,
    model: brainModel(provider), brain, workbench: "Palmier",
  });
  const result = await deps.author(ctx, run.io.send, stage, sessionMode);
  if (result.sessionEstablished && deps.bindSession) {
    run.job = deps.bindSession(run.job);
  }
  if (deps.exists(ctx.planPath)) normalizeGraphicBindings(ctx.planPath);
  let state = planState(run, deps);
  if (result.timedOut) {
    state = recoveredState(run, deps, beforeContentHash, result, stage);
    if (!state) throw new AutoEditError(timeoutMessage(result, stage));
  } else if (result.code !== 0) {
    throw new AutoEditError(
      `${brainProviderLabel(result.provider)} ${stage} authoring failed `
      + `(exit ${result.code}). ${result.errTail.slice(-300)}`,
    );
  }
  if (!state) throw new AutoEditError(
    `${brainProviderLabel(result.provider)} exited 0 but wrote no valid ${ctx.planPath}`,
  );
  run.io.send({
    event: "authoring_done", stage, provider: result.provider,
    model: brainModel(result.provider), ms: result.ms, authored: result.authored,
  });
  return state;
}

function invalidateForCut(run: AuthoringRuntime, reason: string): void {
  run.job = run.io.invalidate({
    checkpoint: "authoring", phase: "authoring", message: reason,
    planningRound: 0, planningCycles: 0,
  });
  run.io.send({ event: "checkpoint_invalidated", reason: "cut_approval_missing", message: reason });
}

async function reusableApprovedCut(
  run: AuthoringRuntime,
  deps: AuthoringStageDependencies,
): Promise<boolean> {
  if (!deps.exists(run.job.ctx.planPath) || !deps.exists(cutApprovalPath(run.job.ctx))) {
    return false;
  }
  try {
    const verdict = await deps.verifyCut(run.job.ctx, run.io.send);
    deps.verifyReviewCut(run.job.ctx, cutAuthorityEvidence(verdict));
    return true;
  } catch {
    return false;
  }
}

/**
 * A saved plan that lacks its cut-approval receipt but re-passes the
 * deterministic cut wall regains cut authority without re-authoring: the
 * receipt is minted from the fresh gate verdict — the exact shape the live
 * approval path writes (item 9a of docs/audits/GUI_LATENCY_TEARDOWN.md).
 */
async function mintRetroactiveCutApproval(
  run: AuthoringRuntime,
  deps: AuthoringStageDependencies,
): Promise<boolean> {
  const { ctx } = run.job;
  if (!deps.exists(ctx.planPath) || deps.exists(cutApprovalPath(ctx))) return false;
  try {
    const receipt = await deps.approveCut(ctx, run.io.send);
    run.io.send({
      event: "cut_receipt_minted", retroactive: true,
      planHash: receipt.planHash, cutTrackDigest: receipt.cutTrackDigest,
      message: "Saved plan passed the deterministic cut wall; its cut-approval receipt was minted retroactively.",
    });
    return true;
  } catch (error) {
    run.io.send({
      event: "cut_receipt_mint_skipped",
      reason: error instanceof Error ? error.message : String(error),
    });
    return false;
  }
}

async function resumableCutCandidate(
  run: AuthoringRuntime,
  deps: AuthoringStageDependencies,
  bootstrapped: boolean,
): Promise<boolean> {
  if (run.job.attempts <= 1 && !bootstrapped) return false;
  const before = planState(run, deps);
  if (!before) return false;
  try {
    await deps.validateCut(run.job.ctx, run.io.send);
  } catch (error) {
    run.io.send({
      event: "cut_candidate_rejected", attempt: run.job.attempts,
      reason: error instanceof Error ? error.message : String(error),
      fallback: "cut-writer",
    });
    return false;
  }
  const after = planState(run, deps);
  if (!after || after.authority.digest !== before.authority.digest) {
    run.io.send({
      event: "cut_candidate_rejected", attempt: run.job.attempts,
      reason: "cut candidate authority changed during resume validation",
      fallback: "cut-writer",
    });
    return false;
  }
  run.io.send({
    event: "cut_candidate_reused", attempt: run.job.attempts,
    planHash: after.fileHash,
    message: "The saved transcript cut passed the deterministic wall; independent cut review is restarting without re-authoring it.",
  });
  return true;
}

export async function runAuthorStage(
  run: AuthoringRuntime,
  deps: AuthoringStageDependencies,
): Promise<void> {
  const bootstrapped = checkpointReached(run.job.checkpoint, "plan_authored");
  if (bootstrapped) {
    if (await reusableApprovedCut(run, deps)) {
      run.io.send({
        event: "resume", stage: "authoring", checkpoint: run.job.checkpoint,
        message: "Using the saved visual plan and its controller-approved cut authority.",
      });
      return;
    }
    if (await mintRetroactiveCutApproval(run, deps)
        && await reusableApprovedCut(run, deps)) {
      run.io.send({
        event: "resume", stage: "authoring", checkpoint: run.job.checkpoint,
        message: "Saved plan re-passed the deterministic cut wall with its clean reviews intact; both writers are skipped.",
      });
      return;
    }
    invalidateForCut(run, "Saved plan has no valid controller cut approval; revalidating the cut before any re-authoring.");
  }
  let sessionMode: AuthoringSessionMode = run.job.attempts > 1
      && Boolean(run.job.ctx.brainSessionId)
    ? "resume" : "start";
  if (!await reusableApprovedCut(run, deps)) {
    const reusedCandidate = await resumableCutCandidate(run, deps, bootstrapped);
    if (!reusedCandidate) {
      await runWriter(run, deps, "cut", sessionMode);
      sessionMode = "resume";
    }
    await deps.reviewCut(run);
    await deps.approveCut(run.job.ctx, run.io.send);
    // Land the twice-reviewed cut in Palmier before visual authoring begins;
    // the courtesy publish never throws, so deferred/warned outcomes cannot
    // block the stage (~190 ms of MCP work when Palmier is open).
    await deps.checkpoint?.(run.job.ctx, { stage: "cut", round: 0 }, run.io.send);
  } else {
    run.io.send({
      event: "resume", stage: "cut_approval",
      message: "Approved cut authority is intact; resuming downstream visual authoring.",
    });
  }
  await deps.verifyCut(run.job.ctx, run.io.send);
  const state = await runWriter(run, deps, "visual", sessionMode);
  await deps.verifyCut(run.job.ctx, run.io.send);
  advanceAuthored(run, state);
}
