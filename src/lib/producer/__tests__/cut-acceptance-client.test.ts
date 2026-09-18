import assert from "node:assert/strict";
import { test } from "node:test";
import { cutAcceptanceSubmission, storedCutAcceptanceSubmission, parseCutAcceptanceSubmission,
  parseCutAcceptanceResult, submitCutAcceptance } from "../cut-acceptance-client";
import type { CutReviewDescription } from "../cut-review-client";

const review = { requestHash: "1".repeat(64), executionKey: "2".repeat(64), receiptHash: "3".repeat(64),
  mediaSha256: "4".repeat(64), expectedToken: "exact-waiting-job" } as CutReviewDescription;
const uuid = "12345678-1234-4234-8234-123456789abc";
const result = { ok: true, state: "cut_accepted", scope: "human-cut-only-not-delivery", cutAccepted: true,
  acceptanceHash: "5".repeat(64), requestHash: review.requestHash, previewAttempt: 1, continuationAttempt: 2, replayed: false };

function storage() {
  const values = new Map<string, string>();
  return { values, getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value); } };
}

test("explicit human decision retains one exact identity through retry and reopened UI", () => {
  const saved = storage(); let keys = 0;
  const input = { review, storage: saved, newKey: () => { keys += 1; return uuid; } };
  const submission = cutAcceptanceSubmission(input);
  assert.equal(submission.idempotencyKey, uuid); assert.equal(keys, 1);
  assert.deepEqual(cutAcceptanceSubmission(input), submission); assert.equal(keys, 1);
  const reloadedStorage = { getItem: saved.getItem, setItem: saved.setItem };
  assert.deepEqual(cutAcceptanceSubmission({ ...input, storage: reloadedStorage }), submission);
  assert.equal(keys, 1);
  assert.equal(submission.expectedToken, review.expectedToken);
  assert.deepEqual(submission.attestation, { watched: true, listened: true, acceptsExactCut: true, acknowledgesUnfinished: true });
});

test("changed stored decision or unavailable persistence cannot invent a replacement retry", () => {
  const saved = storage();
  cutAcceptanceSubmission({ review, storage: saved, newKey: () => uuid });
  const before = [...saved.values];
  for (const changed of [{ expectedToken: "another-job" }, { mediaSha256: "0".repeat(64) }]) {
    assert.throws(() => cutAcceptanceSubmission({ review: { ...review, ...changed }, storage: saved,
      newKey: () => assert.fail("must not create a new decision") }), /differs/);
    assert.deepEqual([...saved.values], before);
  }
  assert.throws(() => cutAcceptanceSubmission({ review, newKey: () => uuid,
    storage: { getItem: () => null, setItem: () => {} } }), /retain/);
  assert.throws(() => cutAcceptanceSubmission({ review, storage: storage(), newKey: () => "bad-key" }), /identity/);
});

test("decision results distinguish pending continuation from running and never mean final approval", () => {
  assert.deepEqual(parseCutAcceptanceResult(result, review.requestHash), result);
  assert.equal(parseCutAcceptanceResult({ ...result, state: "running", replayed: true }).state, "running");
  for (const changed of [{ state: "complete" }, { scope: "approved-final" }, { cutAccepted: false },
    { acceptedFinal: true }, { acceptanceHash: "none" }, { continuationAttempt: 1 }, { previewAttempt: 0 },
    { continuationAttempt: Infinity }, { replayed: "true" }, { requestHash: "0".repeat(64) }]) {
    assert.throws(() => parseCutAcceptanceResult({ ...result, ...changed }, review.requestHash));
  }
});

test("submit sends only the exact decision once and preserves ambiguous failure for recheck", async () => {
  const submission = cutAcceptanceSubmission({ review, storage: storage(), newKey: () => uuid });
  const input = { dir: "/private/tmp/project/producer", submission, signal: new AbortController().signal };
  const calls: unknown[] = [];
  const request: typeof fetch = async (url, init) => {
    calls.push(JSON.parse(String(init?.body)));
    assert.equal(url, "/api/producer/cut-review/accept"); assert.equal(init?.method, "POST");
    assert.equal(init?.redirect, "error"); assert.equal(init?.cache, "no-store");
    return Response.json(result);
  };
  assert.deepEqual(await submitCutAcceptance(input, request), result);
  assert.deepEqual(calls, [{ dir: input.dir, submission }]);
  let attempts = 0;
  await assert.rejects(submitCutAcceptance(input, async () => { attempts += 1; throw new Error("response lost"); }), /response lost/);
  assert.equal(attempts, 1, "no automatic second POST or fresh run");
  await assert.rejects(submitCutAcceptance(input, async () => Response.json({ ok: false, cutAccepted: true,
    error: "Worker launch needs retry" }, { status: 409 })), /Cut accepted, but continuation needs attention/);
  await assert.rejects(submitCutAcceptance(input, async () => Response.json({ ...result, state: "complete" })), /identities or scope/);
});

test("pre-canceled submission sends nothing", async () => {
  const signal = AbortSignal.abort();
  const submission = cutAcceptanceSubmission({ review, storage: storage(), newKey: () => uuid });
  await assert.rejects(submitCutAcceptance({ dir: "/p", submission, signal },
    async () => assert.fail("must not POST")), { name: "AbortError" });
});

test("unfinished-verification recovery only replays a prior exact decision, never creates one", () => {
  const saved = storage();
  assert.equal(storedCutAcceptanceSubmission(review, saved), null);
  assert.equal(saved.values.size, 0);
  const original = cutAcceptanceSubmission({ review, storage: saved, newKey: () => uuid });
  assert.deepEqual(storedCutAcceptanceSubmission(review, saved), original);
  const reordered = Object.fromEntries(Object.entries(original).reverse());
  assert.deepEqual(parseCutAcceptanceSubmission(reordered, review), original);
  for (const changed of [null, [], { ...original, expectedToken: "other" }, { ...original, force: true },
    { ...original, idempotencyKey: "1234" }, { ...original, attestation: { ...original.attestation, listened: false } }]) {
    assert.throws(() => parseCutAcceptanceSubmission(changed, review));
  }
});
