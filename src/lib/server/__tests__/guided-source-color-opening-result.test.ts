/** Actual V3 stopped/ledger and schema2 result binding; all artifacts are inert TEST metadata. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { readHeldOpeningResult } from "../guided-opening-result";
import { readHeldSourceColorOpeningResult, assertSourceColorOpeningResultMetadata, assertHeldSourceColorOpeningResultUnchanged,
  sourceColorOpeningReadbackReceiptArguments, assertSourceColorOpeningReadbackIdentity } from "../guided-source-color-opening-result";
import { snapshotSourceColorMetadata } from "../guided-source-color-staging-hold";
import { sourceColorOpeningResultFixture, sourceColorResultReadback } from "./_guided-source-color-opening-result-fixture";

test("actual V3 result binds both raw completion and schema2 evidence without opening source-color or media files", t => {
  const f = sourceColorOpeningResultFixture(t), selected = readHeldSourceColorOpeningResult(f.context);
  assert(Buffer.isBuffer(f.held.bytes)); assert(Buffer.isBuffer(selected.record.bytes));
  assert.equal(selected.process.receipt.schemaVersion, 3); assert(selected.process.sourceColor);
  assert.deepEqual(selected.completion, f.completion); assert.deepEqual(selected.record.value.sourceColorEvidence, f.evidence);
  assert.equal(selected.sourceBytesObserved, false); assert.equal(selected.mediaBytesObserved, false); assert.equal(selected.mediaSelected, false);
  assert(!fs.existsSync(f.evidence.path));
  assert.deepEqual(sourceColorOpeningReadbackReceiptArguments(selected), ["--receipt-sha256", f.completion.receiptSha256, "--receipt-hash", f.completion.receiptHash]);
  const before = f.calls(); assertSourceColorOpeningResultMetadata(selected, f.held); assert.equal(f.calls(), before);
  assertHeldSourceColorOpeningResultUnchanged(f.held, selected); assert(f.calls() > before);
  const result = assertSourceColorOpeningReadbackIdentity(JSON.stringify(sourceColorResultReadback(f)), { held: f.held, selected });
  assert.deepEqual(result.sourceColorEvidence, f.completion.sourceColorEvidence); assert.equal(result.colorQualified, false);
  assert.throws(() => readHeldOpeningResult(f.held), /not implemented/);
});

for (const version of [1, 2]) test(`source-color binder refuses legacy process V${version}`, t => {
  const f = sourceColorOpeningResultFixture(t, version);
  assert.throws(() => readHeldSourceColorOpeningResult(f.context)); assert.equal(f.calls(), 0);
});

for (const patch of [{ schemaVersion: 1 }, { status: "failed" }, { openingApproved: true }, { deliveryApproved: 0 },
  { inputPath: "/TEST-unopened/other/input.json" }, { executionInputHash: "e".repeat(64) },
  { executionClaim: { path: "/TEST-unopened/other/claim.json", sha256: "a".repeat(64) } },
  { sourceColorEvidence: { path: "/TEST-unopened/other/source-color-evidence.json", sha256: "c".repeat(64), sizeBytes: 128, receiptHash: "d".repeat(64) } }]) {
  test(`raw result cannot be internally rehashed into mismatched schema2 identity ${JSON.stringify(patch)}`, t => {
    const f = sourceColorOpeningResultFixture(t); Object.assign(f.body, patch); f.publish();
    assert.throws(() => readHeldSourceColorOpeningResult(f.context), /schema|identity|changed/); assert.equal(f.calls(), 0);
  });
}

test("completion cannot substitute the original source-color raw evidence reference", t => {
  const f = sourceColorOpeningResultFixture(t); f.completion.sourceColorEvidence.sha256 = "f".repeat(64); f.publish();
  assert.throws(() => readHeldSourceColorOpeningResult(f.context), /changed/);
});

test("failed actual V3 outcome cannot supply a successful nested completion string", t => {
  const f = sourceColorOpeningResultFixture(t); f.outcome.status = "failed"; f.outcome.error = "TEST failed original worker"; f.publish();
  assert.throws(() => readHeldSourceColorOpeningResult(f.context), /complete resolved/); assert.equal(f.calls(), 0);
});

test("actual V3 completion itself must be schema2, independently from schema2 raw receipt", t => {
  const f = sourceColorOpeningResultFixture(t); f.completion.schemaVersion = 1; f.publish();
  assert.throws(() => readHeldSourceColorOpeningResult(f.context), /schema2/); assert.equal(f.calls(), 0);
});

for (const field of ["resultPath", "inputPath", "claimPath", "intentPath", "outcomePath", "ledgerPath", "priorPath"] as const) {
  test(`first original callback cannot replace pre-captured ${field}`, t => {
    const f = sourceColorOpeningResultFixture(t), file = field === "claimPath" ? f.held.claimPath : f[field];
    f.onGuard(() => f.rewrite(file, fs.readFileSync(file)));
    assert.throws(() => readHeldSourceColorOpeningResult(f.context), /changed/); assert.equal(f.calls(), 1);
  });
}

test("original Buffer and caller object changes during the first guard reject without adopting new state", t => {
  const f = sourceColorOpeningResultFixture(t);
  f.onGuard(() => { f.held.bytes[0] ^= 1; });
  assert.throws(() => readHeldSourceColorOpeningResult(f.context), /changed/);
});

test("actual metadata hold cannot be forged or attached to an equal held claim DTO", t => {
  const f = sourceColorOpeningResultFixture(t), selected = readHeldSourceColorOpeningResult(f.context);
  assert.throws(() => assertSourceColorOpeningResultMetadata({ ...selected }), /actual original/);
  assert.throws(() => assertSourceColorOpeningResultMetadata(selected, snapshotSourceColorMetadata(f.held)), /actual original/);
  f.context.held = snapshotSourceColorMetadata(f.held);
  assert.throws(() => assertSourceColorOpeningResultMetadata(selected), /identity/);
});

test("late returned result Buffer or completion mutation stays bound without callbacks", t => {
  const f = sourceColorOpeningResultFixture(t), selected = readHeldSourceColorOpeningResult(f.context), before = f.calls();
  selected.record.bytes[0] ^= 1;
  assert.throws(() => assertSourceColorOpeningResultMetadata(selected), /changed/); assert.equal(f.calls(), before);
});

test("a returned actual completion cannot later substitute an equal-role source-color ref", t => {
  const f = sourceColorOpeningResultFixture(t), selected = readHeldSourceColorOpeningResult(f.context);
  selected.completion.sourceColorEvidence.sizeBytes++;
  assert.throws(() => sourceColorOpeningReadbackReceiptArguments(selected), /changed/);
});

test("late original remaining guard failure cannot be replaced by a fresh callback", t => {
  const f = sourceColorOpeningResultFixture(t), selected = readHeldSourceColorOpeningResult(f.context);
  f.onGuard(() => { throw new Error("TEST original work deadline expired"); });
  assert.throws(() => assertHeldSourceColorOpeningResultUnchanged(f.held, selected), /deadline expired/);
  f.context.guard = () => {};
  assert.throws(() => assertSourceColorOpeningResultMetadata(selected), /identity/);
});

test("last re-read callback cannot change original raw result bytes", t => {
  const f = sourceColorOpeningResultFixture(t), selected = readHeldSourceColorOpeningResult(f.context), last = f.calls() + 2;
  f.onGuard(() => { if (f.calls() === last) f.rewrite(f.resultPath, fs.readFileSync(f.resultPath)); });
  assert.throws(() => assertHeldSourceColorOpeningResultUnchanged(f.held, selected), /changed/); assert.equal(f.calls(), last);
});

for (const change of [{ sourceColorEvidence: { sha256: "f".repeat(64) } }, { schemaVersion: 1 }, { claimSha256: "e".repeat(64) },
  { receiptSha256: "e".repeat(64) }, { sourceColorRecordsReplayed: false }, { colorQualified: true }]) {
  test(`child schema2 readback never borrows mismatched or approved evidence ${JSON.stringify(change)}`, t => {
    const f = sourceColorOpeningResultFixture(t), selected = readHeldSourceColorOpeningResult(f.context), value = sourceColorResultReadback(f);
    Object.assign(value, change.sourceColorEvidence ? { sourceColorEvidence: { ...f.evidence, ...change.sourceColorEvidence } } : change);
    assert.throws(() => assertSourceColorOpeningReadbackIdentity(JSON.stringify(value), { held: f.held, selected }));
  });
}
