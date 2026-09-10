import { exactKeys, objectValue, sha256, stringValue, uuid } from "./contracts/validation";
import { parsePrepareGuidedOpening, type PrepareGuidedOpeningV1 } from "./contracts/guided-opening-v1";
import { readCutReviewJson } from "./cut-review-client";

export type OpeningLaunchRequest = Pick<PrepareGuidedOpeningV1, "expectedToken" | "expectedJournalHash" | "proposalReadinessHash" | "treatmentDraftRevisionHash">;
export interface OpeningLaunchStatus {
  ok: true; state: "eligible" | "unavailable" | "launch-recorded" | "failed"; detail: string;
  request: OpeningLaunchRequest | null; receivedAt: string | null;
}
export interface OpeningLaunchResult {
  ok: true; replayed: boolean; state: "launch-recorded"; journalHash: string; requestId: string;
  openingApproved: false; bodyGenerated: false; deliveryApproved: false;
}
const REQUEST_KEYS = ["expectedToken", "expectedJournalHash", "proposalReadinessHash", "treatmentDraftRevisionHash"] as const;
export const OPENING_LAUNCH_POLL_MS = 5000, OPENING_LAUNCH_POLL_LIMIT = 300;

function parseRequest(value: unknown): OpeningLaunchRequest {
  const row = objectValue(value, "opening launch request");
  exactKeys(row, [...REQUEST_KEYS], [...REQUEST_KEYS], "opening launch request");
  stringValue(row.expectedToken, "expectedToken", 200);
  for (const key of REQUEST_KEYS.slice(1)) sha256(row[key], key);
  return row as unknown as OpeningLaunchRequest;
}

/** Launch eligibility metadata is separate from selectable opening evidence and never proves process liveness. */
export function parseOpeningLaunchStatus(value: unknown): OpeningLaunchStatus {
  const row = objectValue(value, "opening launch status"), keys = ["ok", "state", "detail", "request", "receivedAt"];
  exactKeys(row, keys, keys, "opening launch status");
  if (row.ok !== true || !["eligible", "unavailable", "launch-recorded", "failed"].includes(String(row.state))) throw new Error("Opening launch status is invalid");
  stringValue(row.detail, "opening launch detail", 2048);
  if (row.state === "eligible") parseRequest(row.request);
  else if (row.request !== null) throw new Error("Unavailable opening launch cannot supply execution authority");
  if (row.receivedAt !== null) {
    const at = stringValue(row.receivedAt, "opening launch receivedAt", 30);
    if (!Number.isFinite(Date.parse(at)) || new Date(at).toISOString() !== at) throw new Error("Opening launch timestamp is invalid");
  }
  if (row.state === "launch-recorded" && row.receivedAt === null) throw new Error("Recorded opening launch has no receipt time");
  return row as unknown as OpeningLaunchStatus;
}

export function parseOpeningLaunchResult(value: unknown, requestId: string): OpeningLaunchResult {
  const row = objectValue(value, "opening launch response");
  const keys = ["ok", "replayed", "state", "journalHash", "requestId", "openingApproved", "bodyGenerated", "deliveryApproved"];
  exactKeys(row, keys, keys, "opening launch response");
  if (row.ok !== true || typeof row.replayed !== "boolean" || row.state !== "launch-recorded" || row.requestId !== requestId
      || row.openingApproved !== false || row.bodyGenerated !== false || row.deliveryApproved !== false) throw new Error("Opening launch was not confirmed for this request");
  sha256(row.journalHash, "opening launch journal"); uuid(row.requestId, "opening request ID");
  return row as unknown as OpeningLaunchResult;
}

async function responseBody(response: Response, signal: AbortSignal): Promise<unknown> {
  const body = await readCutReviewJson(response, "Opening launch"); signal.throwIfAborted();
  if (!response.ok) {
    const error = body && typeof body === "object" && "error" in body ? body.error : null;
    throw new Error(typeof error === "string" ? error.slice(0, 2048) : "Opening launch outcome was not confirmed");
  }
  return body;
}

export async function fetchOpeningLaunchStatus(dir: string, signal: AbortSignal, request = fetch): Promise<OpeningLaunchStatus> {
  signal.throwIfAborted();
  const response = await request(`/api/producer/guided-opening/launch?${new URLSearchParams({ dir })}`,
    { signal, cache: "no-store", redirect: "error" });
  return parseOpeningLaunchStatus(await responseBody(response, signal));
}

/** One explicit request; never retry POST automatically, and never interpret an aborted response as cancellation. */
export async function submitOpeningLaunch(input: { dir: string; submission: PrepareGuidedOpeningV1; signal: AbortSignal }, request = fetch) {
  input.signal.throwIfAborted(); const submission = parsePrepareGuidedOpening(input.submission);
  const response = await request("/api/producer/guided-opening/launch", { method: "POST", signal: input.signal,
    cache: "no-store", redirect: "error", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dir: input.dir, submission }) });
  const body = await responseBody(response, input.signal);
  if (response.status !== 202) throw new Error("Opening launch response did not confirm a recorded request");
  return parseOpeningLaunchResult(body, submission.idempotencyKey);
}

const storageKey = (dir: string) => `sniper:opening-launch:v1:${encodeURIComponent(dir)}`;
type PendingStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

/** Browser storage only preserves a submitted UUID. The server must still verify all durable authority. */
export function readPendingOpeningLaunch(dir: string, storage: PendingStorage): PrepareGuidedOpeningV1 | null {
  const text = storage.getItem(storageKey(dir)); if (text === null) return null;
  if (text.length > 16_384) throw new Error("Saved opening request is too large; do not start a duplicate render");
  const row = objectValue(JSON.parse(text), "saved opening request");
  exactKeys(row, ["dir", "submission"], ["dir", "submission"], "saved opening request");
  if (row.dir !== dir) throw new Error("Saved opening request targets another project");
  return parsePrepareGuidedOpening(row.submission);
}

export function retainOpeningLaunch(dir: string, submission: PrepareGuidedOpeningV1, storage: PendingStorage): void {
  const value = parsePrepareGuidedOpening(submission);
  storage.setItem(storageKey(dir), JSON.stringify({ dir, submission: value }));
  if (JSON.stringify(readPendingOpeningLaunch(dir, storage)) !== JSON.stringify(value)) throw new Error("Opening request could not be safely retained; nothing was submitted");
}

export function clearConfirmedOpeningLaunch(dir: string, id: string, storage: PendingStorage): void {
  if (readPendingOpeningLaunch(dir, storage)?.idempotencyKey === id) storage.removeItem(storageKey(dir));
}

export function openingLaunchSubmission(status: OpeningLaunchStatus, pending: PrepareGuidedOpeningV1 | null, id: () => string): PrepareGuidedOpeningV1 {
  if (status.state !== "eligible" || !status.request) throw new Error("Recheck opening eligibility before generating");
  if (pending && REQUEST_KEYS.some((key) => pending[key] !== status.request![key])) throw new Error("A prior request has an unknown outcome for older project evidence. Recheck or recover it; do not start a duplicate.");
  return pending ?? parsePrepareGuidedOpening({ schemaVersion: 1, operation: "prepare-guided-opening", idempotencyKey: id(), ...status.request });
}
