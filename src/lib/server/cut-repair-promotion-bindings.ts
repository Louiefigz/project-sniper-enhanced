import type { CutRepairPromotionActionV1 } from
  "@/lib/producer/contracts/cut-repair-promotion-transition";
import type { CutRepairReviewActionV1 } from
  "@/lib/producer/contracts/cut-repair-review-transition";
import { parseCutRepairRenderedCandidateV1 } from
  "@/lib/producer/contracts/cut-repair-rendered-candidate";
import type { ProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import {
  exactKeys,
  objectValue,
  sha256,
} from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { parseCutRepairRetimeV1 } from
  "@/lib/producer/contracts/cut-repair-retime";
import { parsePalmierCutRepairDispositionV1 } from
  "@/lib/producer/contracts/palmier-cut-repair-disposition";
import type { CutRepairPromotionInput } from
  "./producer-cut-repair-artifacts";

const LOCK_KEYS = [
  "schemaVersion", "approvedCutRevisionHash", "planContentHash",
  "timelineMapHash", "sourceSnapshotSetHash", "transcriptTimingHash",
  "cutApprovalReceiptHash", "cutReviewApprovalReceiptHash",
  "requiredCleanReviews", "workflowPolicy", "selectedApproval",
  "compatibilityAncestorHash", "parentPictureLockHash",
] as const;
const LOCK_REQUIRED = LOCK_KEYS.filter(
  (key) => key !== "compatibilityAncestorHash");

export interface PromotionCandidateBindings {
  invariantProofHash: string;
  sidecars: Record<string, string>;
  artifactHashes: Record<string, string>;
}

export interface PromotionBindingInput {
  proof: CutRepairPromotionInput;
  promotion: CutRepairPromotionActionV1;
  reviewAction: CutRepairReviewActionV1;
  review: ProjectRevision;
  parent: ProjectRevision;
}

function assertChildLock(
  value: unknown,
  input: PromotionBindingInput,
): string {
  const { promotion, review, reviewAction, parent } = input;
  const lock = objectValue(value, "cut repair child picture lock");
  exactKeys(lock, LOCK_KEYS, LOCK_REQUIRED, "cut repair child picture lock");
  const selected = objectValue(lock.selectedApproval, "child lock selected approval");
  const expectedApproval = promotion.selectedApproval;
  if (lock.schemaVersion !== 1
      || lock.approvedCutRevisionHash !== promotion.expectedReviewRevisionHash
      || lock.planContentHash !== review.planContentHash
      || lock.timelineMapHash !== review.timelineMapHash
      || lock.sourceSnapshotSetHash !== review.sourceSnapshotSetHash
      || lock.transcriptTimingHash !== review.transcriptTimingHash
      || lock.requiredCleanReviews !== 2
      || lock.workflowPolicy !== reviewAction.workflowPolicy
      || lock.parentPictureLockHash !== parent.pictureLockHash
      || canonicalJsonSha256(selected) !== canonicalJsonSha256(expectedApproval)) {
    throw new Error(
      "cut repair child lock does not bind review and selected-policy approval");
  }
  sha256(lock.cutApprovalReceiptHash, "child lock cut approval");
  sha256(lock.cutReviewApprovalReceiptHash, "child lock cut review approval");
  if (lock.compatibilityAncestorHash !== undefined) {
    sha256(lock.compatibilityAncestorHash, "child lock compatibility ancestor");
  }
  const observed = canonicalJsonSha256(lock);
  if (observed !== promotion.childPictureLockHash) {
    throw new Error("cut repair promotion substituted its child picture lock");
  }
  return observed;
}

function hashes(candidate: Record<string, unknown>): PromotionCandidateBindings {
  const values = {
    cutRepairCandidate: canonicalJsonSha256(candidate),
    cutRepairFragmentReceipt: canonicalJsonSha256(
      objectValue(candidate.fragmentReceipt, "fragment receipt")),
    cutRepairCompositeReceipt: canonicalJsonSha256(
      objectValue(candidate.compositeReceipt, "composite receipt")),
    cutRepairPictureLock: canonicalJsonSha256(
      objectValue(candidate.childPictureLock, "child picture lock")),
    cutRepairSupersession: canonicalJsonSha256(
      objectValue(candidate.supersessionReceipt, "supersession receipt")),
    captionRepairRevalidation: canonicalJsonSha256(
      objectValue(candidate.captionRevalidation, "caption revalidation")),
    palmierCutRepairDisposition: canonicalJsonSha256(
      objectValue(candidate.palmierDisposition, "Palmier disposition")),
    cutRepairInvariantProof: canonicalJsonSha256(
      objectValue(candidate.invariantProof, "invariant proof")),
  };
  const rendered = candidate.schemaVersion === 2
    ? canonicalJsonSha256(parseCutRepairRenderedCandidateV1(
      candidate.renderedCandidate))
    : null;
  const invariantProofHash = sha256(
    candidate.invariantProofHash, "candidate invariant proof hash");
  if (values.cutRepairInvariantProof !== invariantProofHash
      || (rendered !== null && candidate.renderedCandidateHash !== rendered)) {
    throw new Error("cut repair candidate invariant hash is stale");
  }
  const artifactHashes = {
    ...values,
    ...(rendered ? { cutRepairRenderedCandidate: rendered } : {}),
  };
  return {
    invariantProofHash,
    artifactHashes,
    sidecars: {
      pictureLock: values.cutRepairPictureLock,
      pictureLockSupersession: values.cutRepairSupersession,
      cutRepairFragmentReceipt: values.cutRepairFragmentReceipt,
      cutRepairCompositeReceipt: values.cutRepairCompositeReceipt,
      cutRepairInvariantProof: values.cutRepairInvariantProof,
      cutRepairCandidate: values.cutRepairCandidate,
      captionRepairRevalidation: values.captionRepairRevalidation,
      palmierCutRepairDisposition: values.palmierCutRepairDisposition,
      ...(rendered ? { cutRepairRenderedCandidate: rendered } : {}),
    },
  };
}

function assertRenderedReviewBinding(
  candidate: Record<string, unknown>,
  reviewAction: CutRepairReviewActionV1,
): void {
  if (candidate.schemaVersion !== 2) return;
  const rendered = parseCutRepairRenderedCandidateV1(
    candidate.renderedCandidate);
  if (rendered.operationHash !== reviewAction.operationHash
      || rendered.reviewPlanObjectHash !== reviewAction.reviewPlanObjectHash
      || rendered.reviewPlanContentHash !== reviewAction.reviewPlanContentHash
      || rendered.reviewTimelineMapHash !== reviewAction.reviewTimelineMapHash
      || rendered.reviewRenderGraphHash
        !== reviewAction.reviewRenderGraphHash) {
    throw new Error(
      "cut repair terminal media does not bind the exact reviewed plan");
  }
}

function assertRetimeBindings(
  candidate: Record<string, unknown>,
  reviewAction: CutRepairReviewActionV1,
): void {
  const fragment = objectValue(candidate.fragmentReceipt, "fragment receipt");
  const retime = parseCutRepairRetimeV1(
    objectValue(fragment.retime, "fragment retime"));
  const speedHash = canonicalJsonSha256(reviewAction.operation.speed);
  if (canonicalJsonSha256(retime.requestedSpeed) !== speedHash) {
    throw new Error("fragment retime does not bind the selected repair speed");
  }
  const palmier = parsePalmierCutRepairDispositionV1(
    candidate.palmierDisposition);
  if (palmier.selected
      && (canonicalJsonSha256(palmier.repairSpeed) !== speedHash
        || canonicalJsonSha256(palmier.repairRetime)
          !== canonicalJsonSha256(retime))) {
    throw new Error("Palmier projection and renderer retime disagree");
  }
}

/** Cross-bind review, original action, selected approval, and Python proof. */
export function promotionCandidateBindings(
  input: PromotionBindingInput,
): PromotionCandidateBindings {
  const { proof, promotion, reviewAction, review } = input;
  const candidate = objectValue(proof.candidate, "cut repair candidate");
  const evidence = objectValue(
    proof.promotionEvidence, "cut repair promotion evidence");
  if (review.workflowState !== "CUT_REVIEW"
      || review.parentRevisionHash !== reviewAction.expectedParentRevisionHash
      || promotion.reviewActionHash !== canonicalJsonSha256(reviewAction)
      || promotion.operationHash !== reviewAction.operationHash
      || promotion.selectionPolicyHash !== reviewAction.selectionPolicyHash
      || candidate.operationHash !== reviewAction.operationHash
      || canonicalJsonSha256(candidate) !== promotion.candidateHash
      || canonicalJsonSha256(evidence) !== promotion.promotionEvidenceHash) {
    throw new Error("cut repair promotion does not bind the exact review action");
  }
  assertRenderedReviewBinding(candidate, reviewAction);
  assertRetimeBindings(candidate, reviewAction);
  assertChildLock(candidate.childPictureLock, input);
  return hashes(candidate);
}
