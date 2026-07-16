import { randomUUID } from "node:crypto";
import {
  existsSync, lstatSync, readFileSync, realpathSync,
  renameSync, rmSync, writeFileSync,
} from "node:fs";
import path from "node:path";
import {
  autoEditAuthoritySnapshot,
  stableAuthorityHash,
} from "@/lib/server/auto-edit-authority-snapshot";
import { fileSha256 } from "@/lib/server/auto-edit-hash";
import type {
  CutApprovalReceipt,
  CutAuthorityEvidence,
} from "./cut-approval";
import type { ProducerReview } from "./review-contract";
import { AutoEditError, type AutoEditCtx } from "./stream";

const CUT_REVIEW_APPROVAL_FILE = ".sniper-cut-review-approved.json";
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
  cutAuthorityDigest: string;
  reviews: CleanCutReviewArtifact[];
}

export interface StoredCutReviewArtifact {
  schemaVersion: 1;
  stage: "cut";
  round: number;
  inputAuthority: { digest: string; planHash: string | null };
  inputPacket?: { path: string; hash: string };
  review: ProducerReview;
}

export function cutReviewApprovalPath(ctx: AutoEditCtx): string {
  return path.join(ctx.dir, CUT_REVIEW_APPROVAL_FILE);
}

interface CurrentCutAuthority {
  qualityPolicyVersion: 1;
  manifestHash: string;
  transcriptDigest: string;
  cutTrackDigest: string;
  cutDecisionsDigest: string;
  doctrineHash: string | null;
  digest: string;
}

function currentCutAuthority(
  ctx: AutoEditCtx,
  evidence: CutAuthorityEvidence,
): CurrentCutAuthority {
  const authority = autoEditAuthoritySnapshot(ctx);
  if (!authority.manifestHash) throw new AutoEditError("asset manifest authority is missing");
  if (evidence.planHash !== authority.planHash
      || evidence.manifestHash !== authority.manifestHash
      || evidence.transcriptDigest !== authority.transcriptDigest) {
    throw new AutoEditError("fresh cut evidence no longer matches current inputs");
  }
  const core = {
    qualityPolicyVersion: authority.qualityPolicyVersion,
    manifestHash: evidence.manifestHash,
    transcriptDigest: evidence.transcriptDigest,
    cutTrackDigest: evidence.cutTrackDigest,
    cutDecisionsDigest: evidence.cutDecisionsDigest,
    doctrineHash: ctx.doctrine?.doctrineHash ?? null,
  };
  return { ...core, digest: stableAuthorityHash(core) };
}

function safeReviewPath(ctx: AutoEditCtx, filePath: string): void {
  if (!existsSync(filePath)) throw new AutoEditError("clean cut review artifact is missing");
  const stat = lstatSync(filePath);
  if (stat.isSymbolicLink() || !stat.isFile()) {
    throw new AutoEditError("clean cut review artifact must be a regular non-symlink file");
  }
  const relative = path.relative(realpathSync(ctx.dir), realpathSync(filePath));
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new AutoEditError("clean cut review artifact resolves outside producer directory");
  }
}

function boundJson(
  ctx: AutoEditCtx,
  filePath: string,
  hash: string,
  label: string,
): Record<string, unknown> {
  safeReviewPath(ctx, filePath);
  if (fileSha256(filePath) !== hash) throw new AutoEditError(`${label} hash changed`);
  try {
    const value = JSON.parse(readFileSync(filePath, "utf8")) as unknown;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return value as Record<string, unknown>;
    }
  } catch {
    // The common error below intentionally keeps malformed and unreadable equal.
  }
  throw new AutoEditError(`${label} is invalid JSON`);
}

function validateArtifact(
  ctx: AutoEditCtx,
  item: CleanCutReviewArtifact,
  receipt: CutReviewApprovalReceipt,
): void {
  if (!Number.isInteger(item.round) || item.round < 1 || !item.hash) {
    throw new AutoEditError("clean cut review artifact reference is malformed");
  }
  const value = boundJson(
    ctx, item.path, item.hash, "clean cut review artifact",
  ) as unknown as StoredCutReviewArtifact;
  const valid = value.schemaVersion === 1 && value.stage === "cut"
    && value.round === item.round && value.review?.stage === "cut"
    && value.review.verdict === "pass" && value.review.materialIssues?.length === 0
    && value.inputAuthority?.digest === receipt.authorityDigest
    && value.inputAuthority.planHash === receipt.planHash;
  if (!valid) throw new AutoEditError("clean cut review artifact is not a bound passing review");
}

function legacyDoctrineHash(
  ctx: AutoEditCtx,
  item: CleanCutReviewArtifact,
): string | null {
  const review = boundJson(ctx, item.path, item.hash, "clean cut review artifact");
  const ref = review.inputPacket as { path?: unknown; hash?: unknown } | undefined;
  if (typeof ref?.path !== "string" || typeof ref.hash !== "string") {
    throw new AutoEditError("legacy cut review has no bound critic packet");
  }
  const packet = boundJson(ctx, ref.path, ref.hash, "cut review critic packet");
  const doctrine = packet.doctrineHash;
  if (doctrine !== null && (typeof doctrine !== "string" || !/^[a-f0-9]{64}$/.test(doctrine))) {
    throw new AutoEditError("legacy cut review critic packet has malformed doctrine authority");
  }
  return doctrine as string | null;
}

function validateReceiptShape(value: unknown): CutReviewApprovalReceipt {
  const receipt = value as CutReviewApprovalReceipt;
  const hashes = [
    receipt?.planHash, receipt?.manifestHash, receipt?.transcriptDigest,
    receipt?.authorityDigest, receipt?.cutTrackDigest, receipt?.cutDecisionsDigest,
    receipt?.cutAuthorityDigest,
  ];
  const valid = receipt?.schemaVersion === 1 && receipt.stage === "cut-review"
    && receipt.requiredCleanReviews === REQUIRED_CLEAN_CUT_REVIEWS
    && receipt.qualityPolicyVersion === 1
    && hashes.every((hash) => typeof hash === "string" && /^[a-f0-9]{64}$/.test(hash))
    && (receipt.doctrineHash === null
      || (typeof receipt.doctrineHash === "string" && /^[a-f0-9]{64}$/.test(receipt.doctrineHash)))
    && Array.isArray(receipt.reviews)
    && receipt.reviews.length === REQUIRED_CLEAN_CUT_REVIEWS;
  if (!valid) throw new AutoEditError("cut review approval receipt is malformed");
  return receipt;
}

function legacyReceipt(value: unknown): CutReviewApprovalReceipt {
  const receipt = value as CutReviewApprovalReceipt;
  const hashes = [
    receipt?.planHash, receipt?.manifestHash, receipt?.transcriptDigest,
    receipt?.authorityDigest, receipt?.cutTrackDigest, receipt?.cutDecisionsDigest,
  ];
  const valid = receipt?.schemaVersion === 1 && receipt.stage === "cut-review"
    && receipt.requiredCleanReviews === REQUIRED_CLEAN_CUT_REVIEWS
    && hashes.every((hash) => typeof hash === "string" && /^[a-f0-9]{64}$/.test(hash))
    && Array.isArray(receipt.reviews)
    && receipt.reviews.length === REQUIRED_CLEAN_CUT_REVIEWS;
  if (!valid) throw new AutoEditError("cut review approval receipt is malformed");
  return receipt;
}

function writeReceipt(ctx: AutoEditCtx, receipt: CutReviewApprovalReceipt): void {
  const destination = cutReviewApprovalPath(ctx);
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

function upgradeLegacyReceipt(
  ctx: AutoEditCtx,
  value: unknown,
  current: CurrentCutAuthority,
): CutReviewApprovalReceipt {
  const legacy = legacyReceipt(value);
  const unchanged = legacy.manifestHash === current.manifestHash
    && legacy.transcriptDigest === current.transcriptDigest
    && legacy.cutTrackDigest === current.cutTrackDigest
    && legacy.cutDecisionsDigest === current.cutDecisionsDigest;
  if (!unchanged) throw new AutoEditError("cut review approval no longer matches current cut authority");
  const doctrines = legacy.reviews.map((item) => legacyDoctrineHash(ctx, item));
  if (doctrines.some((item) => item !== current.doctrineHash)) {
    throw new AutoEditError("legacy cut review doctrine authority changed");
  }
  const receipt = validateReceiptShape({
    ...legacy, qualityPolicyVersion: current.qualityPolicyVersion,
    doctrineHash: current.doctrineHash, cutAuthorityDigest: current.digest,
  });
  for (const review of receipt.reviews) validateArtifact(ctx, review, receipt);
  writeReceipt(ctx, receipt);
  return receipt;
}

export function persistCutReviewApproval(
  ctx: AutoEditCtx,
  gate: CutApprovalReceipt,
  authorityDigest: string,
  reviews: CleanCutReviewArtifact[],
): CutReviewApprovalReceipt {
  const current = currentCutAuthority(ctx, gate);
  const receipt = validateReceiptShape({
    schemaVersion: 1,
    stage: "cut-review",
    requiredCleanReviews: REQUIRED_CLEAN_CUT_REVIEWS,
    qualityPolicyVersion: current.qualityPolicyVersion,
    planHash: gate.planHash,
    manifestHash: gate.manifestHash,
    transcriptDigest: gate.transcriptDigest,
    authorityDigest,
    cutTrackDigest: gate.cutTrackDigest,
    cutDecisionsDigest: gate.cutDecisionsDigest,
    doctrineHash: current.doctrineHash,
    cutAuthorityDigest: current.digest,
    reviews,
  });
  for (const review of reviews) validateArtifact(ctx, review, receipt);
  writeReceipt(ctx, receipt);
  return receipt;
}

export function verifyCutReviewApproval(
  ctx: AutoEditCtx,
  evidence: CutAuthorityEvidence,
): CutReviewApprovalReceipt {
  let value: unknown;
  try {
    value = JSON.parse(readFileSync(cutReviewApprovalPath(ctx), "utf8")) as unknown;
  } catch {
    throw new AutoEditError("controller-owned cut review approval is missing or unreadable");
  }
  const current = currentCutAuthority(ctx, evidence);
  const candidate = value as Partial<CutReviewApprovalReceipt>;
  const receipt = candidate.cutAuthorityDigest
    ? validateReceiptShape(value) : upgradeLegacyReceipt(ctx, value, current);
  const storedCore = {
    qualityPolicyVersion: receipt.qualityPolicyVersion,
    manifestHash: receipt.manifestHash,
    transcriptDigest: receipt.transcriptDigest,
    cutTrackDigest: receipt.cutTrackDigest,
    cutDecisionsDigest: receipt.cutDecisionsDigest,
    doctrineHash: receipt.doctrineHash,
  };
  if (receipt.cutAuthorityDigest !== stableAuthorityHash(storedCore)
      || receipt.cutAuthorityDigest !== current.digest) {
    throw new AutoEditError("cut review approval no longer matches current cut authority");
  }
  for (const review of receipt.reviews) validateArtifact(ctx, review, receipt);
  return receipt;
}
