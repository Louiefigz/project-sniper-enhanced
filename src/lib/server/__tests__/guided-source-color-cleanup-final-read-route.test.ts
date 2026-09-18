/** Real current/historical shared-store routing. Native/claim leaves remain TEST metadata, never approval. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { readCommittedOpeningCleanup, readHistoricalOpeningCleanup, openingCleanupStoreDependencies } from "../guided-opening-cleanup-store";
import { readFinalSourceColorCleanupForJournal } from "../guided-source-color-cleanup-final-read";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { canonicalJson } from "../auto-edit-hash";
import { cleanupFinalReadFixture, replaceFinalReadFile } from "./_guided-source-color-cleanup-final-read-fixture";
type FinalInput = Parameters<typeof readFinalSourceColorCleanupForJournal>[0];

test("store defaults to actual final reader and preserves the final discriminant/hash/stop", async t => {
  assert.equal(openingCleanupStoreDependencies.final, readFinalSourceColorCleanupForJournal);
  const f = await cleanupFinalReadFixture(t); let calls = 0;
  t.mock.method(openingCleanupStoreDependencies, "final", (input: FinalInput) => { calls++; return readFinalSourceColorCleanupForJournal(input, f.readDependencies); });
  const value = readCommittedOpeningCleanup(f.readInput.dir);
  assert.equal(calls, 1); assert.equal(value.cleanupHash, f.committed.cleanupHash);
  assert.equal(value.receipt.schemaVersion, 2); assert.equal(value.receipt.kind, "guided-opening-source-color-cleanup-commit");
  assert.deepEqual(value.evidence.stop, f.actual); assert.equal(value.mediaSelected, false);
});

test("shared historical path observes only the named final snapshot after later current journal changes", async t => {
  const f = await cleanupFinalReadFixture(t);
  t.mock.method(openingCleanupStoreDependencies, "final", (input: FinalInput) => readFinalSourceColorCleanupForJournal(input, f.readDependencies));
  replaceFinalReadFile(f, "journal", Buffer.from("{\"TEST\":\"later current journal\"}"));
  const value = readHistoricalOpeningCleanup(f.readInput.dir, f.current.sha256);
  assert.equal(value.sha256, f.current.sha256); assert.equal(value.cleanupHash, f.committed.cleanupHash);
  assert.equal(value.observationScope, "held-historical-journal-cleanup-not-current-selection-or-source-freshness");
  assert.throws(() => readCommittedOpeningCleanup(f.readInput.dir), /malformed or incompatible/);
});

test("prepared and unsupported V2 receipts cannot enter final dispatch or borrow a final identity", async t => {
  const f = await cleanupFinalReadFixture(t); let calls = 0;
  t.mock.method(openingCleanupStoreDependencies, "final", (input: FinalInput) => { calls++; return readFinalSourceColorCleanupForJournal(input, f.readDependencies); });
  const rows = [f.recorded.fact, { ...f.recorded.fact, kind: "guided-opening-source-color-cleanup-commit-unknown" }];
  for (const row of rows) {
    const hash = writeGuidedObject(f.readInput.dir, row), job = structuredClone(f.current.job);
    job.guidedHandoffV2!.openingCleanupHash = hash; replaceFinalReadFile(f, "journal", Buffer.from(canonicalJson(job)));
    assert.throws(() => readCommittedOpeningCleanup(f.readInput.dir), /unknown|unexpected|unsupported|not exact/);
  }
  assert.equal(calls, 0);
});

test("a legacy discriminant stays on the unchanged strict legacy parser, never final dispatch", async t => {
  const f = await cleanupFinalReadFixture(t); let calls = 0;
  t.mock.method(openingCleanupStoreDependencies, "final", (input: FinalInput) => { calls++; return readFinalSourceColorCleanupForJournal(input, f.readDependencies); });
  const hash = writeGuidedObject(f.readInput.dir, { schemaVersion: 1, kind: "guided-opening-cleanup-commit", TEST: "malformed legacy" });
  const job = structuredClone(f.current.job); job.guidedHandoffV2!.openingCleanupHash = hash;
  replaceFinalReadFile(f, "journal", Buffer.from(canonicalJson(job)));
  assert.throws(() => readCommittedOpeningCleanup(f.readInput.dir), /opening cleanup commit/); assert.equal(calls, 0);
});

test("one 30s observation remainder starts at wrapper entry and is not an old cleanup or nested allowance", async t => {
  const f = await cleanupFinalReadFixture(t); let now = 1000, entries = 0;
  t.mock.method(performance, "now", () => now);
  t.mock.method(openingCleanupStoreDependencies, "final", (input: FinalInput) => {
    entries++; now += 10_000; assert.equal(input.remainingMs(), 20_000);
    const value = readFinalSourceColorCleanupForJournal(input, f.readDependencies);
    now += 20_001; return value;
  });
  assert.throws(() => readCommittedOpeningCleanup(f.readInput.dir), /observation budget expired/); assert.equal(entries, 1);
});

test("wrapper last-read tail rejects same-byte original journal or final fact replacement", async t => {
  for (const name of ["journal", "fact"] as const) await t.test(name, async t => {
    const f = await cleanupFinalReadFixture(t);
    t.mock.method(openingCleanupStoreDependencies, "final", (input: FinalInput) => {
      const value = readFinalSourceColorCleanupForJournal(input, f.readDependencies); replaceFinalReadFile(f, name); return value;
    });
    assert.throws(() => readCommittedOpeningCleanup(f.readInput.dir), /original file identity/);
    assert.deepEqual(fs.readFileSync(f.readFiles.journal), f.current.bytes);
  });
});

test("a copied final result cannot replace the actual private metadata-held read", async t => {
  const f = await cleanupFinalReadFixture(t);
  t.mock.method(openingCleanupStoreDependencies, "final", (input: FinalInput) => ({ ...readFinalSourceColorCleanupForJournal(input, f.readDependencies) }));
  assert.throws(() => readCommittedOpeningCleanup(f.readInput.dir), /actual original read evidence/);
  assert.equal(observeHumanCutJob(f.readInput.dir).sha256, f.current.sha256);
});
