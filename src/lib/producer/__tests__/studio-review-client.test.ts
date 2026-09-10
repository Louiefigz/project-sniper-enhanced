import assert from "node:assert/strict";
import { parseStudioStatus, requestStudioReview, studioPreviewUrl } from "../studio-review-client";

const ready = { ok: true, state: "ready", canOpen: true, url: "http://127.0.0.1:3990/#project/studio",
  pendingEdits: [], blockers: [], caveat: "Timing/copy preview, not final QC." };

async function main(): Promise<void> {
  assert.deepEqual(parseStudioStatus(ready), ready);
  assert.equal(studioPreviewUrl(null), null);
  for (const url of ["https://example.com/", "http://localhost:3990/#project/studio",
    "http://127.0.0.1:3990/", "http://127.0.0.1:4000/#project/studio",
    "http://user:password@127.0.0.1:3990/#project/studio", "javascript:alert(1)",
    "http://127.0.0.1:3990/api/projects#project/studio", "http://127.0.0.1:3990/?path=/etc#project/studio"]) {
    assert.throws(() => studioPreviewUrl(url), /untrusted preview/);
  }
  for (const change of [{ ok: false }, { state: "approved" }, { url: null },
    { pendingEdits: [null] }, { canOpen: "yes" }, { blockers: "none" }]) {
    assert.throws(() => parseStudioStatus({ ...ready, ...change }));
  }
  const original = globalThis.fetch;
  const calls: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return Response.json(ready);
  };
  try {
    const controller = new AbortController();
    await requestStudioReview("/project/producer", "open", controller.signal);
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { dir: "/project/producer" });
    assert.equal(calls[0].init?.method, "POST");
    assert.equal(calls[0].init?.signal, controller.signal);
    await requestStudioReview("/project/producer", "status", controller.signal);
    assert.equal(calls[1].url, "/api/producer/studio?dir=%2Fproject%2Fproducer");
    assert.equal(calls[1].init?.method, "GET");
    assert.equal(calls[1].init?.body, undefined);
    controller.abort();
    await assert.rejects(requestStudioReview("/p", "open", controller.signal), { name: "AbortError" });
    assert.equal(calls.length, 2);
    globalThis.fetch = async () => Response.json({ error: "Unsynced edits are preserved" }, { status: 409 });
    await assert.rejects(requestStudioReview("/p", "open", new AbortController().signal), /Unsynced edits/);
    assert.equal(calls.length, 2, "no retry/force/sync fallback");
  } finally { globalThis.fetch = original; }
}
void main().then(() => console.log("studio-review-client.test.ts: all assertions passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
