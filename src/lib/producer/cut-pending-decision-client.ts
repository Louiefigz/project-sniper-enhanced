import { readCutReviewJson, type CutReviewDescription } from "./cut-review-client";
import { parseCutAcceptanceSubmission } from "./cut-acceptance-client";
import type { HumanCutSubmissionV1 } from "./contracts/human-cut-acceptance";

const SCOPE = "previously-submitted-human-cut-decision-not-new-approval";

/** Read back a previously submitted decision; never infer or create human attestation. */
export function parsePendingCutDecision(value: unknown, review: CutReviewDescription): HumanCutSubmissionV1 {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Saved server decision is unavailable");
  const row = value as Record<string, unknown>;
  if (Object.keys(row).sort().join(",") !== "ok,requestHash,scope,submission"
      || row.ok !== true || row.scope !== SCOPE || row.requestHash !== review.requestHash) {
    throw new Error("Saved server decision has the wrong identity or scope; recheck project status");
  }
  return parseCutAcceptanceSubmission(row.submission, review);
}

/** Explicit recovery read. It does not accept, spawn, overwrite browser storage or mint a key. */
export async function fetchPendingCutDecision(input: {
  dir: string; review: CutReviewDescription; signal: AbortSignal;
}, request = fetch): Promise<HumanCutSubmissionV1> {
  input.signal.throwIfAborted();
  const { requestHash, executionKey, receiptHash } = input.review;
  const query = new URLSearchParams({ dir: input.dir, requestHash, executionKey, receiptHash });
  const response = await request(`/api/producer/cut-review/decision?${query}`,
    { signal: input.signal, cache: "no-store", redirect: "error" });
  const body = await readCutReviewJson(response);
  input.signal.throwIfAborted();
  if (!response.ok) {
    const error = body && typeof body === "object" && "error" in body ? body.error : null;
    throw new Error(typeof error === "string" ? error.slice(0, 2048) : "Prior decision could not be recovered; recheck project status");
  }
  return parsePendingCutDecision(body, input.review);
}
