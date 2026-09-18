/** Historical metadata tests: actual archive/raw records/ledger, no native or journal authority. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { readSourceColorCleanupAttempt, assertSourceColorCleanupAttemptMetadata } from "../guided-source-color-cleanup-attempt-read";
import { cleanupAttemptReadFixture, mutateAttemptRecord, replaceAttemptFile } from "./_guided-source-color-cleanup-attempt-read-fixture";

test("actual raw history retains every join, immutable output and explicit not-retirement scope", async t => {
  const f = await cleanupAttemptReadFixture(t), value = f.read();
  assert.deepEqual(value.fact, f.fact); assert.deepEqual(value.result, f.result); assert.deepEqual(value.tools, f.tools);
  assert.equal(value.result.schemaVersion, 2); assert.equal(canonicalJsonSha256(value.result), f.fact.cleanupResultHash);
  assert.equal(value.retirementObserved, false); assert.equal(value.mediaSelected, false);
  assert.equal(value.openingApproved, false); assert.equal(value.deliveryApproved, false);
  assert.equal(value.scope, "historical-exact-source-color-cleanup-attempt-not-retirement-or-approval");
  assert(Object.isFrozen(value.output)); assert(Object.isFrozen(value.tools)); assert(Object.isFrozen(value.result.sourceColor.batch.jobs));
  assert.equal(Object.isFrozen(f.readInput), false); assert.equal(Object.isFrozen(f.fact), false);
  const before = { ...f.checks }; assertSourceColorCleanupAttemptMetadata(value); assert.deepEqual(f.checks, before);
  assert.throws(() => assertSourceColorCleanupAttemptMetadata({ ...value }), /actual original read/);
  value.assertCurrent(); assert.equal(f.checks.guard, before.guard + 1); assert.equal(f.checks.remaining, before.remaining + 1);
});

test("stop exposes the already-held actual projection without an extra process read or mutable authority", async t => {
  const f = await cleanupAttemptReadFixture(t); let calls = 0;
  const dependencies = { ...f.readerDependencies, stopped: () => { calls++; return structuredClone(f.actual); } };
  const value = readSourceColorCleanupAttempt(f.readInput, dependencies);
  assert.equal(calls, 2); assert.deepEqual(value.stop, f.actual); assert.notEqual(value.stop, f.actual);
  assert(Object.isFrozen(value.stop)); assert(Object.isFrozen(value.stop.receipt)); assert(Object.isFrozen(value.stop.sourceColor));
  assert.equal(Reflect.set(value.stop, "receiptSha256", "0".repeat(64)), false);
  assertSourceColorCleanupAttemptMetadata(value); assert.equal(calls, 2);
  value.assertCurrent(); assert.equal(calls, 3); assert.deepEqual(value.stop, f.actual);
});

test("historical read does not open active, sidecar, source jobs or current tool paths", async t => {
  const f = await cleanupAttemptReadFixture(t), active = f.staged.reservation.path;
  assert.equal(active, path.join(f.staging.root, ".sniper-color-resource/active.json"));
  assert.equal(fs.realpathSync(active), active); const stat = fs.lstatSync(active);
  assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  fs.renameSync(active, path.join(f.staging.root, "TEST-original-active-retained.json"));
  fs.writeFileSync(active, "TEST unrelated later reservation\n", { flag: "wx", mode: 0o600 });
  const forbidden = [active, f.staged.input.path, f.tools.script, f.tools.runnerScript, f.tools.python,
    f.tools.pythonResolved, f.tools.venvConfig, ...f.staged.jobs.map(job => job.input.path)];
  const originalOpen = fs.openSync, originalRead = fs.readFileSync;
  t.mock.method(fs, "openSync", (...args: Parameters<typeof fs.openSync>) => {
    assert(!forbidden.includes(String(args[0])), `history unexpectedly opened ${String(args[0])}`);
    return originalOpen(...args);
  });
  t.mock.method(fs, "readFileSync", (...args: Parameters<typeof fs.readFileSync>) => {
    assert(!forbidden.includes(String(args[0])), `history unexpectedly read ${String(args[0])}`);
    return originalRead(...args);
  });
  const evidence = f.read(); evidence.assertCurrent(); assertSourceColorCleanupAttemptMetadata(evidence);
  t.mock.restoreAll();
  assert.equal(fs.readFileSync(active, "utf8"), "TEST unrelated later reservation\n");
});

for (const name of ["start", "invocation", "output"] as const) {
  test(`historical ${name} raw SHA cannot be replaced by self-consistent record bytes`, async t => {
    const f = await cleanupAttemptReadFixture(t);
    replaceAttemptFile(f, `${name}.json`, Buffer.from("{}")); assert.throws(f.read, /raw SHA/);
  });
}

const badStart: [string, (row: Record<string, unknown>) => void][] = [
  ["old schema", row => { row.schemaVersion = 1; }], ["extra key", row => { row.approved = false; }],
  ["initial instead of post-process journal", row => { row.beforeJournalHash = "2".repeat(64); }],
  ["wrong request", row => { (row.sourceColor as { sourceColorHash: string }).sourceColorHash = "2".repeat(64); }],
  ["clock inversion", row => { row.startedAt = "2026-09-07T00:00:00.000Z"; }],
];
for (const [name, mutation] of badStart) {
  test(`start exact contract rejects ${name} even with a matching TEST raw SHA`, async t => {
    const f = await cleanupAttemptReadFixture(t); mutateAttemptRecord(f, "start", mutation);
    assert.throws(f.read, /differs|unknown|unexpected|unsupported|chronological/);
  });
}

const badOutput: [string, (row: Record<string, unknown>) => void][] = [
  ["missing cleanup settlement", row => { row.cleanupProcessGroupStopped = false; }],
  ["unresolved nested cleanup", row => { row.cleanupNestedOwnership = "unresolved"; }],
  ["wrong invocation", row => { row.invocationSha256 = "2".repeat(64); }],
  ["wrong ledger namespace", row => { (row.ledger as { path: string }).path = "/TEST/unowned-ledger"; }],
  ["excess child duration", row => { row.elapsedMs = 3998; }],
  ["clock inversion", row => { row.observedAt = "2026-09-07T00:00:00.000Z"; }],
  ["non-string stdout", row => { row.stdout = {}; }],
];
for (const [name, mutation] of badOutput) {
  test(`output exact contract rejects ${name} even with a matching TEST raw SHA`, async t => {
    const f = await cleanupAttemptReadFixture(t); mutateAttemptRecord(f, "output", mutation);
    assert.throws(f.read, /incomplete|differs|chronological/);
  });
}

test("ordered reservation names cannot be reordered in an otherwise successful result", async t => {
  const f = await cleanupAttemptReadFixture(t);
  mutateAttemptRecord(f, "output", row => {
    const result = JSON.parse(String(row.stdout)); result.sourceColor.batch.jobs.reverse();
    row.stdout = JSON.stringify(result); f.fact.cleanupResultHash = canonicalJsonSha256(result);
  });
  assert.throws(f.read, /ordered names/);
});

test("both media and cleanup nested ownership must actually be resolved by the code reader", async t => {
  const f = await cleanupAttemptReadFixture(t);
  const unresolved = { ...f.readerDependencies, descendants: () => ({ live: [], unknown: [], unrecordedSpawns: ["TEST child intent"] }) };
  assert.throws(() => readSourceColorCleanupAttempt(f.readInput, unresolved), /unresolved original cleanup descendants/);
  const older = { ...f.readerDependencies, stopped: () => ({ ...f.actual,
    receipt: { ...f.actual.receipt, schemaVersion: 2 } }) };
  assert.throws(() => readSourceColorCleanupAttempt(f.readInput, older), /resolved original V3/);
});
