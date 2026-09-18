import assert from "node:assert/strict";
import test from "node:test";
import { parseOpeningMediaCompletion, parseOpeningMediaReadback } from "../../producer/contracts/guided-opening-result-v1";
import { parseSourceColorOpeningCompletion, parseSourceColorOpeningReadback, SOURCE_COLOR_READBACK_STAGES } from "../../producer/contracts/guided-opening-result-v2";

function completion() {
  return { schemaVersion: 2, kind: "guided-opening-media-completion", status: "complete",
    executionId: "11111111-2222-4333-8444-555555555555", inputSha256: "a".repeat(64), executionInputHash: "b".repeat(64),
    executionClaimSha256: "c".repeat(64), receiptPath: "/TEST-unopened/owned/media-result.json",
    receiptSha256: "d".repeat(64), receiptHash: "e".repeat(64), openingApproved: false, deliveryApproved: false,
    sourceColorEvidence: { path: "/TEST-unopened/owned/source-color-evidence.json", sha256: "f".repeat(64),
      sizeBytes: 1024, receiptHash: "0".repeat(64) } };
}

function readback() {
  const { executionClaimSha256, ...value } = completion();
  return { ...value, kind: "guided-opening-media-readback", status: "verified", claimSha256: executionClaimSha256,
    scope: "exact-source-color-held-private-media-not-opening-or-delivery-approval", elapsedMs: 100,
    stages: SOURCE_COLOR_READBACK_STAGES.map(stage => ({ stage, status: "complete", elapsedMs: 1 })),
    sourceColorRecordsReplayed: true, basePictureConsumptionVerified: true, gamutMeasured: false, gradeApplied: false,
    colorQualified: false, processGroupAndDockerCleanup: "requires-separate-owned-server-observation",
    currentJournalAndLease: "requires-separate-owned-server-observation" };
}

test("schema2 completion is shape-only exact detached JSON; no file is read", () => {
  const value = completion(), result = parseSourceColorOpeningCompletion(JSON.stringify(value));
  assert.deepEqual(result, value);
  value.sourceColorEvidence.sha256 = "9".repeat(64);
  assert.notEqual(result.sourceColorEvidence.sha256, value.sourceColorEvidence.sha256);
});

test("schema2 readback requires both observation replay and base-consumption stages", () => {
  assert.deepEqual(parseSourceColorOpeningReadback(JSON.stringify(readback())), readback());
});

test("legacy and source-color completion protocols never upgrade one another", () => {
  const { sourceColorEvidence: omitted, ...legacy } = completion();
  assert.ok(omitted);
  assert.throws(() => parseOpeningMediaCompletion(JSON.stringify(completion())));
  assert.throws(() => parseSourceColorOpeningCompletion(JSON.stringify({ ...legacy, schemaVersion: 1 })));
  assert.throws(() => parseOpeningMediaReadback(JSON.stringify(readback())));
});

test("completion rejects missing, extra and truthy approval fields", () => {
  const { sourceColorEvidence: omitted, ...partial } = completion();
  assert.ok(omitted);
  for (const value of [partial, { ...completion(), unknown: false }, { ...completion(), schemaVersion: 3 },
    { ...completion(), openingApproved: true }, { ...completion(), deliveryApproved: 0 }]) {
    assert.throws(() => parseSourceColorOpeningCompletion(JSON.stringify(value)));
  }
});

test("evidence reference cannot redirect to another directory, role, type or oversized artifact", () => {
  const original = completion();
  for (const changed of [{ path: "/TEST-unopened/foreign/source-color-evidence.json" }, { path: "/TEST-unopened/owned/other.json" },
    { path: "/TEST-unopened/owned/../source-color-evidence.json" }, { sizeBytes: true }, { sizeBytes: 0 },
    { sizeBytes: 16 * 1024 * 1024 + 1 }, { sha256: "bad" }, { receiptHash: "A".repeat(64) }, { unexpected: false }]) {
    assert.throws(() => parseSourceColorOpeningCompletion(JSON.stringify({ ...original,
      sourceColorEvidence: { ...original.sourceColorEvidence, ...changed } })));
  }
});

test("schema2 stdout rejects duplicate decoded keys including escaped spellings", () => {
  const raw = JSON.stringify(completion());
  assert.throws(() => parseSourceColorOpeningCompletion(raw.replace('"schemaVersion":2', '"schemaVersion":1,"schemaVersion":2')), /duplicate/);
  assert.throws(() => parseSourceColorOpeningCompletion(raw.replace('"schemaVersion":2', '"schemaVersion":1,"schema\\u0056ersion":2')), /duplicate/);
  assert.throws(() => parseSourceColorOpeningCompletion(raw.replace('"sizeBytes":1024', '"sizeBytes":0,"sizeBytes":1024')), /duplicate/);
});

test("stdout has one bounded object, with no last-completion fallback", () => {
  const raw = JSON.stringify(completion());
  for (const text of [raw + raw, "progress\n" + raw, " ".repeat(128 * 1024) + raw, raw.replace('"sizeBytes":1024', '"sizeBytes":1e999'),
    raw.replace('"sizeBytes":1024', '"sizeBytes":' + "[".repeat(17) + "0" + "]".repeat(17))]) {
    assert.throws(() => parseSourceColorOpeningCompletion(text));
  }
});

test("readback cannot assert color quality, grading, cleanup or a lease", () => {
  for (const changed of [{ sourceColorRecordsReplayed: false }, { basePictureConsumptionVerified: false },
    { gamutMeasured: true }, { gradeApplied: true }, { colorQualified: true }, { openingApproved: true },
    { processGroupAndDockerCleanup: "verified" }, { currentJournalAndLease: "verified" }, { scope: "approved" }]) {
    assert.throws(() => parseSourceColorOpeningReadback(JSON.stringify({ ...readback(), ...changed })));
  }
});

test("readback rejects omitted, reordered, failed and extra stages", () => {
  const value = readback();
  for (const stages of [value.stages.slice(1), [...value.stages].reverse(), [...value.stages, value.stages[0]],
    value.stages.map((row, index) => index === 0 ? { ...row, status: "failed" } : row)]) {
    assert.throws(() => parseSourceColorOpeningReadback(JSON.stringify({ ...value, stages })));
  }
});

test("readback preserves the existing25-minute cap and strictly typed measured durations", () => {
  for (const elapsedMs of [-1, true, 1.5, 1_500_001]) {
    assert.throws(() => parseSourceColorOpeningReadback(JSON.stringify({ ...readback(), elapsedMs })));
  }
  const value = readback(); value.stages[0].elapsedMs = 101;
  assert.throws(() => parseSourceColorOpeningReadback(JSON.stringify(value)));
});

test("stage sum permits only independent millisecond rounding, not duplicated work budgets", () => {
  const value = readback(); value.elapsedMs = 16;
  value.stages.forEach(row => { row.elapsedMs = 2; });
  assert.deepEqual(parseSourceColorOpeningReadback(JSON.stringify(value)), value);
  value.stages[0].elapsedMs = 3;
  assert.throws(() => parseSourceColorOpeningReadback(JSON.stringify(value)), /stage sum/);
});
