/** Actual final/history reads and TEMP artifacts; native/claim leaves are explicitly TEST-only. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test, { type TestContext } from "node:test";
import { assertOpeningCleanupMetadata, openingCleanupStoreDependencies,
  readCommittedOpeningCleanup, readHistoricalOpeningCleanup } from "../guided-opening-cleanup-store";
import { assertSourceColorFinalCleanupMetadata, readFinalSourceColorCleanupForJournal } from "../guided-source-color-cleanup-final-read";
import { cleanupFinalReadFixture, replaceFinalReadFile } from "./_guided-source-color-cleanup-final-read-fixture";

/** Exercise the actual final reader through the store, replacing only its original native/claim leaves. */
async function fixture(t: TestContext) {
  const value = await cleanupFinalReadFixture(t);
  t.mock.method(openingCleanupStoreDependencies, "final", (input: Parameters<typeof readFinalSourceColorCleanupForJournal>[0]) =>
    readFinalSourceColorCleanupForJournal(input, value.readDependencies));
  return value;
}

test("historical store keeps genuine inner proof without exposing a new public capability", async t => {
  const f = await fixture(t), value = readHistoricalOpeningCleanup(f.readInput.dir, f.current.sha256);
  assert(Object.isFrozen(value));
  assert.equal(value.observationScope, "held-historical-journal-cleanup-not-current-selection-or-source-freshness");
  assert.equal(value.cleanupHash, f.committed.cleanupHash); assert(Buffer.isBuffer(value.bytes));
  assert.equal(value.mediaSelected, false); assert.equal(value.receipt.openingApproved, false);
  assert.doesNotThrow(() => assertOpeningCleanupMetadata(value));
  assert.throws(() => assertSourceColorFinalCleanupMetadata(value as unknown as ReturnType<typeof readFinalSourceColorCleanupForJournal>),
    /actual original read evidence/);
  assert.equal(Object.hasOwn(value, "inner"), false); assert.equal(Object.hasOwn(value, "original"), false);
});

test("same metadata dispatcher accepts actual current store result without changing its private identity", async t => {
  const f = await fixture(t), value = readCommittedOpeningCleanup(f.readInput.dir);
  assert("readBudgetScope" in value);
  assert.doesNotThrow(() => assertSourceColorFinalCleanupMetadata(value));
  assert.doesNotThrow(() => assertOpeningCleanupMetadata(value));
});

test("copied historical/current values and prepared or legacy DTOs cannot borrow store proof", async t => {
  const f = await fixture(t), current = readCommittedOpeningCleanup(f.readInput.dir);
  const historical = readHistoricalOpeningCleanup(f.readInput.dir, f.current.sha256);
  const invalid = [{ ...current }, { ...historical }, JSON.parse(JSON.stringify(historical)), f.recorded.fact,
    { schemaVersion: 1, kind: "guided-opening-cleanup-commit" }];
  for (const value of invalid) {
    assert.throws(() => assertOpeningCleanupMetadata(value as typeof historical), /actual source-color final cleanup store read/);
  }
});

for (const name of ["finalSnapshot", "media", "archive"] as const) {
  test(`historical wrapper retains original ${name} inode after returning`, async t => {
    const f = await fixture(t), value = readHistoricalOpeningCleanup(f.readInput.dir, f.current.sha256);
    const before = fs.readFileSync(f.readFiles[name]); replaceFinalReadFile(f, name);
    assert.deepEqual(fs.readFileSync(f.readFiles[name]), before);
    assert.throws(() => assertOpeningCleanupMetadata(value), /original file identity/);
  });
}

test("historical wrapper cannot substitute its original projection or hide mutable Buffer changes", async t => {
  const f = await fixture(t), value = readHistoricalOpeningCleanup(f.readInput.dir, f.current.sha256);
  assert.equal(Reflect.set(value, "cleanupHash", "a".repeat(64)), false);
  assert.equal(Reflect.set(value, "held", { ...value.held }), false);
  assert.doesNotThrow(() => assertOpeningCleanupMetadata(value));
  value.bytes[0] ^= 1;
  assert.throws(() => assertOpeningCleanupMetadata(value), /returned metadata/);
  assert.deepEqual(fs.readFileSync(f.readFiles.finalSnapshot), f.current.bytes);
});

test("later metadata-only check does not replay callbacks or renew an expired proof-read allowance", async t => {
  const f = await fixture(t); let now = 1000, clockCalls = 0;
  t.mock.method(performance, "now", () => { clockCalls++; return now; });
  const value = readHistoricalOpeningCleanup(f.readInput.dir, f.current.sha256);
  assert("assertCurrent" in value); now += 30_001;
  assert.throws(value.assertCurrent, /observation budget expired/);
  const before = { calls: { ...f.readCalls }, clockCalls };
  assert.doesNotThrow(() => assertOpeningCleanupMetadata(value));
  assert.deepEqual(f.readCalls, before.calls); assert.equal(clockCalls, before.clockCalls);
});

test("historical wrapper still refuses expiry during its original thirty-second read", async t => {
  const f = await fixture(t); let now = 1000;
  t.mock.method(performance, "now", () => now);
  t.mock.method(openingCleanupStoreDependencies, "final", (input: Parameters<typeof readFinalSourceColorCleanupForJournal>[0]) => {
    const value = readFinalSourceColorCleanupForJournal(input, f.readDependencies); now += 30_001; return value;
  });
  assert.throws(() => readHistoricalOpeningCleanup(f.readInput.dir, f.current.sha256), /observation budget expired/);
});
