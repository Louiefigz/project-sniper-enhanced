import {
  parseCutRepairPromotionActionV1,
  type CutRepairSelectedApprovalV1,
} from "@/lib/producer/contracts/cut-repair-promotion-transition";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import { objectValue } from "@/lib/producer/contracts/validation";
import type { StoredCutRepairAudition } from
  "@/lib/server/cut-repair-audition-store";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import {
  storeCutRepairExecutionPackageSync,
  type StoredCutRepairExecutionPackage,
} from "@/lib/server/cut-repair-execution-package-store";
import type { StoredCutRepairPreparation } from
  "@/lib/server/cut-repair-preparation-store";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "@/lib/server/producer-authority-files";
import {
  buildCutRepairPromotionProofV2,
  type PromotionProofBuildInput,
} from "./cut-repair-promotion-proof";
import type { CutRepairDirectiveV1 } from "./cut-repair-route-policy";

interface ApprovalSealServices {
  buildProof: (
    value: PromotionProofBuildInput,
  ) => Promise<Record<string, unknown>>;
  storePackage: typeof storeCutRepairExecutionPackageSync;
}

export interface ApprovalSealInput {
  producerDir: string;
  directive: CutRepairDirectiveV1;
  stored: StoredCutRepairPreparation;
  reviewed: { revisionHash: string; receiptHash: string };
  audition: StoredCutRepairAudition;
  evidence: Record<string, unknown>;
  services?: ApprovalSealServices;
}

const DEFAULT_SERVICES: ApprovalSealServices = {
  buildProof: buildCutRepairPromotionProofV2,
  storePackage: storeCutRepairExecutionPackageSync,
};

function selectedApproval(
  audition: StoredCutRepairAudition,
): CutRepairSelectedApprovalV1 {
  return {
    approver: "operator",
    approvalPolicyHash: audition.approvalPolicyHash,
    approvalReceiptHash: audition.receiptHash,
  };
}

interface PromotionActionInput {
  directive: CutRepairDirectiveV1;
  stored: StoredCutRepairPreparation;
  reviewRevisionHash: string;
  approval: CutRepairSelectedApprovalV1;
  candidate: Record<string, unknown>;
  evidence: Record<string, unknown>;
}

function promotionAction(input: PromotionActionInput) {
  const reviewAction = input.stored.package.proposedReviewAction;
  return parseCutRepairPromotionActionV1({
    schemaVersion: 1,
    kind: "cut-repair-promotion-action",
    idempotencyKey: input.directive.idempotencyKey,
    expectedReviewRevisionHash: input.reviewRevisionHash,
    reviewActionHash: canonicalJsonSha256(reviewAction),
    operationHash: reviewAction.operationHash,
    selectionPolicyHash: reviewAction.selectionPolicyHash,
    selectedApproval: input.approval,
    childPictureLockHash: input.candidate.childPictureLockHash,
    candidateHash: canonicalJsonSha256(input.candidate),
    promotionEvidenceHash: canonicalJsonSha256(input.evidence),
    requestedAt: input.directive.requestedAt,
  });
}

function executionPackage(
  stored: StoredCutRepairPreparation,
  action: ReturnType<typeof promotionAction>,
  candidate: Record<string, unknown>,
  evidence: Record<string, unknown>,
) {
  return {
    schemaVersion: 1,
    kind: "cut-repair-execution-package",
    targetDirectiveHash: stored.package.targetDirectiveHash,
    contextAuthorityHash: stored.package.contextAuthorityHash,
    parentRevisionHash: stored.package.parentRevisionHash,
    reviewAction: stored.package.proposedReviewAction,
    promotionAction: action,
    candidate,
    promotionEvidence: evidence,
  };
}

function assertRenderedCandidate(
  candidate: Record<string, unknown>,
  stored: StoredCutRepairPreparation,
): void {
  const rendered = objectValue(
    candidate.renderedCandidate, "promotion rendered candidate");
  if (candidate.schemaVersion !== 2
      || rendered.candidateSha256
        !== stored.package.reviewCandidateMediaSha256
      || canonicalJsonSha256(rendered)
        !== stored.package.reviewCandidateDescriptorHash) {
    throw new Error("promotion proof substituted the reviewed full-plan media");
  }
}

/** Build the V2 proof, then seal action/package without executing either. */
export async function sealCutRepairPromotionPackage(
  input: ApprovalSealInput,
): Promise<StoredCutRepairExecutionPackage> {
  const services = input.services ?? DEFAULT_SERVICES;
  const paths = producerAuthorityPaths(input.producerDir);
  const reviewRevision = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, input.reviewed.revisionHash));
  const approval = selectedApproval(input.audition);
  const candidate = await services.buildProof({
    producerDir: input.producerDir,
    preparation: input.stored.package,
    reviewRevision,
    reviewRevisionHash: input.reviewed.revisionHash,
    reviewReceiptHash: input.reviewed.receiptHash,
    promotionEvidence: input.evidence,
    selectedApproval: approval,
  });
  assertRenderedCandidate(candidate, input.stored);
  const action = promotionAction({
    directive: input.directive,
    stored: input.stored,
    reviewRevisionHash: input.reviewed.revisionHash,
    approval,
    candidate,
    evidence: input.evidence,
  });
  return services.storePackage({
    producerDir: input.producerDir,
    preparationHash: input.stored.packageHash,
    value: executionPackage(
      input.stored, action, candidate, input.evidence),
  });
}
