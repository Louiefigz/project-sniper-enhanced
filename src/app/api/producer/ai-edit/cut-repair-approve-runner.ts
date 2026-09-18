import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import { sha256 } from "@/lib/producer/contracts/validation";
import {
  storeCutRepairAuditionReceiptSync,
  type StoredCutRepairAudition,
} from "@/lib/server/cut-repair-audition-store";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import type { StoredCutRepairExecutionPackage } from
  "@/lib/server/cut-repair-execution-package-store";
import {
  loadCutRepairPreparationByHashSync,
  type StoredCutRepairPreparation,
} from "@/lib/server/cut-repair-preparation-store";
import { recoverCutRepairReviewSync } from
  "@/lib/server/cut-repair-review-store";
import type { CutRepairTransitionOutcome } from
  "@/lib/server/cut-repair-transition-model";
import { assertCutRepairApprovalAdmissionSync } from
  "@/lib/server/cut-repair-transition-reconciliation";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "@/lib/server/producer-authority-files";
import { validateCutRepairPromotionEvidence } from
  "@/lib/server/producer-cut-repair-promotion-evidence";
import { resolveProducerAuthorityHeadSync } from
  "@/lib/server/producer-revision-head";
import {
  loadCutRepairCandidateQc,
  type CutRepairAutomatedQcPass,
} from "./cut-repair-candidate-qc-runner";
import { sealCutRepairPromotionPackage } from
  "./cut-repair-approval-sealer";
import type { CutRepairDirectiveV1 } from "./cut-repair-route-policy";

interface ApprovalServices {
  loadPreparation: (
    producerDir: string,
    preparationHash: string,
  ) => StoredCutRepairPreparation;
  loadQc: (
    producerDir: string,
    preparationHash: string,
  ) => Promise<CutRepairAutomatedQcPass>;
  recoverReview: (
    producerDir: string,
    idempotencyKey: string,
  ) => CutRepairTransitionOutcome;
  storeAudition: typeof storeCutRepairAuditionReceiptSync;
  sealPackage: typeof sealCutRepairPromotionPackage;
}

const DEFAULT_SERVICES: ApprovalServices = {
  loadPreparation: loadCutRepairPreparationByHashSync,
  loadQc: loadCutRepairCandidateQc,
  recoverReview: recoverCutRepairReviewSync,
  storeAudition: storeCutRepairAuditionReceiptSync,
  sealPackage: sealCutRepairPromotionPackage,
};

function targetHash(directive: CutRepairDirectiveV1): string {
  return canonicalJsonSha256({
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    target: directive.target,
  });
}

function assertQc(
  stored: StoredCutRepairPreparation,
  qc: CutRepairAutomatedQcPass,
): void {
  const value = stored.package;
  if (qc.preparationHash !== stored.packageHash
      || qc.candidateDescriptorHash !== value.reviewCandidateDescriptorHash
      || qc.operationHash !== value.proposedReviewAction.operationHash
      || qc.candidateCompositeSha256 !== value.reviewCandidateMediaSha256
      || qc.operatorAuditionProduced !== false) {
    throw new Error("stored automated QC targets another candidate");
  }
}

function promotionEvidence(
  qc: CutRepairAutomatedQcPass,
  audition: StoredCutRepairAudition,
  operation: unknown,
): Record<string, unknown> {
  const value = {
    schemaVersion: 1,
    kind: "cut-repair-promotion-evidence",
    operationHash: qc.operationHash,
    candidateCompositeSha256: qc.candidateCompositeSha256,
    alignment: qc.alignment,
    vad: qc.vad,
    retranscription: qc.retranscription,
    seam: qc.seam,
    audition: audition.item,
  };
  validateCutRepairPromotionEvidence(
    value, operation, qc.candidateCompositeSha256);
  return value;
}

function assertReview(
  producerDir: string,
  stored: StoredCutRepairPreparation,
  review: CutRepairTransitionOutcome,
): { revisionHash: string; receiptHash: string } {
  if (!["committed", "replayed"].includes(review.status)
      || !review.receiptHash) {
    throw new Error("CUT_REVIEW_NOT_STAGED: approve cannot create its review");
  }
  if (resolveProducerAuthorityHeadSync(producerDir)
      !== review.childRevisionHash) {
    throw new Error("CUT_REVIEW_NOT_CURRENT: approve cannot rebase a repair");
  }
  const action = stored.package.proposedReviewAction;
  const paths = producerAuthorityPaths(producerDir);
  const revision = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, review.childRevisionHash));
  if (revision.workflowState !== "CUT_REVIEW"
      || revision.parentRevisionHash !== stored.package.parentRevisionHash
      || revision.authoritativeSidecars.cutRepairReviewAction
        !== canonicalJsonSha256(action)) {
    throw new Error("stored CUT_REVIEW is not this preparation package");
  }
  return {
    revisionHash: review.childRevisionHash,
    receiptHash: review.receiptHash,
  };
}

function outcome(
  stored: StoredCutRepairPreparation,
  qc: CutRepairAutomatedQcPass,
  audition: StoredCutRepairAudition,
  sealed: StoredCutRepairExecutionPackage,
): Record<string, unknown> {
  return {
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    routeStatus: "promotion-package-sealed",
    preparationHash: stored.packageHash,
    automatedQcBundleHash: qc.automatedQcBundleHash,
    auditionReceiptHash: audition.receiptHash,
    promotionActionHash: sealed.promotionActionHash,
    packageHash: sealed.packageHash,
    executed: false,
    replayed: sealed.replayed,
  };
}

/** Seal explicit approval into a package; never advance or activate it. */
export async function runCutRepairApproval(
  producerDir: string,
  _manifestPath: string,
  directive: CutRepairDirectiveV1,
  services: ApprovalServices = DEFAULT_SERVICES,
): Promise<Record<string, unknown>> {
  if (directive.mode !== "approve" || !directive.packageHash
      || !directive.idempotencyKey || !directive.requestedAt
      || !directive.audition) {
    throw new Error("cut repair approval requires package, identity, and audition");
  }
  const stored = services.loadPreparation(
    producerDir, directive.packageHash);
  if (stored.packageHash !== directive.packageHash
      || stored.package.targetDirectiveHash !== targetHash(directive)) {
    throw new Error("preparation package targets another phrase occurrence");
  }
  const qc = await services.loadQc(producerDir, stored.packageHash);
  assertQc(stored, qc);
  assertCutRepairApprovalAdmissionSync(
    producerDir, stored.package.proposedReviewAction.idempotencyKey);
  const review = services.recoverReview(
    producerDir, stored.package.proposedReviewAction.idempotencyKey);
  const reviewed = assertReview(producerDir, stored, review);
  const audition = services.storeAudition({
    producerDir,
    operationHash: stored.package.proposedReviewAction.operationHash,
    expected: {
      preparationHash: stored.packageHash,
      candidateDescriptorHash:
        stored.package.reviewCandidateDescriptorHash,
      candidateSha256: stored.package.reviewCandidateMediaSha256,
    },
    attestation: directive.audition,
  });
  const evidence = promotionEvidence(
    qc, audition, stored.package.proposedReviewAction.operation);
  const sealed = await services.sealPackage({
    producerDir,
    directive,
    stored,
    reviewed,
    audition,
    evidence,
  });
  sha256(sealed.packageHash, "sealed execution package");
  return outcome(stored, qc, audition, sealed);
}

export type { ApprovalServices as CutRepairApprovalServices };
