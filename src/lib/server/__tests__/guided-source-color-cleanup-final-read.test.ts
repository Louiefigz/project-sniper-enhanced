/** Actual final/pending/attempt/ack records; original admission/native leaves remain explicitly TEST-stubbed. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import test from "node:test";
import { readFinalSourceColorCleanupForJournal, assertSourceColorFinalCleanupMetadata } from "../guided-source-color-cleanup-final-read";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { canonicalJson } from "../auto-edit-hash";
import { parseFinalSourceColorCleanupFact } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";
import { cleanupFinalReadFixture, replaceFinalReadFile, retainedFinalReadInput, rebindFinalReadFact,
  finalReadFaultFile, type FinalReadFixture } from "./_guided-source-color-cleanup-final-read-fixture";

/** Change only the exact TEST journal, then supply its actual freshly observed bytes. */
function journal(f: FinalReadFixture, job: typeof f.current.job): void {
  replaceFinalReadFile(f, "journal", Buffer.from(canonicalJson(job)));
  f.readInput.journal.observed = observeHumanCutJob(f.readInput.dir);
}

test("actual final receipt and stop remain truthful after original cleanup leases and allowance are retired", async t => {
  const f = await cleanupFinalReadFixture(t); f.projectLease.release(); f.staging.resource.lease.release();
  f.callbacks.remaining = () => { throw new Error("TEST old cleanup allowance must never be consulted"); };
  const value = f.read();
  assert.equal(value.receipt.kind, "guided-opening-source-color-cleanup-commit"); assert.equal(value.receipt.phase, "retired");
  assert.equal(value.cleanupHash, f.committed.cleanupHash); assert.notEqual(value.cleanupHash, f.recorded.factHash);
  assert.deepEqual(value.held.bytes, f.before.bytes); assert(Buffer.isBuffer(value.held.bytes));
  assert.deepEqual(value.evidence.stop, f.actual); assert.equal(value.evidence.stop, value.pending.attempt.stop);
  assert.equal(value.evidence.start, value.pending.attempt.start); assert.equal(value.evidence.output, value.pending.attempt.output);
  assert.equal(value.evidence.result, value.pending.attempt.result); assert.equal(value.retirementAck.disposition, "unlinked-original");
  assert.equal(value.mediaSelected, false); assert.equal(value.openingApproved, false); assert.equal(value.deliveryApproved, false);
  const counts = { ...f.readCalls }; assertSourceColorFinalCleanupMetadata(value); assert.deepEqual(f.readCalls, counts);
  value.assertCurrent(); assert.equal(f.readCalls.guard, counts.guard + 1); assert.equal(f.readCalls.remaining, counts.remaining + 1);
  assert.throws(() => assertSourceColorFinalCleanupMetadata({ ...value }), /actual original read evidence/);
});

test("retained final history never opens current journal, new active reservation or current source/tool/job files", async t => {
  const f = await cleanupFinalReadFixture(t), input = retainedFinalReadInput(f), active = f.staged.reservation.path;
  f.projectLease.release(); f.staging.resource.lease.release();
  assert(active.startsWith(f.staging.root + path.sep)); assert.equal(fs.realpathSync(path.dirname(active)), path.dirname(active));
  assert.throws(() => fs.lstatSync(active), { code: "ENOENT" }); fs.writeFileSync(active, "TEST later reservation", { flag: "wx", mode: 0o600 });
  replaceFinalReadFile(f, "journal", Buffer.from("{\"TEST\":\"later unrelated job\"}"));
  const forbidden = [active, f.readFiles.journal, f.staged.input.path, f.tools.script, f.tools.runnerScript,
    f.tools.python, f.tools.pythonResolved, f.tools.venvConfig, ...f.staged.jobs.map(row => row.input.path)];
  const open = fs.openSync, read = fs.readFileSync;
  t.mock.method(fs, "openSync", (...args: Parameters<typeof fs.openSync>) => { assert(!forbidden.includes(String(args[0]))); return open(...args); });
  t.mock.method(fs, "readFileSync", (...args: Parameters<typeof fs.readFileSync>) => { assert(!forbidden.includes(String(args[0]))); return read(...args); });
  const value = readFinalSourceColorCleanupForJournal(input, f.readDependencies); value.assertCurrent(); assertSourceColorFinalCleanupMetadata(value);
  t.mock.restoreAll(); assert.equal(fs.readFileSync(active, "utf8"), "TEST later reservation");
});

test("only exact supplied current or SHA-named snapshot paths and original observed bytes are accepted", async t => {
  const f = await cleanupFinalReadFixture(t), input = f.readInput;
  for (const file of [f.readFiles.ack, path.join(input.dir, "human-cut-job-snapshots", `${"a".repeat(64)}.json`)]) {
    assert.throws(() => readFinalSourceColorCleanupForJournal({ ...input, journal: { ...input.journal, path: file } }, f.readDependencies), /journal path/);
  }
  const observed = { ...input.journal.observed, bytes: Buffer.from("{}") };
  assert.throws(() => readFinalSourceColorCleanupForJournal({ ...input, journal: { ...input.journal, observed } }, f.readDependencies), /outer raw journal/);
  assert.equal(f.readCalls.history, 0);
});

test("unselected outer job must be the complete deterministic final transition", async t => {
  const f = await cleanupFinalReadFixture(t), original = f.current.job;
  const changes = [(job: typeof original) => { job.message = "TEST different message"; }, (job: typeof original) => { job.events = []; },
    (job: typeof original) => { job.nextEventId++; }, (job: typeof original) => { job.updatedAt = new Date(Date.parse(job.updatedAt) + 1).toISOString(); }];
  for (const change of changes) {
    const changed = structuredClone(original); change(changed); journal(f, changed); assert.throws(f.read, /entire deterministic final job/);
  }
});

test("selection/approval additions tolerate only their exact journal changes and confer no approval from cleanup", async t => {
  const f = await cleanupFinalReadFixture(t), selected = structuredClone(f.current.job);
  Object.assign(selected.guidedHandoffV2!, { openingMediaSelectionHash: "a".repeat(64), openingApprovalHash: "b".repeat(64) });
  selected.message = "TEST separately selected and approved"; selected.events = []; selected.nextEventId += 2;
  selected.updatedAt = new Date(Date.parse(selected.updatedAt) + 1).toISOString(); journal(f, selected);
  const value = f.read(); assert.equal(value.mediaSelected, false); assert.equal(value.openingApproved, false);
  const changes = [(job: typeof selected) => { job.token += "-different"; }, (job: typeof selected) => { job.artifactToken = "TEST other artifact"; },
    (job: typeof selected) => { job.attempts++; }, (job: typeof selected) => { job.checkpoint = "queued"; },
    (job: typeof selected) => { job.phase = "TEST-other" as typeof job.phase; },
    (job: typeof selected) => { job.guidedHandoffV2!.openingExecutionClaimHash = f.input.held.claimHash; },
    (job: typeof selected) => { job.guidedHandoffV2!.openingProcessOutcomeHash = f.recorded.fact.processOutcomeSha256; }];
  for (const change of changes) {
    const changed = structuredClone(selected); change(changed);
    assert.throws(() => { journal(f, changed); f.read(); }, /stable selected\/approved job|malformed or incompatible/);
  }
});

for (const name of ["journal", "fact", "ack", "pending", "prepared", "result", "original", "media", "output", "archive"] as const) {
  test(`final ${name} metadata is captured before the first caller guard`, async t => {
    const f = await cleanupFinalReadFixture(t); let changed = false;
    f.readCallbacks.guard = () => { if (!changed) { changed = true; replaceFinalReadFile(f, name); } };
    assert.throws(f.read, /identity changed|parent identity/);
  });
}

test("prepared cleanup cannot be relabeled as a final receipt", async t => {
  const f = await cleanupFinalReadFixture(t), job = structuredClone(f.current.job);
  job.guidedHandoffV2!.openingCleanupHash = f.recorded.factHash; journal(f, job);
  assert.throws(f.read, /unknown|unexpected|unsupported|Unsupported final/); assert.equal(f.readCalls.history, 0);
});

test("ack raw bound, full metadata bindings and chronology are independent requirements", async t => {
  const f = await cleanupFinalReadFixture(t), original = readCutPreviewObject(f.readFiles.ack).value;
  const fact = parseFinalSourceColorCleanupFact(readCutPreviewObject(f.readFiles.fact).value);
  const changes = [(ack: typeof original) => { ack.claimHash = "a".repeat(64); },
    (ack: typeof original) => { ack.preparedFactHash = "a".repeat(64); },
    (ack: typeof original) => { ack.observedAt = new Date(Date.parse(fact.createdAt) + 1).toISOString(); }];
  for (const change of changes) {
    const ack = structuredClone(original); change(ack); const bytes = Buffer.from(canonicalJson(ack));
    replaceFinalReadFile(f, "ack", bytes);
    rebindFinalReadFact(f, { ...fact, retirementAck: { ...fact.retirementAck, sha256: createHash("sha256").update(bytes).digest("hex"), sizeBytes: bytes.length } });
    assert.throws(f.read, /acknowledgement bindings|not chronological/);
  }
  replaceFinalReadFile(f, "ack", Buffer.alloc(128 * 1024 + 1, 32)); assert.throws(f.read, /bound|large|size/);
});

test("last callback may not replace outer context or already-held metadata", async t => {
  const f = await cleanupFinalReadFixture(t), original = { ...f.readInput };
  const changes = [() => { f.readInput.journal = { ...original.journal }; },
    () => { f.readInput.remainingMs = () => 30_000; }, () => { f.readInput.guard = () => {}; }];
  for (const change of changes) {
    Object.assign(f.readInput, original); f.readCallbacks.remaining = change; assert.throws(f.read, /context changed|caller identity/);
  }
});

test("final history return and original 30s observation cutoff are checked without callback rebaselining", async t => {
  const f = await cleanupFinalReadFixture(t), history = f.readDependencies.history; let now = 1000;
  t.mock.method(performance, "now", () => now); f.readInput.remainingMs = () => 30_000;
  f.readDependencies.history = (input, hash) => { const value = history(input, hash); now += 30_001; return value; };
  assert.throws(f.read, /observation budget expired/);
  f.readDependencies.history = (input, hash) => { const value = history(input, hash); replaceFinalReadFile(f, "ack"); return value; };
  assert.throws(f.read, /original file identity/);
});

test("later metadata and assertCurrent retain all files and immutable actual read identity", async t => {
  const f = await cleanupFinalReadFixture(t), value = f.read();
  assert(Object.isFrozen(value.receipt)); assert(Object.isFrozen(value.retirementAck));
  finalReadFaultFile(f, "ack"); replaceFinalReadFile(f, "ack");
  assert.throws(() => assertSourceColorFinalCleanupMetadata(value), /original file identity/);
  assert.throws(value.assertCurrent, /original file identity/);
});
