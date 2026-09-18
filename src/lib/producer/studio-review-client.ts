/** Preview access only: this client cannot sync, render, or approve a plan. */
export interface StudioReviewStatus {
  ok: true;
  state: "ready" | "not-open" | "blocked";
  url: string | null;
  canOpen: boolean;
  pendingEdits: string[];
  blockers: string[];
  caveat: string;
  reused?: boolean;
}

/** Never embed a server-supplied external URL or a different local service. */
export function studioPreviewUrl(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value !== "string") throw new Error("Studio returned an invalid preview URL");
  const url = new URL(value);
  const port = Number(url.port);
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || url.username || url.password
      || port < 3990 || port > 3999 || url.pathname !== "/" || url.search
      || !url.hash.startsWith("#project/")) {
    throw new Error("Studio returned an untrusted preview URL");
  }
  return url.href;
}

function stringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === "string");
}

/** Validate status before giving the Studio iframe a source. */
export function parseStudioStatus(value: unknown): StudioReviewStatus {
  if (!value || typeof value !== "object") throw new Error("Studio returned an invalid status");
  const row = value as Record<string, unknown>;
  if (row.ok !== true || !["ready", "not-open", "blocked"].includes(String(row.state))
      || typeof row.canOpen !== "boolean" || !stringList(row.pendingEdits)
      || !stringList(row.blockers) || typeof row.caveat !== "string") {
    throw new Error("Studio returned an invalid status");
  }
  const url = studioPreviewUrl(row.url);
  if (row.state === "ready" && !url) throw new Error("Studio has no ready preview URL");
  return { ...row, url } as unknown as StudioReviewStatus;
}

/** Open/reuse or inspect the projection, never apply edits or start delivery. */
export async function requestStudioReview(
  dir: string,
  action: "open" | "status",
  signal: AbortSignal,
): Promise<StudioReviewStatus> {
  signal.throwIfAborted();
  const response = await fetch(action === "open"
    ? "/api/producer/studio" : `/api/producer/studio?dir=${encodeURIComponent(dir)}`, {
    method: action === "open" ? "POST" : "GET", cache: "no-store", signal,
    ...(action === "open" ? {
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dir }),
    } : {}),
  });
  const value = await response.json().catch(() => null) as { error?: unknown } | null;
  if (!response.ok) throw new Error(typeof value?.error === "string"
    ? value.error : `Studio request failed (${response.status})`);
  return parseStudioStatus(value);
}
