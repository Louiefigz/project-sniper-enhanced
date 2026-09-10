import assert from "node:assert/strict";
import test from "node:test";
import {
  parseSourceColorOpeningReadback,
  SOURCE_COLOR_READBACK_STAGES,
} from "../../producer/contracts/guided-opening-result-v2";

/** Pure transport fixture; these paths are never opened and grant no authority. */
function readback(elapsedMs: number, stageElapsedMs: number) {
  return {
    schemaVersion: 2,
    kind: "guided-opening-media-readback",
    status: "verified",
    executionId: "11111111-2222-4333-8444-555555555555",
    inputSha256: "a".repeat(64),
    executionInputHash: "b".repeat(64),
    claimSha256: "c".repeat(64),
    receiptPath: "/TEST-unopened/rounding/media-result.json",
    receiptSha256: "d".repeat(64),
    receiptHash: "e".repeat(64),
    sourceColorEvidence: {
      path: "/TEST-unopened/rounding/source-color-evidence.json",
      sha256: "f".repeat(64),
      receiptHash: "0".repeat(64),
      sizeBytes: 1024,
    },
    scope: "exact-source-color-held-private-media-not-opening-or-delivery-approval",
    elapsedMs,
    stages: SOURCE_COLOR_READBACK_STAGES.map(stage => ({ stage, status: "complete", elapsedMs: stageElapsedMs })),
    sourceColorRecordsReplayed: true,
    basePictureConsumptionVerified: true,
    gamutMeasured: false,
    gradeApplied: false,
    colorQualified: false,
    processGroupAndDockerCleanup: "requires-separate-owned-server-observation",
    currentJournalAndLease: "requires-separate-owned-server-observation",
    openingApproved: false,
    deliveryApproved: false,
  };
}

test("eleven 2ms stages cannot fit an independently rounded 11ms total", () => {
  const value = readback(11, 2);
  assert.equal(value.stages.length, 11);
  // Each duration rounding to 2ms is at least 1.5ms, so the true total
  // is at least 16.5ms. It cannot round to 11ms under nearest rounding.
  assert.throws(() => parseSourceColorOpeningReadback(JSON.stringify(value)), /stage sum/);
});

test("eleven sequential rounded stages never gain more than 6ms aggregate slack", () => {
  const sum = SOURCE_COLOR_READBACK_STAGES.length * 2;
  for (const excess of [7, 8, 9, 10, 11]) {
    const value = readback(sum - excess, 2);
    assert.throws(() => parseSourceColorOpeningReadback(JSON.stringify(value)), /stage sum/);
  }
});

test("the conservative half-even rounding endpoint remains supported", () => {
  // Python round(1.5) == 2, and round(11 * 1.5) == 16.
  // This is a rounding-boundary fixture, not measured runtime evidence.
  const value = readback(16, 2);
  assert.deepEqual(parseSourceColorOpeningReadback(JSON.stringify(value)), value);
});

test("unattributed elapsed time remains allowed without inventing a stage", () => {
  const value = readback(1_500_000, 1);
  assert.deepEqual(parseSourceColorOpeningReadback(JSON.stringify(value)), value);
});
