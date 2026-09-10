import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { cutAcceptanceResponse } from "@/app/api/producer/cut-review/accept-response";
import { HumanCutAcceptanceError } from "@/lib/server/human-cut-acceptance";

const decision = { schemaVersion: 1, operation: "accept", idempotencyKey: "12345678-1234-4234-8234-123456789abc",
  expectedToken: "current-paused-job", requestHash: "1".repeat(64), executionKey: "2".repeat(64),
  receiptHash: "3".repeat(64), mediaSha256: "4".repeat(64),
  attestation: { watched: true, listened: true, acceptsExactCut: true, acknowledgesUnfinished: true } };
const result = { ok: true, state: "cut_accepted", scope: "human-cut-only-not-delivery", cutAccepted: true,
  acceptanceHash: "5".repeat(64), requestHash: decision.requestHash, previewAttempt: 1, continuationAttempt: 2, replayed: false } as const;
const status = { ...result, expectedToken: "not-for-browser", workerPid: 123, canRetryContinuation: true,
  acceptanceState: "accepted" as const, waitStoppedAt: "2026-09-06T01:02:03.000Z", timingState: "verified-activation" as const,
  decisionSubmittedAt: "2026-09-06T01:02:03.000Z", caveat: "Cut-only historical human acceptance; not final approval." };

function request(input: { dir?: string; submission?: unknown; query?: string; headers?: Record<string, string>; method?: string }) {
  const method = input.method ?? "POST";
  return new NextRequest(`http://localhost/api/producer/cut-review/accept${input.query ?? ""}`, {
    method, headers: { host: "localhost", "content-type": "application/json", ...input.headers },
    ...(method === "POST" ? { body: JSON.stringify({ dir: input.dir, submission: input.submission ?? decision }) } : {}) });
}

test("local origin and media type rejection precede all body and authority reads", async () => {
  const deny = () => assert.fail("must not enter a service");
  const cases: Record<string, string>[] = [{ origin: "https://example.com" }, { host: "example.com" },
    { "sec-fetch-site": "cross-site" }, { "content-type": "text/plain" }];
  for (const headers of cases) {
    const req = request({ dir: "/unread", headers });
    const response = await cutAcceptanceResponse(req, { accept: deny, retry: deny, status: deny });
    assert.ok([403, 415].includes(response.status)); assert.equal(req.bodyUsed, false);
  }
});

test("explicit POST dispatches once; uncertain accepted handoff never becomes running or final", async () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-cut-response-")));
  const previous = process.env.SNIPER_WORKSPACE_ROOT; process.env.SNIPER_WORKSPACE_ROOT = root;
  const dir = path.join(root, "project", "producer"); mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(root, "project", "project.json"), "{}");
  const calls: string[] = [];
  const services = { accept: async (input: unknown) => { calls.push("accept"); assert.deepEqual(input, { dir, submission: decision }); return result; },
    retry: async () => { calls.push("retry"); return result; }, status: () => assert.fail("POST cannot fall back to a read") };
  try {
    const accepted = await cutAcceptanceResponse(request({ dir }), services);
    assert.equal(accepted.status, 200); assert.deepEqual(await accepted.json(), result);
    assert.equal(accepted.headers.get("cache-control"), "private, no-store");
    const submission = { schemaVersion: 1, operation: "retry-continuation", acceptanceHash: result.acceptanceHash, requestHash: result.requestHash };
    assert.equal((await cutAcceptanceResponse(request({ dir, submission }), services)).status, 200);
    assert.deepEqual(calls, ["accept", "retry"]);
    const pending = await cutAcceptanceResponse(request({ dir }), { ...services,
      accept: async () => { throw new HumanCutAcceptanceError("Worker launch was not confirmed", 409, true); } });
    assert.equal(pending.status, 409); assert.deepEqual(await pending.json(), { ok: false, cutAccepted: true, error: "Worker launch was not confirmed" });
    const history = await cutAcceptanceResponse(request({ dir }), { ...services,
      accept: async () => { throw new HumanCutAcceptanceError("Worker is interrupted; refresh project status", 409, true); } });
    assert.equal(history.status, 409); assert.equal((await history.json()).cutAccepted, true);
  } finally {
    if (previous === undefined) delete process.env.SNIPER_WORKSPACE_ROOT; else process.env.SNIPER_WORKSPACE_ROOT = previous;
    rmSync(root, { recursive: true, force: true });
  }
});

test("accepted status is a read-only allowlist without process/token leakage or invented delivery scope", async () => {
  const deny = () => assert.fail("GET must never accept or spawn");
  let reads = 0;
  const services = { accept: deny, retry: deny, status: () => { reads += 1; return status; } };
  const response = await cutAcceptanceResponse(request({ method: "GET", query: "?dir=/project/producer" }), services);
  const body = await response.json();
  assert.equal(response.status, 200); assert.equal(reads, 1);
  assert.equal(body.canRetryContinuation, true); assert.equal(body.cutAccepted, true);
  for (const field of ["workerPid", "expectedToken", "replayed", "acceptanceState", "finalApproved"]) assert.equal(field in body, false);
  for (const query of ["", "?dir=/p&force=true", "?dir=/p&dir=/p"]) {
    assert.equal((await cutAcceptanceResponse(request({ method: "GET", query }), services)).status, 400);
  }
  assert.equal(reads, 1, "invalid query cannot read authority");
});
