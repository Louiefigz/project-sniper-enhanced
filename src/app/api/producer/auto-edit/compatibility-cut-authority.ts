import {
  cutAuthorityEvidence,
  type verifyApprovedCut,
} from "./cut-approval";
import type { verifyCutReviewApproval } from "./cut-review-approval";
import type { mintCompatibilityPictureLock } from "./compatibility-picture-lock";
import type { AutoEditCtx, Send } from "./stream";

export interface CompatibilityCutDependencies {
  verifyCut: typeof verifyApprovedCut;
  verifyReviewCut: typeof verifyCutReviewApproval;
  lockCut: typeof mintCompatibilityPictureLock;
}

/** Verify both legacy cut authorities, then mint/reuse their immutable P1 lock. */
export async function requireCompatibilityCutAuthority(
  ctx: AutoEditCtx,
  send: Send,
  deps: CompatibilityCutDependencies,
): ReturnType<typeof mintCompatibilityPictureLock> {
  const verdict = await deps.verifyCut(ctx, send);
  const review = deps.verifyReviewCut(ctx, cutAuthorityEvidence(verdict));
  const result = await deps.lockCut(ctx, verdict, review);
  send({
    event: "compatibility_picture_lock",
    pictureLockHash: result.hash,
    timelineMapHash: result.lock.timelineMapHash,
    projectionReceiptHash: result.projectionHash,
    reused: result.reused,
  });
  return result;
}
