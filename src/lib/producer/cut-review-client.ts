/** Browser contract for historical cut-only playback, never final approval. */
export interface CutReviewDescription {
  ok: true;
  state: "awaiting_cut_approval";
  requestHash: string;
  planHash: string;
  expectedToken: string;
  executionKey: string;
  receiptHash: string;
  mediaSha256: string;
  waitStartedAt: string;
  waitStoppedAt: string | null;
  acceptanceState: "awaiting-decision" | "verifying" | "verification-failed";
  acceptanceError: string | null;
  previewStartedAt: string;
  mediaUrl: string;
  durationSeconds: number;
  width: number;
  height: number;
  scope: "cut-only-source-aspect-ungraded-unmixed-not-delivery";
  accepted: false;
  caveat: string;
}

const HASHES = ["requestHash", "planHash", "executionKey", "receiptHash", "mediaSha256"] as const;
const KEYS = ["ok", "state", ...HASHES, "expectedToken", "waitStartedAt", "previewStartedAt", "mediaUrl",
  "durationSeconds", "width", "height", "scope", "accepted", "caveat", "waitStoppedAt", "acceptanceState", "acceptanceError"];
const DATE = (value: unknown) => typeof value === "string" && Number.isFinite(Date.parse(value))
  && new Date(value).toISOString() === value;

function exactMediaUrl(row: Record<string, unknown>, dir: string): boolean {
  if (typeof row.mediaUrl !== "string" || !row.mediaUrl.startsWith("/api/producer/cut-review/video?")) return false;
  const url = new URL(row.mediaUrl, "http://localhost");
  const expected = { dir, requestHash: row.requestHash, executionKey: row.executionKey, receiptHash: row.receiptHash };
  return !url.hash && [...url.searchParams].length === 4 && Object.entries(expected)
    .every(([key, value]) => url.searchParams.getAll(key).length === 1 && url.searchParams.get(key) === value);
}

function validAcceptanceState(row: Record<string, unknown>): boolean {
  if (row.acceptanceState === "verifying") return DATE(row.waitStoppedAt)
    && String(row.waitStoppedAt) >= String(row.waitStartedAt) && row.acceptanceError === null;
  if (row.waitStoppedAt !== null) return false;
  if (row.acceptanceState === "awaiting-decision") return row.acceptanceError === null;
  return row.acceptanceState === "verification-failed" && typeof row.acceptanceError === "string"
    && row.acceptanceError.length > 0 && row.acceptanceError.length <= 1000;
}

export function parseCutReviewDescription(value: unknown, dir: string): CutReviewDescription {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Cut preview response is malformed");
  const row = value as Record<string, unknown>;
  if (Object.keys(row).length !== KEYS.length || Object.keys(row).some((key) => !KEYS.includes(key))
      || row.ok !== true || row.state !== "awaiting_cut_approval" || row.accepted !== false
      || row.scope !== "cut-only-source-aspect-ungraded-unmixed-not-delivery"
      || typeof row.expectedToken !== "string" || !row.expectedToken || row.expectedToken.length > 200
      || !validAcceptanceState(row)
      || HASHES.some((key) => typeof row[key] !== "string" || !/^[a-f0-9]{64}$/.test(row[key] as string))
      || !DATE(row.waitStartedAt) || !DATE(row.previewStartedAt)
      || Date.parse(row.waitStartedAt as string) < Date.parse(row.previewStartedAt as string)
      || typeof row.durationSeconds !== "number" || !Number.isFinite(row.durationSeconds) || row.durationSeconds <= 0
      || row.durationSeconds > 24 * 3600 || !Number.isInteger(row.width) || !Number.isInteger(row.height)
      || Number(row.width) < 2 || Number(row.width) > 8192 || Number(row.height) < 2 || Number(row.height) > 8192
      || typeof row.caveat !== "string" || !row.caveat.trim() || row.caveat.length > 2048
      || !exactMediaUrl(row, dir)) throw new Error("Cut preview identities or scope could not be verified");
  return row as unknown as CutReviewDescription;
}

export async function fetchCutReview(dir: string, signal: AbortSignal, request = fetch): Promise<CutReviewDescription> {
  signal.throwIfAborted();
  const response = await request(`/api/producer/cut-review?${new URLSearchParams({ dir })}`,
    { signal, cache: "no-store", redirect: "error" });
  const body = await readCutReviewJson(response);
  signal.throwIfAborted();
  if (!response.ok) {
    const error = body && typeof body === "object" && "error" in body ? body.error : null;
    throw new Error(typeof error === "string" ? error.slice(0, 2048) : "Cut preview is unavailable");
  }
  return parseCutReviewDescription(body, dir);
}

/** Shared bounded browser readback for preview and human-decision responses. */
export async function readCutReviewJson(response: Response, label = "Cut review"): Promise<unknown> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error(`${label} response has no body`);
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) break;
      size += chunk.value.length;
      if (size > 16_384) throw new Error(`${label} response exceeds its size limit`);
      chunks.push(chunk.value);
    }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown;
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

export function cutWaitLabel(startedAt: string, now: number): string {
  const seconds = Math.floor((now - Date.parse(startedAt)) / 1000);
  if (!Number.isFinite(seconds) || seconds < 0) return "Waiting clock unavailable (device clock differs)";
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s waiting for you`;
}
