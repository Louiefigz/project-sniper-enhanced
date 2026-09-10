import {
  existsSync,
  lstatSync,
  realpathSync,
} from "node:fs";
import path from "node:path";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import {
  loadCutRepairPreparationByHashSync,
  type StoredCutRepairPreparation,
} from "@/lib/server/cut-repair-preparation-store";
import {
  stageCutRepairReviewSync,
} from "@/lib/server/cut-repair-review-store";
import type { CutRepairTransitionOutcome } from
  "@/lib/server/cut-repair-transition-model";
import {
  assertCutRepairReviewRecoverySync,
  cutRepairTransitionChildSync,
} from "@/lib/server/cut-repair-transition-reconciliation";
import { producerAuthorityPaths } from
  "@/lib/server/producer-authority-files";
import { resolveProducerAuthorityHeadSync } from
  "@/lib/server/producer-revision-head";
import {
  loadCutRepairCandidateQc,
  runCutRepairCandidateQc,
  type CutRepairAutomatedQcResult,
} from "./cut-repair-candidate-qc-runner";
import { ensureCutRepairQcToolManifest } from
  "./cut-repair-qc-toolchain";
import type { CutRepairDirectiveV1 } from "./cut-repair-route-policy";

interface ReviewServices {
  loadPreparation: (
    producerDir: string,
    preparationHash: string,
  ) => StoredCutRepairPreparation;
  obtainQc: (
    producerDir: string,
    preparationHash: string,
  ) => Promise<CutRepairAutomatedQcResult>;
  stageReview: (input: {
    producerDir: string;
    action: unknown;
  }) => CutRepairTransitionOutcome;
  admitReview: (
    producerDir: string,
    stored: StoredCutRepairPreparation,
  ) => void;
}

function targetHash(directive: CutRepairDirectiveV1): string {
  return canonicalJsonSha256({
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    target: directive.target,
  });
}

function qcPointerPath(producerDir: string, preparationHash: string): string {
  return path.join(
    producerAuthorityPaths(producerDir).sagas,
    "cut-repair-automated-qc",
    "records",
    `${preparationHash}.json`,
  );
}

function assertControllerFile(filePath: string, label: string): void {
  const stat = lstatSync(filePath);
  if (!stat.isFile() || stat.isSymbolicLink()
      || realpathSync(filePath) !== filePath) {
    throw new Error(`${label} must be a canonical controller-owned file`);
  }
}

async function obtainQc(
  producerDir: string,
  preparationHash: string,
): Promise<CutRepairAutomatedQcResult> {
  const pointer = qcPointerPath(producerDir, preparationHash);
  if (existsSync(pointer)) {
    assertControllerFile(pointer, "candidate QC pointer");
    return loadCutRepairCandidateQc(producerDir, preparationHash);
  }
  const manifest = await ensureCutRepairQcToolManifest(producerDir);
  assertControllerFile(manifest, "candidate QC tool manifest");
  return runCutRepairCandidateQc(
    producerDir, preparationHash, manifest);
}

function admitReview(
  producerDir: string,
  stored: StoredCutRepairPreparation,
): void {
  const action = stored.package.proposedReviewAction;
  assertCutRepairReviewRecoverySync(producerDir, action.idempotencyKey);
  const child = cutRepairTransitionChildSync(
    producerDir, "review", action.idempotencyKey);
  const head = resolveProducerAuthorityHeadSync(producerDir);
  if (head !== action.expectedParentRevisionHash && head !== child) {
    throw new Error("review package is stale for the selected revision");
  }
}

const DEFAULT_SERVICES: ReviewServices = {
  loadPreparation: loadCutRepairPreparationByHashSync,
  obtainQc,
  stageReview: stageCutRepairReviewSync,
  admitReview,
};

function assertQcBindings(
  stored: StoredCutRepairPreparation,
  qc: CutRepairAutomatedQcResult,
): void {
  const preparation = stored.package;
  if (qc.preparationHash !== stored.packageHash
      || qc.candidateDescriptorHash
        !== preparation.reviewCandidateDescriptorHash
      || qc.operationHash !== preparation.proposedReviewAction.operationHash
      || qc.candidateCompositeSha256
        !== preparation.reviewCandidateMediaSha256
      || qc.operatorAuditionProduced !== false) {
    throw new Error("automated QC targets another full-plan candidate");
  }
  if (!qc.ok) return;
  const lanes = [qc.alignment, qc.vad, qc.retranscription, qc.seam];
  if (lanes.some((lane) => lane.status !== "bounded-pass"
      || lane.candidateCompositeSha256
        !== preparation.reviewCandidateMediaSha256)) {
    throw new Error("automated QC did not pass all four candidate-bound lanes");
  }
}

function reviewOutcome(
  stored: StoredCutRepairPreparation,
  qc: Extract<CutRepairAutomatedQcResult, { ok: true }>,
  review: CutRepairTransitionOutcome,
): Record<string, unknown> {
  if (!["committed", "replayed"].includes(review.status)
      || !review.receiptHash) {
    throw new Error("exact CUT_REVIEW transition did not commit");
  }
  return {
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    routeStatus: "cut-review-staged",
    preparationHash: stored.packageHash,
    automatedQcBundleHash: qc.automatedQcBundleHash,
    candidateDescriptorHash: qc.candidateDescriptorHash,
    candidateSha256: qc.candidateCompositeSha256,
    reviewActionHash: canonicalJsonSha256(
      stored.package.proposedReviewAction),
    reviewRevisionHash: review.childRevisionHash,
    reviewReceiptHash: review.receiptHash,
    replayed: review.status === "replayed",
  };
}

/** Run/reopen automated QC, then stage only the already-proposed review. */
export async function runCutRepairReview(
  producerDir: string,
  _manifestPath: string,
  directive: CutRepairDirectiveV1,
  services: ReviewServices = DEFAULT_SERVICES,
): Promise<Record<string, unknown>> {
  if (directive.mode !== "review" || !directive.packageHash) {
    throw new Error("cut repair review requires one preparation package");
  }
  const stored = services.loadPreparation(
    producerDir, directive.packageHash);
  if (stored.packageHash !== directive.packageHash
      || stored.package.targetDirectiveHash !== targetHash(directive)) {
    throw new Error("preparation package targets another phrase occurrence");
  }
  services.admitReview(producerDir, stored);
  const qc = await services.obtainQc(producerDir, stored.packageHash);
  assertQcBindings(stored, qc);
  if (!qc.ok) {
    throw new Error(
      `AUTOMATED_QC_BLOCKED:${JSON.stringify(qc.blockers)}`);
  }
  const review = services.stageReview({
    producerDir,
    action: stored.package.proposedReviewAction,
  });
  return reviewOutcome(stored, qc, review);
}

export type { ReviewServices as CutRepairReviewServices };
