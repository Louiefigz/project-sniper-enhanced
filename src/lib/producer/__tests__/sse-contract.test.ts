import assert from "node:assert/strict";
import { readEventStream } from "../sse";
import type { StreamEvent } from "../types";

function sseResponse(...events: StreamEvent[]): Response {
  const body = events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
  return new Response(body, { status: 200 });
}

async function main(): Promise<void> {
  {
    const seen: StreamEvent[] = [];
    await readEventStream(
      sseResponse({ event: "progress" }, { event: "outputs", path: "/tmp/final.mp4" }),
      (event) => seen.push(event),
      undefined,
      "outputs",
    );
    assert.deepEqual(seen.map((event) => event.event), ["progress", "outputs"]);
  }

  await assert.rejects(
    readEventStream(sseResponse({ event: "progress" }), () => undefined, undefined, "outputs"),
    /ended before confirming outputs/,
  );

  const handlerError = new Error("render event handler failed");
  await assert.rejects(
    readEventStream(sseResponse({ event: "error", error: "render failed" }), () => {
      throw handlerError;
    }),
    (error: unknown) => error === handlerError,
  );
}

void main()
  .then(() => console.log("sse-contract.test.ts: all assertions passed"))
  .catch((error: unknown) => {
    console.error(error);
    process.exitCode = 1;
  });
