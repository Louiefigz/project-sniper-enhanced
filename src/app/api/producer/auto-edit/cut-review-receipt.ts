import { randomUUID } from "node:crypto";
import { renameSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { AutoEditError } from "./stream";

const SHA256 = /^[a-f0-9]{64}$/;
export const REQUIRED_CLEAN_CUT_REVIEWS = 2;

export interface CleanCutReviewArtifact {
  round: number;
  path: string;
  hash: string;
}

export interface CutReviewApprovalReceipt {
  schemaVersion: 1;
  stage: "cut-review";
  requiredCleanReviews: 2;
  qualityPolicyVersion: 1;
  planHash: string;
  manifestHash: string;
  transcriptDigest: string;
  authorityDigest: string;
  cutTrackDigest: string;
  cutDecisionsDigest: string;
  doctrineHash: string | null;
  cutIntentDigest: string;
  cutAuthorityDigest: string;
  reviews: CleanCutReviewArtifact[];
}

function validateDistinctReviews(reviews: CleanCutReviewArtifact[]): void {
  const valid = reviews.every((item) => item !== null
    && Number.isInteger(item.round) && item.round >= 1
    && typeof item.path === "string" && item.path.length > 0
    && typeof item.hash === "string" && SHA256.test(item.hash));
  if (!valid) throw new AutoEditError("clean cut review artifact reference is malformed");
  const dimensions: Array<[string, Array<string | number>]> = [
    ["rounds", reviews.map((item) => item.round)],
    ["artifact paths", reviews.map((item) => path.resolve(item.path))],
    ["hashes", reviews.map((item) => item.hash)],
  ];
  for (const [label, values] of dimensions) {
    if (new Set(values).size !== reviews.length) {
      throw new AutoEditError(`cut review approval requires distinct ${label}`);
    }
  }
}

export function validateCutReviewReceipt(
  value: unknown,
): CutReviewApprovalReceipt {
  const receipt = value as CutReviewApprovalReceipt;
  const hashes = [
    receipt?.planHash, receipt?.manifestHash, receipt?.transcriptDigest,
    receipt?.authorityDigest, receipt?.cutTrackDigest, receipt?.cutDecisionsDigest,
    receipt?.cutIntentDigest, receipt?.cutAuthorityDigest,
  ];
  const valid = receipt?.schemaVersion === 1 && receipt.stage === "cut-review"
    && receipt.requiredCleanReviews === REQUIRED_CLEAN_CUT_REVIEWS
    && receipt.qualityPolicyVersion === 1
    && hashes.every((hash) => typeof hash === "string" && SHA256.test(hash))
    && (receipt.doctrineHash === null
      || (typeof receipt.doctrineHash === "string" && SHA256.test(receipt.doctrineHash)))
    && Array.isArray(receipt.reviews)
    && receipt.reviews.length === REQUIRED_CLEAN_CUT_REVIEWS;
  if (!valid) throw new AutoEditError("cut review approval receipt is malformed");
  validateDistinctReviews(receipt.reviews);
  return receipt;
}

export function validateLegacyCutReviewReceipt(
  value: unknown,
): CutReviewApprovalReceipt {
  const receipt = value as CutReviewApprovalReceipt;
  const hashes = [
    receipt?.planHash, receipt?.manifestHash, receipt?.transcriptDigest,
    receipt?.authorityDigest, receipt?.cutTrackDigest, receipt?.cutDecisionsDigest,
  ];
  const valid = receipt?.schemaVersion === 1 && receipt.stage === "cut-review"
    && receipt.requiredCleanReviews === REQUIRED_CLEAN_CUT_REVIEWS
    && hashes.every((hash) => typeof hash === "string" && SHA256.test(hash))
    && Array.isArray(receipt.reviews)
    && receipt.reviews.length === REQUIRED_CLEAN_CUT_REVIEWS;
  if (!valid) throw new AutoEditError("cut review approval receipt is malformed");
  validateDistinctReviews(receipt.reviews);
  return receipt;
}

export function writeCutReviewReceipt(
  destination: string,
  receipt: CutReviewApprovalReceipt,
): void {
  const temporary = `${destination}.${randomUUID()}.tmp`;
  try {
    writeFileSync(temporary, `${JSON.stringify(receipt, null, 2)}\n`, {
      flag: "wx", mode: 0o600,
    });
    renameSync(temporary, destination);
  } finally {
    rmSync(temporary, { force: true });
  }
}
