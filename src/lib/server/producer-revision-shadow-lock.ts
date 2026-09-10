import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  readFileSync,
  readdirSync,
} from "node:fs";
import path from "node:path";
import { compatibilityPlanHash } from
  "@/app/api/producer/auto-edit/compatibility-picture-identity";
import { canonicalJsonSha256 } from "./auto-edit-hash";

const SHA256 = /^[a-f0-9]{64}$/u;
const LOCK_KEYS = [
  "schemaVersion", "kind", "adapterVersion", "approvedCutPlanHash",
  "planContentHash", "manifestHash", "transcriptDigest", "cutTrackDigest",
  "cutDecisionsDigest", "cutApprovalReceiptHash",
  "cutReviewApprovalReceiptHash", "cutReviewAuthorityDigest",
  "cutAuthorityDigest", "projectionReceiptHash", "timelineMapHash",
  "qualityPolicyVersion", "requiredCleanReviews",
] as const;

export interface CompatibilityShadowLock {
  hash: string;
  approvedCutPlanHash: string;
  manifestHash: string;
  transcriptDigest: string;
  timelineMapHash: string;
  projectionReceiptHash: string;
  cutApprovalReceiptHash: string;
  cutReviewApprovalReceiptHash: string;
}

function fileHash(filePath: string, label: string): string {
  const before = lstatSync(filePath);
  if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1) {
    throw new Error(`${label} must be one regular non-symlink file`);
  }
  const bytes = readFileSync(filePath);
  const after = lstatSync(filePath);
  if (before.dev !== after.dev || before.ino !== after.ino
      || before.size !== after.size || before.mtimeMs !== after.mtimeMs) {
    throw new Error(`${label} changed while it was hashed`);
  }
  return createHash("sha256").update(bytes).digest("hex");
}

function exactLock(value: unknown, hash: string): CompatibilityShadowLock | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const row = value as Record<string, unknown>;
  if (Object.keys(row).sort().join("\0") !== [...LOCK_KEYS].sort().join("\0")
      || row.schemaVersion !== 1 || row.adapterVersion !== 1
      || row.kind !== "compatibility-picture-lock"
      || row.qualityPolicyVersion !== 1 || row.requiredCleanReviews !== 2) {
    return null;
  }
  const hashes = LOCK_KEYS.filter((key) =>
    key.toLowerCase().includes("hash") || key.toLowerCase().includes("digest"));
  if (hashes.some((key) => typeof row[key] !== "string"
      || !SHA256.test(row[key] as string))) return null;
  return {
    hash,
    approvedCutPlanHash: row.approvedCutPlanHash as string,
    manifestHash: row.manifestHash as string,
    transcriptDigest: row.transcriptDigest as string,
    timelineMapHash: row.timelineMapHash as string,
    projectionReceiptHash: row.projectionReceiptHash as string,
    cutApprovalReceiptHash: row.cutApprovalReceiptHash as string,
    cutReviewApprovalReceiptHash: row.cutReviewApprovalReceiptHash as string,
  };
}

function lockCandidate(
  lockPath: string,
  expected: Record<string, string>,
): CompatibilityShadowLock | null {
  const name = path.basename(lockPath, ".json");
  if (!SHA256.test(name)) return null;
  const bytes = readFileSync(lockPath);
  if (fileHash(lockPath, "compatibility picture lock") !== name) return null;
  const lock = exactLock(JSON.parse(bytes.toString("utf8")), name);
  if (!lock) return null;
  const row = JSON.parse(bytes.toString("utf8")) as Record<string, unknown>;
  return Object.entries(expected).every(([key, value]) => row[key] === value)
    ? lock : null;
}

/** Select one immutable dual-review lock matching current cut and manifest. */
export function findCompatibilityShadowLock(
  producerDir: string,
  manifestPath: string,
  parent: Record<string, unknown>,
): CompatibilityShadowLock | null {
  const directory = path.join(producerDir, "picture_locks");
  if (!existsSync(directory)) return null;
  const cutTrackDigest = canonicalJsonSha256(parent.cutTrack ?? []);
  const cutDecisionsDigest = canonicalJsonSha256(parent.cutDecisions ?? {});
  const expected = {
    manifestHash: fileHash(manifestPath, "manifest"),
    cutTrackDigest,
    cutDecisionsDigest,
    planContentHash: compatibilityPlanHash(
      parent, cutTrackDigest, cutDecisionsDigest,
    ),
  };
  const matches = readdirSync(directory)
    .filter((name) => name.endsWith(".json"))
    .map((name) => lockCandidate(path.join(directory, name), expected))
    .filter((lock): lock is CompatibilityShadowLock => lock !== null);
  if (matches.length > 1) throw new Error("multiple compatibility picture locks match");
  return matches[0] ?? null;
}
