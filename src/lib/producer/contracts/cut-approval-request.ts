import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";

/** Exact reviewed draft, not operator acceptance or final-video approval. */
export interface CutApprovalRequestV1 {
  schemaVersion: 1;
  requestHash: string;
  requestKey: string;
  planHash: string;
  authorityDigest: string;
  cutAuthorityDigest: string;
  cutApprovalReceiptHash: string;
  cutReviewApprovalReceiptHash: string;
  pictureLockHash: string;
  timelineMapHash: string;
  projectionReceiptHash: string;
  createdAt: string;
}

export interface CutApprovalPauseOutcome {
  status: "awaiting_cut_approval";
  request: CutApprovalRequestV1;
  /** Optional only for reading pre-preview foundation records; never acceptance. */
  preview?: CutPreviewPointer;
}

/** Server-derived private attempt; never a client-supplied media path. */
export interface CutPreviewPointer {
  executionKey: string;
  receiptHash: string;
}

const HASH_FIELDS = [
  "requestHash", "requestKey", "planHash", "authorityDigest", "cutAuthorityDigest",
  "cutApprovalReceiptHash", "cutReviewApprovalReceiptHash", "pictureLockHash",
  "timelineMapHash", "projectionReceiptHash",
] as const;
const KEYS = ["schemaVersion", "createdAt", ...HASH_FIELDS];
const SHA256 = /^[a-f0-9]{64}$/;

export function parseCutPreviewPointer(value: unknown): CutPreviewPointer {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("cut preview pointer is missing");
  const row = value as Record<string, unknown>;
  if (Object.keys(row).length !== 2 || typeof row.executionKey !== "string" || typeof row.receiptHash !== "string"
      || !SHA256.test(row.executionKey) || !SHA256.test(row.receiptHash)) throw new Error("cut preview pointer is malformed");
  return { executionKey: row.executionKey, receiptHash: row.receiptHash };
}

export function validCutPreviewPointer(value: unknown): boolean {
  try { parseCutPreviewPointer(value); return true; } catch { return false; }
}

/** Closed parser usable by job readers without loading the authoring pipeline. */
export function parseCutApprovalRequest(value: unknown): CutApprovalRequestV1 {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("cut approval request must be an object");
  }
  const row = value as Record<string, unknown>;
  const date = typeof row.createdAt === "string" ? Date.parse(row.createdAt) : NaN;
  if (Object.keys(row).length !== KEYS.length || Object.keys(row).some((key) => !KEYS.includes(key))
      || row.schemaVersion !== 1 || HASH_FIELDS.some((key) => typeof row[key] !== "string" || !SHA256.test(row[key] as string))
      || !Number.isFinite(date) || new Date(date).toISOString() !== row.createdAt) {
    throw new Error("cut approval request has malformed fields or timestamp");
  }
  const { requestHash, ...core } = row;
  if (canonicalJsonSha256(core) !== requestHash) throw new Error("cut approval request hash is stale");
  return row as unknown as CutApprovalRequestV1;
}

/** Read-only durable shape validation; current artifact checks are separate. */
export function validCutApprovalRequest(value: unknown, requestKey: string): boolean {
  try { return parseCutApprovalRequest(value).requestKey === requestKey; }
  catch { return false; }
}
