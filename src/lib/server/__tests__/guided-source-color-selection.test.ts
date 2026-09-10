/** Metadata/CAS qualification only: no native source or playback validation is performed in these tests. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { readSelectedOpeningMedia, readHistoricalOpeningSelection, selectVerifiedOpeningMediaUnderLease,
  assertOpeningSelectionMetadata } from "../guided-opening-selection";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { assertSourceColorOpeningReadbackMetadata } from "../guided-source-color-readback";
import { readSourceColorSelection } from "../guided-source-color-selection-read";
import { sourceColorSelectionFixture, replaceSelectionFixtureFile } from "./_guided-source-color-selection-fixture";

test("actual schema2 selection CAS retains historical proof while the old current verifier becomes stale", async t => {
  const f = await sourceColorSelectionFixture(t), committed = f.select(), current = observeHumanCutJob(f.input.dir);
  assert.equal(fs.statSync(f.files.core).mode & 0o777, 0o644);
  assert.equal(committed.fact.schemaVersion, 2); assert.equal(committed.mediaSelected, true); assert.equal(committed.openingApproved, false);
  assert.equal(current.job.guidedHandoffV2!.openingMediaSelectionHash, committed.selectionHash);
  assert.throws(() => assertSourceColorOpeningReadbackMetadata(f.verified), /changed|identity/);
  assert.doesNotThrow(() => assertOpeningSelectionMetadata(committed));
  const selected = readSelectedOpeningMedia(f.input.dir); assert.equal(selected.selectionHash, committed.selectionHash);
  assert.equal(selected.rows.core.audioSamples, 48048); assertOpeningSelectionMetadata(selected);
  saveHumanCutJobSnapshot(f.input.dir, current); const historical = readHistoricalOpeningSelection(f.input.dir, current.sha256);
  assert.equal(historical.selectionHash, committed.selectionHash); assertOpeningSelectionMetadata(historical);
  assert.equal(f.calls.native, 1);
});

test("source selection refuses copied verifiers or different original callback/lease before publication", async t => {
  const f = await sourceColorSelectionFixture(t), before = observeHumanCutJob(f.input.dir).sha256;
  const changes = [{ verified: { ...f.verified } }, { remainingMs: () => f.input.remainingMs() }, { lease: { ...f.input.lease } }];
  for (const change of changes) assert.throws(() => selectVerifiedOpeningMediaUnderLease({ ...f.input, ...change }), /actual|original|owner/);
  assert.equal(observeHumanCutJob(f.input.dir).sha256, before); assert.equal(f.calls.remaining, 0);
});

test("readiness callback cannot change original source result or reservation metadata before selection", async t => {
  const f = await sourceColorSelectionFixture(t), before = observeHumanCutJob(f.input.dir).sha256;
  f.callbacks.readiness = () => replaceSelectionFixtureFile(f, "archive");
  assert.throws(f.select, /changed|identity/); assert.equal(observeHumanCutJob(f.input.dir).sha256, before);
});

test("original remaining callback cannot substitute the source owner after verification", async t => {
  const f = await sourceColorSelectionFixture(t), before = observeHumanCutJob(f.input.dir).sha256;
  f.callbacks.remaining = () => { f.input.remainingMs = () => 30_000; };
  assert.throws(f.select, /owner changed/); assert.equal(observeHumanCutJob(f.input.dir).sha256, before);
});

test("source selection metadata never downgrades a genuine or copied handle by changing fact version", async t => {
  const f = await sourceColorSelectionFixture(t), committed = f.select(), selected = readSelectedOpeningMedia(f.input.dir);
  assert.throws(() => assertOpeningSelectionMetadata({ ...committed }), /actual/);
  assert.throws(() => assertOpeningSelectionMetadata({ ...selected }), /actual/);
  selected.fact.schemaVersion = 1; assert.throws(() => assertOpeningSelectionMetadata(selected), /changed/);
  committed.fact.schemaVersion = 1; assert.throws(() => assertOpeningSelectionMetadata(committed), /changed/);
});

test("cold first borrowed callback cannot replace retained readback output after selection", async t => {
  const f = await sourceColorSelectionFixture(t); f.select(); let calls = 0;
  assert.throws(() => readSelectedOpeningMedia(f.input.dir, () => { if (++calls === 1) replaceSelectionFixtureFile(f, "output"); }), /changed|identity/);
});

test("cold and later finite source checks retain actual media metadata but never replay old callbacks", async t => {
  const f = await sourceColorSelectionFixture(t); f.select(); let expired = false;
  const selected = readSelectedOpeningMedia(f.input.dir, () => { if (expired) throw new Error("TEST expired old guard"); });
  expired = true; assert.doesNotThrow(() => assertOpeningSelectionMetadata(selected));
  replaceSelectionFixtureFile(f, "core"); assert.throws(() => assertOpeningSelectionMetadata(selected), /changed/);
});

test("failed readiness cannot publish selection or retroactive readback failure", async t => {
  const f = await sourceColorSelectionFixture(t), before = observeHumanCutJob(f.input.dir).sha256;
  f.callbacks.readiness = () => { throw new Error("TEST readiness changed"); };
  assert.throws(f.select, /readiness changed/); assert.equal(observeHumanCutJob(f.input.dir).sha256, before);
  assert.equal(fs.existsSync(f.verified.receipt.path.replace("verified.json", "selection.json")), false);
  assert.equal(fs.existsSync(f.verified.receipt.path.replace("verified.json", "failure.json")), false);
});

test("direct cold helper cannot authenticate altered fact flags against an unrelated actual publication hash", async t => {
  const f = await sourceColorSelectionFixture(t); f.select(); const selected = readSelectedOpeningMedia(f.input.dir);
  assert.throws(() => readSourceColorSelection({ dir: f.input.dir, observed: selected.observed, selectionHash: selected.selectionHash,
    fact: { ...selected.fact, openingApproved: true } }, () => {}), /fact|metadata/);
});
