import { createHash } from "node:crypto";
import path from "node:path";
import { atomicWriteFileSync } from "@/lib/server/atomic-file";
import {
  canonicalJson,
  canonicalJsonSha256,
  fileSha256,
} from "@/lib/server/auto-edit-hash";
import { promoteCutRepairReviewSync } from
  "@/lib/server/cut-repair-promotion-store";
import {
  loadCutRepairExecutionPackageSync,
  type CutRepairExecutionPackageV1,
} from "@/lib/server/cut-repair-execution-package-store";
import { recoverCutRepairReviewSync } from
  "@/lib/server/cut-repair-review-store";
import type { CutRepairTransitionOutcome } from
  "@/lib/server/cut-repair-transition-model";
import {
  assertCutRepairRecoveryPackageSync,
  cutRepairTransitionChildSync,
} from "@/lib/server/cut-repair-transition-reconciliation";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "@/lib/server/producer-authority-files";
import { resolveProducerAuthorityHeadSync } from
  "@/lib/server/producer-revision-head";
import type { CutRepairPromotionInput } from
  "@/lib/server/producer-cut-repair-artifacts";
import type { CutRepairDirectiveV1 } from "./cut-repair-route-policy";

function targetHash(directive: CutRepairDirectiveV1): string {
  return canonicalJsonSha256({
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    target: directive.target,
  });
}

function assertRecoveryHead(
  producerDir: string,
  value: CutRepairExecutionPackageV1,
  head: string,
): void {
  assertCutRepairRecoveryPackageSync({
    producerDir,
    reviewIdempotencyKey: value.reviewAction.idempotencyKey,
    promotionIdempotencyKey: value.promotionAction.idempotencyKey,
    expectedReviewRevisionHash:
      value.promotionAction.expectedReviewRevisionHash,
  });
  const finalChild = cutRepairTransitionChildSync(
    producerDir, "promotion", value.promotionAction.idempotencyKey);
  if (head === value.parentRevisionHash) {
    throw new Error(
      "CUT_REVIEW_NOT_STAGED: promotion cannot create its own review");
  }
  if (![value.promotionAction.expectedReviewRevisionHash, finalChild]
    .includes(head)) {
    throw new Error("execution package is stale for the selected revision");
  }
}

function publishCompatibilityPlan(
  producerDir: string,
  value: CutRepairExecutionPackageV1,
): void {
  const paths = producerAuthorityPaths(producerDir);
  const plan = assertObjectHashSync(
    paths.objects.plans, value.reviewAction.reviewPlanObjectHash);
  const bytes = canonicalJson(plan);
  const observed = createHash("sha256").update(bytes).digest("hex");
  if (observed !== value.reviewAction.reviewPlanObjectHash) {
    throw new Error("stored cut repair compatibility plan hash changed");
  }
  const destination = path.join(producerDir, "edit_plan.json");
  if (fileSha256(destination) !== observed) {
    atomicWriteFileSync(destination, bytes);
  }
  if (fileSha256(destination) !== observed) {
    throw new Error("cut repair compatibility plan did not publish exactly");
  }
}

function executionOutcome(
  directive: CutRepairDirectiveV1,
  value: CutRepairExecutionPackageV1,
  review: CutRepairTransitionOutcome,
  promoted: CutRepairTransitionOutcome,
): Record<string, unknown> {
  return {
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    routeStatus: "two-step-promotion-committed",
    packageHash: directive.packageHash,
    parentRevisionHash: value.parentRevisionHash,
    reviewRevisionHash: review.childRevisionHash,
    promotedRevisionHash: promoted.childRevisionHash,
    reviewReceiptHash: review.receiptHash,
    promotionReceiptHash: promoted.receiptHash,
    terminalAuthority: value.candidate.schemaVersion === 2
      ? "rendered-plan-media-activated"
      : "legacy-diagnostic-composite",
    finalMediaActivated: value.candidate.schemaVersion === 2,
  };
}

/** Execute/recover only a fully sealed two-phase package. */
export async function runCutRepairExecution(
  producerDir: string,
  _manifestPath: string,
  directive: CutRepairDirectiveV1,
): Promise<Record<string, unknown>> {
  if (directive.mode !== "execute" || !directive.packageHash) {
    throw new Error("cut repair execution requires one packageHash");
  }
  const value = loadCutRepairExecutionPackageSync(
    producerDir, directive.packageHash);
  if (value.targetDirectiveHash !== targetHash(directive)) {
    throw new Error("execution package targets another phrase occurrence");
  }
  const before = resolveProducerAuthorityHeadSync(producerDir);
  assertRecoveryHead(producerDir, value, before);
  const review = recoverCutRepairReviewSync(
    producerDir, value.reviewAction.idempotencyKey);
  if (!["committed", "replayed"].includes(review.status)
      || review.childRevisionHash
        !== value.promotionAction.expectedReviewRevisionHash) {
    throw new Error("cut repair review transition lost expected-parent CAS");
  }
  const proof: CutRepairPromotionInput = {
    candidate: value.candidate,
    promotionEvidence: value.promotionEvidence,
  };
  const promoted = promoteCutRepairReviewSync({
    producerDir,
    action: value.promotionAction,
    proof,
  });
  if (!["committed", "replayed"].includes(promoted.status)) {
    throw new Error("cut repair promotion did not commit");
  }
  if (resolveProducerAuthorityHeadSync(producerDir)
      !== promoted.childRevisionHash) {
    throw new Error("newer authority superseded this cut repair package");
  }
  if (value.candidate.schemaVersion !== 2) {
    publishCompatibilityPlan(producerDir, value);
  }
  return executionOutcome(directive, value, review, promoted);
}
