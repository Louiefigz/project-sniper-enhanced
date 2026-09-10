/** Actual saved pending/CAS/attempt records; only original claim/native provenance uses explicit TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test, { type TestContext } from "node:test";
import { readRetainedSourceColorCleanupPending, assertSourceColorCleanupPendingMetadata,
  remainingSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { canonicalJson } from "../auto-edit-hash";
import { atomicCreateFileSync } from "../atomic-file";
import { cleanupPendingReadFixture, replacePendingFile } from "./_guided-source-color-cleanup-pending-read-fixture";

/** Save the actual pending bytes before simulated final CAS; never weaken the current-reader fixture. */
async function historyFixture(t: TestContext) {
  const current = await cleanupPendingReadFixture(t), hash = current.current.sha256;
  saveHumanCutJobSnapshot(current.pendingInput.dir, current.current);
  const journal = path.join(current.pendingInput.dir, "human-cut-job-snapshots", `${hash}.json`);
  assert(journal.startsWith(current.staging.root + path.sep));
  return { ...current, currentFixture: current, hash, files: { ...current.files, journal },
    readHistory: () => readRetainedSourceColorCleanupPending(current.pendingInput, hash, current.pendingDependencies) };
}

test("explicit retained pending read survives changed current journal without granting current or retirement scope", async t => {
  const f = await historyFixture(t), current = f.read(), retained = f.readHistory();
  const currentScope: "current-pending-source-color-cleanup-not-retirement-or-approval" = current.scope;
  const historyScope: "retained-pending-source-color-cleanup-not-retirement-or-approval" = retained.scope;
  assert.notEqual(currentScope, historyScope); assert.equal(retained.pendingJournalHash, current.pendingJournalHash);
  assert.deepEqual(retained.job, current.job); assert.deepEqual(retained.fact, current.fact);
  assert.deepEqual(retained.result, current.result); assert(Buffer.isBuffer(retained.held.bytes));
  assert.equal(retained.retirementObserved, false); assert.equal(retained.mediaSelected, false);
  assert.equal(retained.openingApproved, false); assert.equal(retained.deliveryApproved, false);
  replacePendingFile(f.currentFixture, "journal", Buffer.from("{\"TEST\":\"unrelated current journal\"}"));
  assert.throws(current.assertCurrent, /original file identity/);
  const counts = { ...f.counts }; assertSourceColorCleanupPendingMetadata(retained); assert.deepEqual(f.counts, counts);
  retained.assertCurrent(); assert(remainingSourceColorCleanupPending(retained) > 0);
  assert.deepEqual(f.readHistory().job, retained.job);
  assert.throws(() => assertSourceColorCleanupPendingMetadata({ ...retained }), /actual original read evidence/);
  assert.throws(() => remainingSourceColorCleanupPending({ ...retained }), /actual original read evidence/);
});

test("explicit retained pending read never opens a missing current journal", async t => {
  const f = await historyFixture(t), file = f.currentFixture.files.journal;
  assert(file.startsWith(f.staging.root + path.sep)); assert.equal(fs.realpathSync(file), file);
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  fs.renameSync(file, path.join(path.dirname(file), "TEST-retired-current-journal.json"));
  f.readHistory().assertCurrent(); assert.throws(f.read, /ENOENT/);
});

test("retained hash is explicit and exact, never an automatic current journal fallback", async t => {
  const f = await historyFixture(t), input = f.pendingInput, dependencies = f.pendingDependencies;
  assert.throws(() => readRetainedSourceColorCleanupPending(input, "../invalid", dependencies), /SHA|hash/);
  const hash = "f".repeat(64), file = path.join(input.dir, "human-cut-job-snapshots", `${hash}.json`);
  assert.throws(() => readRetainedSourceColorCleanupPending(input, hash, dependencies), /ENOENT/);
  assert(file.startsWith(f.staging.root + path.sep)); atomicCreateFileSync(file, f.current.bytes);
  assert.throws(() => readRetainedSourceColorCleanupPending(input, hash, dependencies), /retained pending raw journal SHA/);
  assert.equal(f.counts.attempt, 0);
});

test("even a correctly hashed retained snapshot must equal the entire deterministic pending job", async t => {
  const f = await historyFixture(t), original = f.current.job;
  const changes = [(job: typeof original) => { job.message = "TEST unrelated message"; },
    (job: typeof original) => { job.nextEventId++; },
    (job: typeof original) => { job.token = "TEST changed token"; }];
  for (const change of changes) {
    const job = structuredClone(original); change(job);
    replacePendingFile(f.currentFixture, "journal", Buffer.from(canonicalJson(job)));
    const snapshot = observeHumanCutJob(f.pendingInput.dir); saveHumanCutJobSnapshot(f.pendingInput.dir, snapshot);
    assert.throws(() => readRetainedSourceColorCleanupPending(f.pendingInput, snapshot.sha256, f.pendingDependencies), /deterministic pending job/);
  }
  assert.equal(f.counts.attempt, 0);
});

for (const name of ["journal", "fact", "snapshot", "result"] as const) {
  test(`retained ${name} is held before the first caller callback with no post-CAS exclusions`, async t => {
    const f = await historyFixture(t); let changed = false;
    f.callbacks.guard = () => { if (!changed) { changed = true; replacePendingFile(f, name); } };
    assert.throws(f.readHistory, /original file identity/); assert.equal(f.counts.attempt, 1); // Capture only, before stopped-record observation.
  });
}

test("retained pending reader preserves original caller identities before its first callback", async t => {
  const f = await historyFixture(t), original = { ...f.pendingInput };
  const changes = [() => { f.pendingInput.dir += "/TEST-changed"; }, () => { f.pendingInput.guard = () => {}; },
    () => { f.pendingInput.remainingMs = () => 300_000; }];
  for (const change of changes) {
    Object.assign(f.pendingInput, original); f.callbacks.guard = change;
    assert.throws(f.readHistory, /original caller identity/);
  }
  assert.equal(f.counts.attempt, changes.length);
});

test("last actual attempt callback cannot replace the retained pending snapshot", async t => {
  const f = await historyFixture(t), attempt = f.pendingDependencies.attempt;
  f.pendingDependencies.attempt = input => { const result = attempt(input); replacePendingFile(f, "journal"); return result; };
  assert.throws(f.readHistory, /original file identity/);
});

test("retained pending lifetime rejects final expiry and later snapshot replacement", async t => {
  const f = await historyFixture(t), value = f.readHistory(), attempt = f.pendingDependencies.attempt; let now = 1000;
  t.mock.method(performance, "now", () => now); f.callbacks.remaining = () => 1000;
  f.pendingDependencies.attempt = input => { const result = attempt(input); now += 1001; return result; };
  assert.throws(f.readHistory, /original protected deadline expired/);
  f.callbacks.remaining = () => 0; assert.throws(() => remainingSourceColorCleanupPending(value), /remainder is invalid/);
  f.callbacks.remaining = () => 295_000; replacePendingFile(f, "journal");
  assert.throws(value.assertCurrent, /original file identity/);
  assert.throws(() => assertSourceColorCleanupPendingMetadata(value), /original file identity/);
});
