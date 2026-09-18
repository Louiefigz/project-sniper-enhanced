/** Bounded JSON request bodies for local API routes: an oversize Content-Length is refused before any body read,
 * streamed bytes are capped and the reader is cancelled the moment the cumulative size passes the limit, and a
 * wall-clock deadline bounds the whole read. Nothing is parsed unless the entire body arrived inside both bounds. */
export class BoundedBodyError extends Error {
  constructor(message: string, readonly status: 400 | 408 | 413) { super(message); }
}
export interface BoundedBodyLimits { maximumBytes: number; deadlineMs: number }
/** The structural slice of Request/NextRequest this reader needs; tests may pass a plain object. */
export interface BoundedBodyRequest { headers: Headers; body: ReadableStream<Uint8Array> | null; signal: AbortSignal }

function failIfAborted(abort: AbortSignal, deadline: AbortSignal): void {
  if (deadline.aborted) throw new BoundedBodyError("Request body timed out", 408);
  if (abort.aborted) throw new BoundedBodyError("Request body was disconnected", 400);
}

/** A referenced timer (not AbortSignal.timeout, whose timer is unref'd) so the deadline fires even on an idle loop; always cleared. */
async function readBounded(request: BoundedBodyRequest, reader: ReadableStreamDefaultReader<Uint8Array>, limits: BoundedBodyLimits): Promise<Buffer> {
  const deadline = new AbortController(), timer = setTimeout(() => deadline.abort(), limits.deadlineMs);
  const abort = AbortSignal.any([request.signal, deadline.signal]);
  const cancel = () => { void reader.cancel().catch(() => {}); };
  abort.addEventListener("abort", cancel, { once: true });
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      failIfAborted(abort, deadline.signal);
      const chunk = await reader.read();
      failIfAborted(abort, deadline.signal);
      if (chunk.done) return Buffer.concat(chunks);
      size += chunk.value.length;
      if (size > limits.maximumBytes) throw new BoundedBodyError("Request body is too large", 413);
      chunks.push(chunk.value);
    }
  } finally {
    clearTimeout(timer); abort.removeEventListener("abort", cancel);
    await reader.cancel().catch(() => {}); reader.releaseLock();
  }
}

/** Resolves the parsed JSON value; throws BoundedBodyError 413 (size), 408 (deadline) or 400 (missing/disconnected/invalid). */
export async function readBoundedJsonBody(request: BoundedBodyRequest, limits: BoundedBodyLimits): Promise<unknown> {
  if (Number(request.headers.get("content-length") ?? 0) > limits.maximumBytes) throw new BoundedBodyError("Request body is too large", 413);
  const reader = request.body?.getReader();
  if (!reader) throw new BoundedBodyError("A JSON request body is required", 400);
  const raw = await readBounded(request, reader, limits);
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)); }
  catch { throw new BoundedBodyError("Request body must be valid UTF-8 JSON", 400); }
}
