import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { RequestFailure } from "@/app/api/producer/auto-edit/request-failure";

const require = createRequire(import.meta.url), HASH = "a".repeat(64), DIR = "/private/tmp/TEST-only/producer";
const ID = "11111111-1111-4111-8111-111111111111", URL = "http://localhost:3327/api/producer/guided-opening/launch";
const submission = { schemaVersion: 1, operation: "prepare-guided-opening", idempotencyKey: ID,
  expectedToken: "TEST", expectedJournalHash: HASH, proposalReadinessHash: HASH, treatmentDraftRevisionHash: HASH };
const counts = { launch: 0, read: 0, canonical: 0 };
const result = { ok: true, replayed: false, state: "launch-recorded", journalHash: HASH, requestId: ID,
  openingApproved: false, bodyGenerated: false, deliveryApproved: false };
const status = { ok: true, state: "unavailable", detail: "TEST metadata only", request: null, receivedAt: null };

/** Swap module cache before importing the route: no actual service, source observation or process invocation. */
function replace(file: string, patch: Record<string, unknown>) {
  const resolved = require.resolve(file), original = require(resolved), entry = require.cache[resolved]!;
  entry.exports = { ...original, ...patch }; return () => { entry.exports = original; };
}
const restore = [
  replace("../guided-opening-launcher", { launchGuidedOpening: async (value: unknown) => { counts.launch++; assert.deepEqual(value, { dir: DIR, submission }); return result; } }),
  replace("../guided-opening-launch-status", { readGuidedOpeningLaunchStatus: (dir: string) => { counts.read++; assert.equal(dir, DIR); return status; } }),
  replace("../../../app/api/producer/auto-edit/request", { canonicalProducerDir: (dir: unknown) => { counts.canonical++; if (dir !== DIR) throw new RequestFailure("TEST foreign project", 403); return DIR; } }),
];
const route = require("../../../app/api/producer/guided-opening/launch/route") as { GET: (r: NextRequest) => Promise<Response>; POST: (r: NextRequest) => Promise<Response> };
restore.forEach((done) => done());

function request(options: { method?: string; query?: string; body?: unknown; headers?: Record<string, string> } = {}) {
  const method = options.method ?? "GET";
  return new NextRequest(URL + (options.query ?? `?dir=${encodeURIComponent(DIR)}`), { method,
    headers: { host: "localhost:3327", origin: "http://localhost:3327", "content-type": "application/json", ...options.headers },
    ...(method === "POST" ? { body: typeof options.body === "string" ? options.body : JSON.stringify(options.body ?? { dir: DIR, submission }) } : {}) });
}

test("local GET only reads bounded dir metadata; explicit POST records exact submission with 202", async () => {
  const read = await route.GET(request()); assert.equal(read.status, 200); assert.deepEqual(await read.json(), status);
  const sent = await route.POST(request({ method: "POST", query: "" })); assert.equal(sent.status, 202); assert.deepEqual(await sent.json(), result);
  assert.equal(sent.headers.get("cache-control"), "private, no-store"); assert.equal(counts.launch, 1); assert.equal(counts.read, 1);
});

test("closed query/body/local policy rejects before the mocked service is reached", async () => {
  const before = { ...counts };
  for (const query of ["", "?dir=", `?dir=${DIR}&dir=${DIR}`, `?dir=${DIR}&approved=true`, `?dir=${"x".repeat(4097)}`]) {
    assert.equal((await route.GET(request({ query }))).status, 400);
  }
  for (const body of ["{", "null", "[]", { dir: DIR }, { dir: DIR, submission, approved: true },
    { dir: DIR, submission: { ...submission, approved: true } }, { dir: DIR, submission: { ...submission, idempotencyKey: "invalid" } }]) {
    assert.equal((await route.POST(request({ method: "POST", query: "", body }))).status, 400);
  }
  assert.equal((await route.POST(request({ method: "POST" }))).status, 400);
  assert.equal((await route.POST(request({ method: "POST", query: "", body: "x".repeat(16_385) }))).status, 413);
  const badHeaders: Record<string, string>[] = [{ host: "evil.example" }, { origin: "https://evil.example" }, { "sec-fetch-site": "cross-site" }];
  for (const headers of badHeaders) {
    assert.equal((await route.GET(request({ headers }))).status, 403);
    assert.equal((await route.POST(request({ method: "POST", query: "", headers }))).status, 403);
  }
  assert.equal((await route.POST(request({ method: "POST", query: "", headers: { "content-type": "text/plain" } }))).status, 415);
  assert.equal(counts.read, before.read); assert.equal(counts.launch, before.launch);
});

test("a stalled streaming body reaches its exact 10-second deadline without calling the launcher", async (t) => {
  const before = counts.launch; let cancelled = false;
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const body = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new TextEncoder().encode("{")); }, cancel() { cancelled = true; } });
  const req = new NextRequest(URL, { method: "POST", headers: { host: "localhost:3327", "content-type": "application/json" }, body, duplex: "half" } as ConstructorParameters<typeof NextRequest>[1]);
  const pending = route.POST(req); t.mock.timers.tick(10_001);
  assert.equal((await pending).status, 408); assert.equal(cancelled, true); assert.equal(counts.launch, before);
});

test("foreign project and disconnected bodies fail before launch without mutating the submitted UUID", async () => {
  const before = counts.launch;
  assert.equal((await route.POST(request({ method: "POST", query: "", body: { dir: "/OTHER", submission } }))).status, 403);
  const controller = new AbortController(); controller.abort();
  const aborted = new NextRequest(URL, { method: "POST", headers: { host: "localhost:3327", "content-type": "application/json" },
    body: JSON.stringify({ dir: DIR, submission }), signal: controller.signal });
  assert.equal((await route.POST(aborted)).status, 400); assert.equal(counts.launch, before); assert.equal(submission.idempotencyKey, ID);
});
