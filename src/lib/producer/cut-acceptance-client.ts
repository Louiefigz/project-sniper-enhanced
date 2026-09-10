import type { HumanCutSubmissionV1, HumanCutRetryV1 } from "./contracts/human-cut-acceptance";
import type { CutReviewDescription } from "./cut-review-client";
import { readCutReviewJson } from "./cut-review-client";

export interface CutAcceptanceResult {
  ok: true;
  state: "cut_accepted" | "running";
  scope: "human-cut-only-not-delivery";
  cutAccepted: true;
  acceptanceHash: string;
  requestHash: string;
  previewAttempt: number;
  continuationAttempt: number;
  replayed: boolean;
}

interface DecisionStorage { getItem(key: string): string | null; setItem(key: string, value: string): void }
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
const SHA = /^[a-f0-9]{64}$/;
export const CUT_ACCEPTANCE_RESPONSE_TIMEOUT_MS = 300_000;

function decisionKey(review: CutReviewDescription): string {
  return `sniper.cut-decision.v1:${review.requestHash}:${review.executionKey}:${review.receiptHash}`;
}

function decisionCore(review: CutReviewDescription) {
  return { schemaVersion: 1 as const, operation: "accept" as const, expectedToken: review.expectedToken,
    requestHash: review.requestHash, executionKey: review.executionKey, receiptHash: review.receiptHash,
    mediaSha256: review.mediaSha256, attestation: { watched: true as const, listened: true as const,
      acceptsExactCut: true as const, acknowledgesUnfinished: true as const } };
}

/** Recovery may read an earlier explicit choice, but must never invent a new key or attestation. */
export function storedCutAcceptanceSubmission(review: CutReviewDescription, storage: DecisionStorage): HumanCutSubmissionV1 | null {
  const stored = storage.getItem(decisionKey(review));
  if (stored === null) return null;
  if (stored.length > 4096) throw new Error("Saved cut decision is invalid; check project status before retrying");
  return parseCutAcceptanceSubmission(JSON.parse(stored), review);
}

/** Closed exact-preview replay, independent of harmless JSON field ordering. */
export function parseCutAcceptanceSubmission(value: unknown, review: CutReviewDescription): HumanCutSubmissionV1 {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Saved cut decision is malformed");
  const row = value as Record<string, unknown>, core = decisionCore(review);
  const keys = [...Object.keys(core), "idempotencyKey"];
  const attestation = row.attestation as Record<string, unknown> | null;
  const attestationKeys = Object.keys(core.attestation);
  if (Object.keys(row).sort().join(",") !== keys.sort().join(",")
      || typeof row.idempotencyKey !== "string" || !UUID.test(row.idempotencyKey)
      || Object.entries(core).some(([key, expected]) => key !== "attestation" && row[key] !== expected)
      || !attestation || typeof attestation !== "object" || Array.isArray(attestation)
      || Object.keys(attestation).sort().join(",") !== attestationKeys.sort().join(",")
      || attestationKeys.some((key) => attestation[key] !== true)) {
    throw new Error("Saved cut decision differs from this exact preview; check project status before retrying");
  }
  return { ...core, idempotencyKey: row.idempotencyKey };
}

/** Call only after explicit human attestation; retain the same key across uncertain retries/reopen. */
export function cutAcceptanceSubmission(input: {
  review: CutReviewDescription; storage: DecisionStorage; newKey: () => string;
}): HumanCutSubmissionV1 {
  const { review, storage } = input;
  const stored = storedCutAcceptanceSubmission(review, storage);
  if (stored) return stored;
  const idempotencyKey = input.newKey();
  if (!UUID.test(idempotencyKey)) throw new Error("Could not establish a stable cut decision identity");
  const submission = { ...decisionCore(review), idempotencyKey }, key = decisionKey(review);
  storage.setItem(key, JSON.stringify(submission));
  if (storage.getItem(key) !== JSON.stringify(submission)) throw new Error("Could not retain the cut decision for safe retry");
  return submission;
}

export function parseCutAcceptanceResult(value: unknown, requestHash?: string): CutAcceptanceResult {
  const keys = ["ok", "state", "scope", "cutAccepted", "acceptanceHash", "requestHash", "previewAttempt", "continuationAttempt", "replayed"];
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Cut decision result is unknown; recheck project status");
  const row = value as Record<string, unknown>;
  if (Object.keys(row).sort().join(",") !== keys.sort().join(",") || row.ok !== true
      || !["cut_accepted", "running"].includes(String(row.state)) || row.scope !== "human-cut-only-not-delivery" || row.cutAccepted !== true
      || typeof row.acceptanceHash !== "string" || !SHA.test(row.acceptanceHash)
      || typeof row.requestHash !== "string" || !SHA.test(row.requestHash)
      || (requestHash !== undefined && row.requestHash !== requestHash)
      || !Number.isSafeInteger(row.previewAttempt) || Number(row.previewAttempt) < 1
      || !Number.isSafeInteger(row.continuationAttempt) || Number(row.continuationAttempt) <= Number(row.previewAttempt)
      || Number(row.continuationAttempt) > 10000 || typeof row.replayed !== "boolean") {
    throw new Error("Cut decision identities or scope are invalid; recheck project status");
  }
  return row as unknown as CutAcceptanceResult;
}

/** One explicit POST only; no automatic retry, policy switch or final approval. */
export async function submitCutAcceptance(input: {
  dir: string; submission: HumanCutSubmissionV1 | HumanCutRetryV1; signal: AbortSignal;
}, request = fetch): Promise<CutAcceptanceResult> {
  input.signal.throwIfAborted();
  const response = await request("/api/producer/cut-review/accept", { method: "POST", cache: "no-store", redirect: "error",
    headers: { "Content-Type": "application/json" }, signal: input.signal,
    body: JSON.stringify({ dir: input.dir, submission: input.submission }) });
  const body = await readCutReviewJson(response);
  input.signal.throwIfAborted();
  if (!response.ok) {
    const row = body && typeof body === "object" ? body as Record<string, unknown> : {};
    const prefix = row.cutAccepted === true ? "Cut accepted, but continuation needs attention. " : "";
    throw new Error(prefix + (typeof row.error === "string" ? row.error.slice(0, 2048) : "Cut decision could not be confirmed; recheck project status"));
  }
  return parseCutAcceptanceResult(body, input.submission.requestHash);
}
