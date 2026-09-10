import {
  parseCutRepairPromotionActionV1,
  type CutRepairPromotionActionV1,
} from "@/lib/producer/contracts/cut-repair-promotion-transition";
import { parseCutRepairReviewActionV1 } from
  "@/lib/producer/contracts/cut-repair-review-transition";
import { parseCutRepairTransitionReceiptV1 } from
  "@/lib/producer/contracts/cut-repair-transition-receipt";
import {
  parseProjectRevision,
  type ProjectRevision,
} from "@/lib/producer/contracts/project-revision";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  promotionCandidateBindings,
  type PromotionCandidateBindings,
} from "./cut-repair-promotion-bindings";
import { buildPromotedRevisionV2 } from
  "./cut-repair-promotion-revision";
import { recoverCutRepairReviewSync } from "./cut-repair-review-store";
import {
  materializeCutRepairTransitionSync,
  type CutRepairTransitionHooks,
  type CutRepairTransitionRecord,
} from "./cut-repair-transition-store";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "./producer-authority-files";
import {
  storeCutRepairPromotionByHashSync,
  type CutRepairPromotionInput,
} from "./producer-cut-repair-artifacts";
import {
  assertRevisionPlanObjectSync,
  revisionV2WriteFrom,
  writeProjectRevisionV2Sync,
} from "./producer-plan-authority";

export interface CutRepairPromotionTransitionInput {
  producerDir: string;
  action: unknown;
  proof: CutRepairPromotionInput;
}

export interface PromotionContext {
  action: CutRepairPromotionActionV1;
  reviewAction: ReturnType<typeof parseCutRepairReviewActionV1>;
  review: ProjectRevision;
  parent: ProjectRevision;
  bindings: PromotionCandidateBindings;
  reviewReceiptHash: string;
}

/** Reopen every immutable authority required by promotion. */
export function cutRepairPromotionContextSync(
  input: CutRepairPromotionTransitionInput,
): PromotionContext {
  const action = parseCutRepairPromotionActionV1(input.action);
  const paths = producerAuthorityPaths(input.producerDir);
  const review = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, action.expectedReviewRevisionHash));
  const reviewActionHash = review.authoritativeSidecars.cutRepairReviewAction;
  if (reviewActionHash !== action.reviewActionHash) {
    throw new Error("promotion expected review action is not authoritative");
  }
  const reviewAction = parseCutRepairReviewActionV1(assertObjectHashSync(
    paths.objects.cutRepairs, reviewActionHash));
  const reviewOutcome = recoverCutRepairReviewSync(
    input.producerDir, reviewAction.idempotencyKey);
  if (!["committed", "replayed"].includes(reviewOutcome.status)
      || reviewOutcome.childRevisionHash !== action.expectedReviewRevisionHash
      || !reviewOutcome.receiptHash) {
    throw new Error("cut repair review transition is not durably committed");
  }
  const parent = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, reviewAction.expectedParentRevisionHash));
  if (parent.workflowState !== "PICTURE_LOCKED" || !parent.pictureLockHash) {
    throw new Error("cut repair original parent is not PICTURE_LOCKED");
  }
  return {
    action,
    reviewAction,
    review,
    parent,
    bindings: promotionCandidateBindings({
      proof: input.proof, promotion: action, reviewAction, review, parent,
    }),
    reviewReceiptHash: reviewOutcome.receiptHash,
  };
}

function promotionReceipt(
  value: PromotionContext,
  actionHash: string,
  revisionHash: string,
) {
  return parseCutRepairTransitionReceiptV1({
    schemaVersion: 1,
    kind: "cut-repair-transition-receipt",
    status: "PICTURE_LOCKED_COMMITTED",
    idempotencyKey: value.action.idempotencyKey,
    actionHash,
    expectedParentRevisionHash: value.action.expectedReviewRevisionHash,
    childRevisionHash: revisionHash,
    originalPictureLockedParentHash:
      value.reviewAction.expectedParentRevisionHash,
    operationHash: value.action.operationHash,
    selectionPolicyHash: value.action.selectionPolicyHash,
    childPictureLockHash: value.action.childPictureLockHash,
    recordedAt: value.action.requestedAt,
  });
}

function storeProof(
  input: CutRepairPromotionTransitionInput,
  value: PromotionContext,
  revision: ProjectRevision,
): Record<string, string> {
  const paths = producerAuthorityPaths(input.producerDir);
  const stored = storeCutRepairPromotionByHashSync({
    paths,
    producerDir: input.producerDir,
    input: input.proof,
    operation: value.reviewAction.operation,
    revision,
    invariantProofHash: value.bindings.invariantProofHash,
  });
  const expected = {
    ...value.bindings.artifactHashes,
    cutRepairPromotionEvidence: value.action.promotionEvidenceHash,
  };
  if (Object.entries(expected).some(
    ([key, hash]) => stored[key] !== hash,
  )) {
    throw new Error("stored cut repair promotion proof changed identity");
  }
  return stored;
}

/** Materialize one immutable promotion record without advancing its head. */
export function materializeCutRepairPromotionSync(
  input: CutRepairPromotionTransitionInput,
  hooks: CutRepairTransitionHooks,
): CutRepairTransitionRecord {
  const value = cutRepairPromotionContextSync(input);
  const paths = producerAuthorityPaths(input.producerDir);
  const action = writeAuthorityObjectSync(paths.objects.cutRepairs, value.action);
  const plan = assertRevisionPlanObjectSync(paths, value.review)
    ?? assertObjectHashSync(
      paths.objects.plans, value.reviewAction.reviewPlanObjectHash);
  const child = writeProjectRevisionV2Sync({
    paths,
    planObject: plan,
    revision: revisionV2WriteFrom(buildPromotedRevisionV2(
      value, action.hash, canonicalJsonSha256(plan))),
  });
  const proof = storeProof(input, value, child.revision);
  const receipt = writeAuthorityObjectSync(
    paths.objects.receipts,
    promotionReceipt(value, action.hash, child.revisionHash),
  );
  return materializeCutRepairTransitionSync(input.producerDir, {
    schemaVersion: 1,
    kind: "cut-repair-transition-record",
    transition: "promotion",
    idempotencyKey: value.action.idempotencyKey,
    actionHash: action.hash,
    expectedParentRevisionHash: value.action.expectedReviewRevisionHash,
    childRevisionHash: child.revisionHash,
    originalPictureLockedParentHash:
      value.reviewAction.expectedParentRevisionHash,
    receiptHash: receipt.hash,
    artifactHashes: {
      action: action.hash,
      reviewAction: value.action.reviewActionHash,
      reviewRevision: value.action.expectedReviewRevisionHash,
      reviewReceipt: value.reviewReceiptHash,
      plan: child.planObjectHash,
      revision: child.revisionHash,
      receipt: receipt.hash,
      ...proof,
    },
    recordedAt: value.action.requestedAt,
  }, hooks);
}

/** Reopen promotion inputs using only hashes captured in its durable record. */
export function reopenCutRepairPromotionContextSync(
  producerDir: string,
  record: CutRepairTransitionRecord,
): { value: PromotionContext; revision: ProjectRevision } {
  const paths = producerAuthorityPaths(producerDir);
  const hashes = record.artifactHashes;
  const action = parseCutRepairPromotionActionV1(assertObjectHashSync(
    paths.objects.cutRepairs, hashes.action));
  const candidate = assertObjectHashSync(
    paths.objects.cutRepairs, hashes.cutRepairCandidate);
  const promotionEvidence = assertObjectHashSync(
    paths.objects.cutRepairs, hashes.cutRepairPromotionEvidence);
  const value = cutRepairPromotionContextSync({
    producerDir,
    action,
    proof: { candidate, promotionEvidence },
  });
  const revision = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, hashes.revision));
  return { value, revision };
}
