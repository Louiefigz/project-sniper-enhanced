/** Actual pending journal/CAS/record readers; only retained-claim/native provenance is TEST-stubbed. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { readSourceColorCleanupPending, assertSourceColorCleanupPendingMetadata,
  remainingSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { buildSourceColorCleanupPendingJob } from "../guided-source-color-cleanup-pending-job";
import { cleanupPendingReadFixture, replacePendingFile } from "./_guided-source-color-cleanup-pending-read-fixture";
import { canonicalJson } from "../auto-edit-hash";
import { writeGuidedObject } from "../guided-cut-v2-store";

test("actual pending CAS/read keeps a complete Buffer-bearing original journal and exact deterministic job", async t => {
  const f = await cleanupPendingReadFixture(t), value = f.read();
  assert(Buffer.isBuffer(value.held.bytes)); assert.deepEqual(value.held.bytes, f.before.bytes);
  assert.equal(value.pendingJournalHash, f.committed.pendingJournalHash); assert.equal(value.factHash, f.recorded.factHash);
  assert.deepEqual(value.job, buildSourceColorCleanupPendingJob(f.input.held, f.recorded.fact));
  assert.deepEqual(value.result, value.attempt.result); assert.deepEqual(value.fact, f.recorded.fact);
  assert.equal(value.retirementObserved, false); assert.equal(value.mediaSelected, false);
  assert.equal(value.openingApproved, false); assert.equal(value.deliveryApproved, false);
  const before = { ...f.counts }; assertSourceColorCleanupPendingMetadata(value); assert.deepEqual(f.counts, before);
  assert.throws(() => assertSourceColorCleanupPendingMetadata({ ...value }), /actual original read evidence/);
  value.assertCurrent(); assert.equal(f.counts.guard, before.guard + 1); assert.equal(f.counts.remaining, before.remaining + 1);
  const remaining = remainingSourceColorCleanupPending(value); assert(remaining > 0 && remaining < 295_000);
  assert.throws(() => remainingSourceColorCleanupPending({ ...value }), /actual original read evidence/);
});

test("pending full-job comparison rejects every unrelated change, not just pointer drift", async t => {
  const f = await cleanupPendingReadFixture(t), original = JSON.parse(fs.readFileSync(f.files.journal, "utf8"));
  const changes: ((job: typeof original) => void)[] = [job => { job.message = "TEST different message"; },
    job => { job.token = "TEST different token"; }, job => { job.attempts++; }, job => { job.nextEventId++; },
    job => { job.events = []; }, job => { job.events[0].payload.claimRetained = false; },
    job => { job.updatedAt = "2026-09-08T00:00:03.000Z"; }, job => { job.extraUnrelatedField = true; },
    job => { job.ctx.intent.brief = "TEST altered editorial request"; }];
  for (const change of changes) {
    const job = structuredClone(original); change(job); replacePendingFile(f, "journal", Buffer.from(canonicalJson(job)));
    assert.throws(f.read, /deterministic pending job|malformed or incompatible/);
  }
  assert.equal(f.counts.attempt, 0);
});

for (const name of ["journal", "fact", "snapshot", "result"] as const) {
  test(`pending ${name} original inode is captured before the first caller callback`, async t => {
    const f = await cleanupPendingReadFixture(t); let changed = false;
    f.callbacks.guard = () => { if (!changed) { changed = true; replacePendingFile(f, name); } };
    assert.throws(f.read, /original file identity/); assert.equal(f.counts.attempt, 1); // Metadata capture precedes caller admission.
  });
}

for (const name of ["fact", "snapshot", "result"] as const) {
  test(`pending ${name} raw substitution cannot borrow its old hash path`, async t => {
    const f = await cleanupPendingReadFixture(t); replacePendingFile(f, name, Buffer.from("{}"));
    assert.throws(f.read, /changed|raw journal SHA|malformed/); assert.equal(f.counts.attempt, 0);
  });
}

test("first caller callbacks cannot replace original directory, guard or remainder", async t => {
  const f = await cleanupPendingReadFixture(t), original = { ...f.pendingInput };
  const changes = [() => { f.pendingInput.dir += "/TEST-changed"; }, () => { f.pendingInput.guard = () => {}; },
    () => { f.pendingInput.remainingMs = () => 300_000; }];
  for (const change of changes) {
    Object.assign(f.pendingInput, original); f.callbacks.guard = change;
    assert.throws(f.read, /original caller identity/);
  }
  assert.equal(f.counts.attempt, changes.length);
});

test("final actual attempt return cannot mutate already held pending metadata", async t => {
  const f = await cleanupPendingReadFixture(t), attempt = f.pendingDependencies.attempt;
  f.pendingDependencies.attempt = input => { const result = attempt(input); replacePendingFile(f, "result"); return result; };
  assert.throws(f.read, /original file identity/);
});

test("mutating original Buffer bytes in the final actual read callback is rejected", async t => {
  const f = await cleanupPendingReadFixture(t), attempt = f.pendingDependencies.attempt;
  f.pendingDependencies.attempt = input => { const result = attempt(input); input.held.bytes[0] ^= 1; return result; };
  assert.throws(f.read, /original returned metadata/);
});

test("same original deadline is checked after actual attempt bookkeeping", async t => {
  const f = await cleanupPendingReadFixture(t), attempt = f.pendingDependencies.attempt; let now = 1000;
  t.mock.method(performance, "now", () => now); f.callbacks.remaining = () => 1000;
  f.pendingDependencies.attempt = input => { const result = attempt(input); now += 1001; return result; };
  assert.throws(f.read, /original protected deadline expired/);
});

test("retained pending evidence keeps original files and deadline without rebaselining", async t => {
  const f = await cleanupPendingReadFixture(t), value = f.read();
  f.callbacks.remaining = () => 0; assert.throws(() => remainingSourceColorCleanupPending(value), /remainder is invalid/);
  f.callbacks.remaining = () => 295_000; replacePendingFile(f, "snapshot");
  assert.throws(value.assertCurrent, /original file identity/);
  assert.throws(() => assertSourceColorCleanupPendingMetadata(value), /original file identity/);
});

test("an actual earlier attempt cannot validate a different self-consistent pending fact", async t => {
  const f = await cleanupPendingReadFixture(t), fact = structuredClone(f.recorded.fact);
  fact.createdAt = new Date(Date.parse(fact.createdAt) + 1).toISOString();
  writeGuidedObject(f.pendingInput.dir, fact);
  const pending = buildSourceColorCleanupPendingJob(f.input.held, fact);
  replacePendingFile(f, "journal", Buffer.from(canonicalJson(pending)));
  const dependencies = { ...f.pendingDependencies, attempt: (input: Parameters<typeof f.pendingDependencies.attempt>[0]) => {
    f.pendingDependencies.attempt(input); return f.recorded.evidence;
  } };
  assert.throws(() => readSourceColorCleanupPending(f.pendingInput, dependencies), /actual attempt prepared fact/);
});

test("a forged result or cloned attempt does not become authenticated pending evidence", async t => {
  const f = await cleanupPendingReadFixture(t), attempt = f.pendingDependencies.attempt;
  f.pendingDependencies.attempt = input => ({ ...attempt(input) });
  assert.throws(f.read, /actual original read evidence/);
});
