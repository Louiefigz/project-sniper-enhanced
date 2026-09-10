import { planContentHash } from "@/lib/server/auto-edit-authority";
import type { AutoEditAuthoritySnapshot } from
  "@/lib/server/auto-edit-authority-snapshot";
import type { AutoEditJob } from "@/lib/server/auto-edit-job-store";
import { cutApprovalPath } from "./cut-approval";
import { requireCompatibilityCutAuthority } from "./compatibility-cut-authority";
import type { AutoEditCtx, Send } from "./stream";
import type { CompatibilityPictureLockResult } from "./compatibility-picture-lock";

export interface CutPlanState {
  fileHash: string;
  contentHash: string;
  authority: AutoEditAuthoritySnapshot;
}

interface CutRuntime {
  job: AutoEditJob;
  io: { send: Send };
}

type CutApprover = (ctx: AutoEditCtx, send?: Send) => Promise<{
  planHash: string;
  cutTrackDigest: string;
}>;

interface CutStateDependencies {
  exists: (filePath: string) => boolean;
  hashFile: (filePath: string) => string | undefined;
  authority: (ctx: AutoEditCtx) => AutoEditAuthoritySnapshot;
  validateCut: (ctx: AutoEditCtx, send?: Send) => Promise<unknown>;
  validateSavedCut: (ctx: AutoEditCtx, send?: Send) => Promise<unknown>;
  approveCut: CutApprover;
  approveSavedCut: CutApprover;
  verifyCut: Parameters<typeof requireCompatibilityCutAuthority>[2]["verifyCut"];
  verifyReviewCut:
    Parameters<typeof requireCompatibilityCutAuthority>[2]["verifyReviewCut"];
  lockCut: Parameters<typeof requireCompatibilityCutAuthority>[2]["lockCut"];
}

export function currentCutPlanState(
  run: CutRuntime,
  deps: CutStateDependencies,
): CutPlanState | null {
  const { planPath } = run.job.ctx;
  if (!deps.exists(planPath)) return null;
  const fileHash = deps.hashFile(planPath);
  const contentHash = planContentHash(planPath);
  if (!fileHash || !contentHash) return null;
  const authority = deps.authority(run.job.ctx);
  if (authority.planHash !== fileHash
      || authority.planContentHash !== contentHash) return null;
  return { fileHash, contentHash, authority };
}

export async function reusableApprovedCut(
  run: CutRuntime,
  deps: CutStateDependencies,
): Promise<CompatibilityPictureLockResult | null> {
  const { ctx } = run.job;
  if (!deps.exists(ctx.planPath) || !deps.exists(cutApprovalPath(ctx))) {
    return null;
  }
  try {
    return await requireCompatibilityCutAuthority(ctx, run.io.send, deps);
  } catch {
    return null;
  }
}

export async function mintRetroactiveCutApproval(
  run: CutRuntime,
  deps: CutStateDependencies,
): Promise<boolean> {
  const { ctx } = run.job;
  if (!deps.exists(ctx.planPath) || deps.exists(cutApprovalPath(ctx))) return false;
  try {
    const approve = run.job.reviewSavedPlan
      ? deps.approveSavedCut : deps.approveCut;
    const receipt = await approve(ctx, run.io.send);
    run.io.send({
      event: "cut_receipt_minted", retroactive: true,
      planHash: receipt.planHash, cutTrackDigest: receipt.cutTrackDigest,
      message: "Saved plan passed the deterministic cut wall; its cut-approval receipt was minted retroactively.",
    });
    return true;
  } catch (error) {
    if (run.job.reviewSavedPlan) throw error;
    run.io.send({
      event: "cut_receipt_mint_skipped",
      reason: error instanceof Error ? error.message : String(error),
    });
    return false;
  }
}

export async function resumableCutCandidate(
  run: CutRuntime,
  deps: CutStateDependencies,
  bootstrapped: boolean,
): Promise<boolean> {
  if (run.job.attempts <= 1 && !bootstrapped) return false;
  const before = currentCutPlanState(run, deps);
  if (!before) return false;
  try {
    const validate = run.job.reviewSavedPlan
      ? deps.validateSavedCut : deps.validateCut;
    await validate(run.job.ctx, run.io.send);
  } catch (error) {
    if (run.job.reviewSavedPlan) throw error;
    run.io.send({
      event: "cut_candidate_rejected", attempt: run.job.attempts,
      reason: error instanceof Error ? error.message : String(error),
      fallback: "cut-writer",
    });
    return false;
  }
  const after = currentCutPlanState(run, deps);
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

export function unchangedSavedPlanState(
  run: CutRuntime,
  deps: CutStateDependencies,
  expectedHash: string | undefined,
): CutPlanState | null {
  if (!expectedHash) return null;
  const state = currentCutPlanState(run, deps);
  return state?.fileHash === expectedHash ? state : null;
}
