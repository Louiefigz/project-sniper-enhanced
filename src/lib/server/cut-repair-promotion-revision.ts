import {
  parseProjectRevisionV1,
  parseProjectRevisionV2,
  type ProjectRevision,
  type ProjectRevisionV1,
  type ProjectRevisionV2,
} from "@/lib/producer/contracts/project-revision";
import { revisionV2WriteFrom } from "./producer-plan-authority";

export interface PromotionRevisionContext {
  review: ProjectRevision;
  action: {
    expectedReviewRevisionHash: string;
    childPictureLockHash: string;
    promotionEvidenceHash: string;
  };
  reviewReceiptHash: string;
  bindings: { sidecars: Record<string, string> };
}

/** Build the exact locked child while retaining the review plan identity. */
export function buildPromotedRevisionV2(
  input: PromotionRevisionContext,
  actionHash: string,
  planObjectHash: string,
): ProjectRevisionV2 {
  return parseProjectRevisionV2({
    ...revisionV2WriteFrom(input.review),
    schemaVersion: 2,
    planObjectHash,
    parentRevisionHash: input.action.expectedReviewRevisionHash,
    pictureLockHash: input.action.childPictureLockHash,
    workflowState: "PICTURE_LOCKED",
    authoritativeSidecars: {
      ...input.review.authoritativeSidecars,
      cutRepairReviewReceipt: input.reviewReceiptHash,
      ...input.bindings.sidecars,
      cutRepairPromotionEvidence: input.action.promotionEvidenceHash,
      cutRepairPromotionAction: actionHash,
    },
  });
}

/** Reconstruct legacy immutable children for read/recovery compatibility. */
export function buildLegacyPromotedRevisionV1(
  input: PromotionRevisionContext,
  actionHash: string,
): ProjectRevisionV1 {
  const v2 = buildPromotedRevisionV2(
    input, actionHash, input.review.planContentHash);
  return parseProjectRevisionV1({
    ...revisionV2WriteFrom(v2),
    schemaVersion: 1,
  });
}
