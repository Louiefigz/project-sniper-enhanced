import { readCutReviewJson } from "./cut-review-client";

export interface AcceptedCutStatus {
  ok: true;
  cutAccepted: true;
  scope: "human-cut-only-not-delivery";
  state: "cut_accepted" | "running" | "failed" | "interrupted" | "complete";
  acceptanceHash: string;
  requestHash: string;
  previewAttempt: number;
  continuationAttempt: number;
  canRetryContinuation: boolean;
  timingState: "verified-activation" | "unavailable-legacy-activation";
  waitStoppedAt: string | null;
  decisionSubmittedAt: string;
  caveat: string;
}

function validTiming(row: Record<string, unknown>): boolean {
  const date = (value: unknown) => typeof value === "string" && Number.isFinite(Date.parse(value))
    && new Date(value).toISOString() === value;
  if (!date(row.decisionSubmittedAt)) return false;
  if (row.timingState === "unavailable-legacy-activation") return row.waitStoppedAt === null;
  return row.timingState === "verified-activation" && date(row.waitStoppedAt)
    && String(row.waitStoppedAt) >= String(row.decisionSubmittedAt);
}

/** Historical human decision only. Even a completed worker is not evidence of final approval. */
export function parseAcceptedCutStatus(value: unknown): AcceptedCutStatus {
  const keys = ["ok", "cutAccepted", "scope", "state", "acceptanceHash", "requestHash", "previewAttempt",
    "continuationAttempt", "canRetryContinuation", "waitStoppedAt", "timingState", "decisionSubmittedAt", "caveat"];
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Accepted cut status is unavailable");
  const row = value as Record<string, unknown>;
  if (Object.keys(row).sort().join(",") !== keys.sort().join(",") || row.ok !== true || row.cutAccepted !== true
      || row.scope !== "human-cut-only-not-delivery"
      || !["cut_accepted", "running", "failed", "interrupted", "complete"].includes(String(row.state))
      || [row.acceptanceHash, row.requestHash].some((hash) => typeof hash !== "string" || !/^[a-f0-9]{64}$/.test(hash))
      || !Number.isSafeInteger(row.previewAttempt) || Number(row.previewAttempt) < 1
      || !Number.isSafeInteger(row.continuationAttempt) || Number(row.continuationAttempt) <= Number(row.previewAttempt)
      || Number(row.continuationAttempt) > 10000 || row.canRetryContinuation !== (row.state === "cut_accepted")
      || !validTiming(row)
      || typeof row.caveat !== "string" || !row.caveat.trim() || row.caveat.length > 2048) {
    throw new Error("Accepted cut status identities or scope could not be verified");
  }
  return row as unknown as AcceptedCutStatus;
}

export async function fetchAcceptedCutStatus(dir: string, signal: AbortSignal, request = fetch): Promise<AcceptedCutStatus> {
  signal.throwIfAborted();
  const response = await request(`/api/producer/cut-review/accept?${new URLSearchParams({ dir })}`,
    { signal, cache: "no-store", redirect: "error" });
  const body = await readCutReviewJson(response);
  signal.throwIfAborted();
  if (!response.ok) {
    const error = body && typeof body === "object" && "error" in body ? body.error : null;
    throw new Error(typeof error === "string" ? error.slice(0, 2048) : "Accepted cut status could not be verified");
  }
  return parseAcceptedCutStatus(body);
}
