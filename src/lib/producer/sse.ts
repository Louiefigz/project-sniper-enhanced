// Shared client-side reader for the PRODUCER SSE routes (ingest, render).
//
// All the Python stages emit NDJSON status lines on stdout; the routes forward
// each line verbatim as an SSE `data:` frame (plus synthetic stderr `log` and
// `error` frames). This reads that frame stream and hands each parsed JSON
// object to `onEvent`. Mirrors the parsing loop in FRAME.IO REVIEW's
// review-workspace, factored out so both PRODUCER runners share it.

import type { StreamEvent } from "./types";
import { planRefitProgressMessage } from "./auto-edit-progress";

/** HH:MM:SS.mmm stamp for a log line (matches the debug.ts / Diagnostics format). */
export function logStamp(): string {
  try {
    return new Date().toISOString().slice(11, 23);
  } catch {
    return "--:--:--";
  }
}

/**
 * Read an SSE POST response body to completion, invoking `onEvent` for every
 * parseable `data:` frame. Keepalive comments and partial frames are skipped.
 * Alternative terminal events are explicit per caller; a cut pause is not outputs.
 */
export async function readEventStream(
  res: Response,
  onEvent: (ev: StreamEvent) => void,
  signal?: AbortSignal,
  requiredEvent?: string | readonly string[],
): Promise<void> {
  if (!res.ok) {
    const detail = (await res.clone().json().catch(() => null)) as { error?: string; message?: string } | null;
    throw new Error(detail?.error || detail?.message || `stream request failed (${res.status})`);
  }
  if (!res.body) {
    throw new Error("stream request returned no response body");
  }
  const reader = res.body.getReader();
  const required = requiredEvent == null ? [] : typeof requiredEvent === "string" ? [requiredEvent] : [...requiredEvent];
  if (requiredEvent != null && (!required.length || required.some((item) => !item))) {
    await reader.cancel(); reader.releaseLock();
    throw new Error("A stream requires at least one named terminal event");
  }
  const canceled = () => { void reader.cancel().catch(() => {}); };
  signal?.addEventListener("abort", canceled, { once: true });
  try {
    await consumeEvents(reader, onEvent, signal, required);
  } finally {
    signal?.removeEventListener("abort", canceled);
    await reader.cancel().catch(() => {}); reader.releaseLock();
  }
}

async function consumeEvents(
  reader: ReadableStreamDefaultReader<Uint8Array>, onEvent: (ev: StreamEvent) => void,
  signal: AbortSignal | undefined, required: string[],
): Promise<void> {
  const decoder = new TextDecoder();
  let buffer = "", terminalSeen = required.length === 0;
  for (;;) {
    if (signal?.aborted) return;
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      const ev = parseEventFrame(chunk);
      if (!ev) continue;
      if (required.includes(String(ev.event))) terminalSeen = true;
      onEvent(ev);
    }
  }
  if (!terminalSeen && !signal?.aborted) {
    throw new Error(`The operation ended before confirming ${required.join(" or ")}. Its result is unknown; check the project status before retrying.`);
  }
}

/** Catch malformed JSON only, never an exception raised by the event handler. */
function parseEventFrame(chunk: string): StreamEvent | null {
  const line = chunk.split("\n").find((value) => value.startsWith("data: "));
  if (!line) return null;
  try {
    const value: unknown = JSON.parse(line.slice(6).trim());
    return value && typeof value === "object" && !Array.isArray(value) ? value as StreamEvent : null;
  } catch { return null; }
}

/** Compact one status event into a readable one-line log string. */
export function summarizeEvent(ev: StreamEvent): string {
  const refit = planRefitProgressMessage(ev);
  if (refit) return refit;
  if (typeof ev.text === "string" && ev.event === "log") return ev.text;
  if (typeof ev.error === "string") return `error: ${ev.error}`;
  if (typeof ev.message === "string" && ev.event === "error") return `error: ${ev.message}`;
  if (typeof ev.message === "string" && ev.event === "intent_capability") return ev.message;
  const status = (ev.status ?? ev.event ?? "event") as string;
  const rest = Object.entries(ev)
    .filter(([k]) => k !== "status" && k !== "event")
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`)
    .join(" ");
  return rest ? `${status} · ${rest}` : String(status);
}
