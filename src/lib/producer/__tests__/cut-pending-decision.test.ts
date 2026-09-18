import assert from "node:assert/strict";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { pendingCutDecisionResponse } from "@/app/api/producer/cut-review/decision-response";
import { fetchPendingCutDecision, parsePendingCutDecision } from "../cut-pending-decision-client";
import type { CutReviewDescription } from "../cut-review-client";

const review = { requestHash: "1".repeat(64), executionKey: "2".repeat(64), receiptHash: "3".repeat(64),
  mediaSha256: "4".repeat(64), expectedToken: "exact-paused-job" } as CutReviewDescription;
const submission = { schemaVersion: 1, operation: "accept", idempotencyKey: "12345678-1234-4234-8234-123456789abc",
  expectedToken: review.expectedToken, requestHash: review.requestHash, executionKey: review.executionKey,
  receiptHash: review.receiptHash, mediaSha256: review.mediaSha256,
  attestation: { watched: true, listened: true, acceptsExactCut: true, acknowledgesUnfinished: true } } as const;
const envelope = { ok: true, scope: "previously-submitted-human-cut-decision-not-new-approval",
  requestHash: review.requestHash, submission } as const;
const query = new URLSearchParams({ dir: "/p", requestHash: review.requestHash, executionKey: review.executionKey, receiptHash: review.receiptHash });

test("pending recovery requires a closed exact prior decision, not new or upgraded approval", () => {
  assert.deepEqual(parsePendingCutDecision(envelope, review), submission);
  for (const change of [{ ok: false }, { scope: "new-approval" }, { requestHash: "0".repeat(64) }, { workerPid: 123 },
    { submission: { ...submission, idempotencyKey: "new" } },
    { submission: { ...submission, attestation: { ...submission.attestation, watched: false } } }]) {
    assert.throws(() => parsePendingCutDecision({ ...envelope, ...change }, review));
  }
});

test("cross-tab recovery is one bounded read with no local storage or implicit POST", async () => {
  const input = { dir: "/p", review, signal: new AbortController().signal };
  let calls = 0;
  const request: typeof fetch = async (url, init) => {
    calls += 1; assert.equal(url, `/api/producer/cut-review/decision?${query}`);
    assert.equal(init?.method, undefined); assert.equal(init?.cache, "no-store"); assert.equal(init?.redirect, "error");
    return Response.json(envelope);
  };
  assert.deepEqual(await fetchPendingCutDecision(input, request), submission); assert.equal(calls, 1);
  await assert.rejects(fetchPendingCutDecision({ ...input, signal: AbortSignal.abort() }, request), { name: "AbortError" });
  assert.equal(calls, 1);
  await assert.rejects(fetchPendingCutDecision(input, async () => Response.json({ error: "Cut already accepted; refresh status" }, { status: 409 })), /already accepted/);
});

test("pending decision route validates local origin and all preview identities before returning readback", async () => {
  let reads = 0;
  const read = () => { reads += 1; return envelope; };
  const req = (suffix: string, headers: Record<string, string> = {}) => new NextRequest(
    `http://localhost/api/producer/cut-review/decision?${suffix}`, { headers: { host: "localhost", ...headers } });
  assert.equal((await pendingCutDecisionResponse(req(String(query), { origin: "https://example.com" }), read)).status, 403);
  for (const suffix of ["dir=/p", `${query}&force=true`, `${query}&dir=/p`, String(query).replace(review.receiptHash, "bad")]) {
    assert.equal((await pendingCutDecisionResponse(req(suffix), read)).status, 400);
  }
  assert.equal(reads, 0);
  assert.equal((await pendingCutDecisionResponse(req(String(query).replace(review.receiptHash, "0".repeat(64))), read)).status, 409);
  const response = await pendingCutDecisionResponse(req(String(query)), read);
  assert.equal(response.status, 200); assert.equal(response.headers.get("cache-control"), "private, no-store");
  assert.deepEqual(await response.json(), envelope); assert.equal(reads, 2);
});
