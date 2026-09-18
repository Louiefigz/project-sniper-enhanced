import assert from "node:assert/strict";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { BoundedBodyError, readBoundedJsonBody } from "../../../app/api/_lib/bounded-json-body";

const LIMIT = 16 * 1024, CHUNK = 4 * 1024;
const status = (expected: number) => (error: unknown) => error instanceof BoundedBodyError && error.status === expected;

/** highWaterMark 0 makes pull() fire only for a pending read, so `enqueued` counts exactly the bytes the reader consumed. */
function countingStream(total: number, counters: { enqueued: number; cancelled: boolean }) {
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (counters.enqueued >= total) { controller.close(); return; }
      controller.enqueue(new Uint8Array(CHUNK).fill(0x20)); counters.enqueued += CHUNK;
    },
    cancel() { counters.cancelled = true; },
  }, { highWaterMark: 0 });
}

test("a 40 KiB streamed body without Content-Length is refused after at most limit + one chunk and the reader is cancelled", async () => {
  const counters = { enqueued: 0, cancelled: false }, stream = countingStream(40 * 1024, counters);
  const request = new Request("http://127.0.0.1/x", { method: "POST", body: stream, duplex: "half" } as RequestInit);
  assert.equal(request.headers.get("content-length"), null);
  await assert.rejects(readBoundedJsonBody(request, { maximumBytes: LIMIT, deadlineMs: 2000 }), status(413));
  assert.equal(counters.cancelled, true);
  assert.ok(counters.enqueued > LIMIT && counters.enqueued <= LIMIT + CHUNK, `consumed ${counters.enqueued} bytes`);
  assert.equal(stream.locked, false);
});

test("an oversize Content-Length is refused before any body read", async () => {
  const counters = { enqueued: 0, cancelled: false }, stream = countingStream(CHUNK, counters);
  const request = new NextRequest("http://127.0.0.1/x", { method: "POST", body: stream, duplex: "half",
    headers: { "content-length": String(LIMIT + 1) } } as ConstructorParameters<typeof NextRequest>[1]);
  assert.equal(request.headers.get("content-length"), String(LIMIT + 1));
  await assert.rejects(readBoundedJsonBody(request, { maximumBytes: LIMIT, deadlineMs: 2000 }), status(413));
  assert.equal(counters.enqueued, 0); assert.equal(stream.locked, false);
});

test("a stalled stream hits the read deadline with 408 and the reader is cancelled", async () => {
  let cancelled = false;
  const stream = new ReadableStream<Uint8Array>({ pull() { return new Promise<void>(() => {}); }, cancel() { cancelled = true; } });
  const started = performance.now();
  await assert.rejects(readBoundedJsonBody({ headers: new Headers(), body: stream, signal: new AbortController().signal },
    { maximumBytes: LIMIT, deadlineMs: 60 }), status(408));
  assert.ok(performance.now() - started >= 50, "deadline fired early");
  assert.equal(cancelled, true); assert.equal(stream.locked, false);
});

test("a small valid NextRequest body parses; invalid JSON and a missing body are 400", async () => {
  const request = new NextRequest("http://127.0.0.1/x", { method: "POST", body: JSON.stringify({ dir: "/p", submission: { a: 1 } }) });
  assert.deepEqual(await readBoundedJsonBody(request, { maximumBytes: LIMIT, deadlineMs: 2000 }), { dir: "/p", submission: { a: 1 } });
  await assert.rejects(readBoundedJsonBody(new NextRequest("http://127.0.0.1/x", { method: "POST", body: "{" }), { maximumBytes: LIMIT, deadlineMs: 2000 }), status(400));
  await assert.rejects(readBoundedJsonBody(new NextRequest("http://127.0.0.1/x", { method: "POST" }), { maximumBytes: LIMIT, deadlineMs: 2000 }), status(400));
});
