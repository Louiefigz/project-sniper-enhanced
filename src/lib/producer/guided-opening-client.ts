import { GUIDED_OPENING_STATUS_SCOPE, type GuidedOpeningStatusV1 } from "./contracts/guided-opening-status-v1";
import { exactKeys, objectValue, sha256, stringValue, uuid } from "./contracts/validation";
import { readCutReviewJson } from "./cut-review-client";
import { parseOpeningMedia } from "./guided-opening-media-client";

const BASE_KEYS = ["ok", "schemaVersion", "scope", "state", "requestId", "executionId", "claimHash",
  "openingApproved", "deliveryApproved", "subjectiveListening", "detail", "timing"];
const STATES = ["unavailable", "pending-owned-execution", "pending-cleanup", "failed", "ready-for-review"];

function exactDate(value: unknown): void {
  const text = stringValue(value, "opening generation origin", 30);
  if (!Number.isFinite(Date.parse(text)) || new Date(text).toISOString() !== text) throw new Error("Opening generation origin is malformed");
}

function elapsed(value: unknown): boolean {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= Number.MAX_SAFE_INTEGER;
}

function timing(value: unknown, state: string): void {
  const row = objectValue(value, "opening timing");
  const keys = ["generationStartedAt", "engineElapsedMs", "cleanupElapsedMs", "elapsedStatus", "coverage"];
  exactKeys(row, keys, keys, "opening timing");
  if (row.generationStartedAt !== null) exactDate(row.generationStartedAt);
  if (row.elapsedStatus === "unavailable") {
    if (row.engineElapsedMs !== null || row.cleanupElapsedMs !== null || row.coverage !== "unavailable"
        || state === "ready-for-review") throw new Error("Unknown opening timing cannot become a completed measurement");
    return;
  }
  // A recorded stopped attempt may still be "pending-owned-execution": a force-stopped outer group or a live
  // recorded descendant keeps ownership unresolved after the owned run itself ended (server status forced branch).
  if (row.elapsedStatus !== "completed" || row.generationStartedAt === null || !elapsed(row.engineElapsedMs)
      || (row.cleanupElapsedMs !== null && !elapsed(row.cleanupElapsedMs))
      || row.coverage !== "recorded-owned-attempt-only" || (state === "pending-owned-execution" && row.cleanupElapsedMs !== null)
      || (state === "ready-for-review" && row.cleanupElapsedMs === null)) {
    throw new Error("Opening timing does not describe a recorded stopped attempt");
  }
}

/** Closed display DTO. The server still owns all current-source and artifact verification. */
export function parseGuidedOpeningStatus(value: unknown, dir: string): GuidedOpeningStatusV1 {
  const row = objectValue(value, "opening status");
  const keys = row.state === "ready-for-review" ? [...BASE_KEYS, "selectionHash", "receiptHash", "receiptSha256", "media",
    "selectionQualifiedAt", "sourceFreshness", "journal", "approval"] : BASE_KEYS;
  exactKeys(row, keys, keys, "opening status");
  if (row.ok !== true || row.schemaVersion !== 1 || row.scope !== GUIDED_OPENING_STATUS_SCOPE
      || typeof row.state !== "string" || !STATES.includes(row.state)
      || typeof row.openingApproved !== "boolean" || (row.state !== "ready-for-review" && row.openingApproved !== false)
      || row.deliveryApproved !== false
      || row.subjectiveListening !== "not-performed-by-system") throw new Error("Opening status cannot claim approval or listening");
  stringValue(row.detail, "opening status detail", 2048);
  if (row.state !== "unavailable" || row.requestId !== null || row.executionId !== null || row.claimHash !== null) {
    uuid(row.requestId, "opening request ID"); uuid(row.executionId, "opening execution ID"); sha256(row.claimHash, "opening claim");
  }
  timing(row.timing, row.state);
  if (row.state === "ready-for-review") {
    for (const key of ["selectionHash", "receiptHash", "receiptSha256"]) sha256(row[key], key);
    exactDate(row.selectionQualifiedAt);
    if (row.sourceFreshness !== "not-rechecked-by-status"
        || String(row.selectionQualifiedAt) < String((row.timing as Record<string, unknown>).generationStartedAt)) {
      throw new Error("Opening status cannot claim current source revalidation");
    }
    parseOpeningMedia(row.media, { dir, selectionHash: row.selectionHash as string });
    const journal = objectValue(row.journal, "opening journal identity");
    exactKeys(journal, ["token", "sha256"], ["token", "sha256"], "opening journal identity");
    stringValue(journal.token, "opening journal token", 200); sha256(journal.sha256, "opening journal hash");
    approvalDisplay(row.approval, row.openingApproved === true, String(row.selectionQualifiedAt));
  }
  return row as unknown as GuidedOpeningStatusV1;
}

/** A verified approval object is the only thing that may set openingApproved; playback never does. */
function approvalDisplay(value: unknown, claimed: boolean, selectionQualifiedAt: string): void {
  if (value === null) { if (claimed) throw new Error("Opening status claims approval without a verified approval object"); return; }
  const row = objectValue(value, "opening approval");
  exactKeys(row, ["approvalHash", "approvedAt"], ["approvalHash", "approvedAt"], "opening approval");
  sha256(row.approvalHash, "opening approval hash"); exactDate(row.approvedAt);
  if (!claimed || String(row.approvedAt) < selectionQualifiedAt) throw new Error("Opening approval object does not agree with the approved flag or selection time");
}

const APPROVAL_RESULT_KEYS = ["ok", "replayed", "approvalHash", "approvedAt", "selectionHash", "openingApproved", "bodyGenerated", "deliveryApproved"];

export interface GuidedOpeningApprovalResult { ok: true; replayed: boolean; approvalHash: string; approvedAt: string; selectionHash: string }

export function parseGuidedOpeningApprovalResult(value: unknown, selectionHash: string): GuidedOpeningApprovalResult {
  const row = objectValue(value, "opening approval result");
  exactKeys(row, APPROVAL_RESULT_KEYS, APPROVAL_RESULT_KEYS, "opening approval result");
  if (row.ok !== true || typeof row.replayed !== "boolean" || row.openingApproved !== true || row.bodyGenerated !== false || row.deliveryApproved !== false
      || row.selectionHash !== selectionHash) throw new Error("Opening approval result does not describe this exact selection");
  sha256(row.approvalHash, "approvalHash"); exactDate(row.approvedAt);
  return row as unknown as GuidedOpeningApprovalResult;
}

/** Explicit human POST; the server re-verifies everything and never treats this call as body or delivery approval. */
export async function submitGuidedOpeningApproval(dir: string, submission: Record<string, unknown>, signal: AbortSignal, request = fetch) {
  signal.throwIfAborted();
  const response = await request("/api/producer/guided-opening/approve", { method: "POST", signal, cache: "no-store", redirect: "error",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dir, submission }) });
  const body = await readCutReviewJson(response, "Opening approval");
  signal.throwIfAborted();
  if (!response.ok) {
    const error = body && typeof body === "object" && "error" in body ? body.error : null;
    throw new Error(typeof error === "string" ? error.slice(0, 2048) : "Opening approval was not confirmed");
  }
  return parseGuidedOpeningApprovalResult(body, String(submission.selectionHash));
}

export async function fetchGuidedOpeningStatus(dir: string, signal: AbortSignal, request = fetch): Promise<GuidedOpeningStatusV1> {
  signal.throwIfAborted();
  const response = await request(`/api/producer/guided-opening/status?${new URLSearchParams({ dir })}`,
    { signal, cache: "no-store", redirect: "error" });
  const body = await readCutReviewJson(response, "Opening status");
  signal.throwIfAborted();
  if (!response.ok) {
    const error = body && typeof body === "object" && "error" in body ? body.error : null;
    throw new Error(typeof error === "string" ? error.slice(0, 2048) : "Opening status is unavailable");
  }
  return parseGuidedOpeningStatus(body, dir);
}
