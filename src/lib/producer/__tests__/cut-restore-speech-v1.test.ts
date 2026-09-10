import assert from "node:assert/strict";
import { parseCutRestoreSpeechV1 } from "../contracts/cut-restore-speech-v1";
import { parseEditBatchV1 } from "../contracts/edit-batch";
import { cutRestoreAction, fixtureSha } from "./_cut-restore-speech-fixture";

const base = {
  projectRevisionHash: fixtureSha("1"),
  planContentHash: fixtureSha("a"),
  manifestHash: fixtureSha("b"),
  sourceSnapshotSetHash: fixtureSha("c"),
  timelineMapHash: fixtureSha("e"),
  canvasProfileHash: fixtureSha("f"),
  destinationProfileHashes: [fixtureSha("3")],
  pictureLockHash: fixtureSha("2"),
};
const envelope = {
  schemaVersion: 1,
  operationId: "50000000-0000-4000-8000-000000000001",
  clauseId: "30000000-0000-4000-8000-000000000001",
  action: cutRestoreAction(),
};
const batch = {
  schemaVersion: 1,
  batchId: "40000000-0000-4000-8000-000000000001",
  requestId: "10000000-0000-4000-8000-000000000001",
  idempotencyKey: "20000000-0000-4000-8000-000000000001",
  stage: "cut",
  atomic: true,
  preserveUnrelated: true,
  base,
  operations: [envelope],
};

const action = parseCutRestoreSpeechV1(cutRestoreAction());
assert.equal(action.operation, "cut.restoreSpeech");
assert.equal(action.totalOutputFramesBefore, action.totalOutputFramesAfter);
assert.equal(action.replaceableAudioEvidenceHash, fixtureSha("a"));
assert.equal(parseEditBatchV1(batch).stage, "cut");
assert.deepEqual(
  parseCutRestoreSpeechV1({
    ...cutRestoreAction(),
    speed: { numerator: "2", denominator: "1" },
  }).speed,
  { numerator: "2", denominator: "1" },
);

assert.throws(
  () => parseEditBatchV1({ ...batch, stage: "treatment" }),
  /another stage/,
);
assert.throws(
  () => parseEditBatchV1({
    ...batch,
    base: { ...base, pictureLockHash: fixtureSha("9") },
  }),
  /parent lock and timeline/,
);
assert.throws(
  () => parseCutRestoreSpeechV1({
    ...cutRestoreAction(),
    totalOutputFramesAfter: 361,
  }),
  /non-ripple/,
);
const unsafe = cutRestoreAction();
delete unsafe.replaceableAudioEvidenceHash;
assert.throws(
  () => parseCutRestoreSpeechV1(unsafe),
  /replaceableAudioEvidenceHash/,
);

const picture = cutRestoreAction();
delete picture.replacedAudioSampleRanges;
delete picture.replaceableAudioEvidenceHash;
Object.assign(picture, {
  method: "extend-and-reclaim-silence",
  pictureDirtyWindows: [{ startFrame: 40, endFrameExclusive: 70 }],
  audioDirtyWindows: [{ startFrame: 40, endFrameExclusive: 70 }],
  audioDirtySampleRanges: [{
    startSample: 64_000,
    endSampleExclusive: 112_000,
  }],
  sourceVideoFrameRange: { startFrame: 31, endFrameExclusive: 33 },
  sourceFrameRate: { numerator: "30", denominator: "1" },
  reclaimedSilence: {
    silenceId: "silence-1",
    sourceSampleRange: {
      startSample: 10_000,
      endSampleExclusive: 13_200,
    },
    outputFrameRange: { startFrame: 40, endFrameExclusive: 42 },
  },
  quantizationResidualSamples: 800,
  residualPolicy: "reclaimed-proved-silence",
  unchangedPictureMappingRanges: [
    { startFrame: 0, endFrameExclusive: 40 },
    { startFrame: 70, endFrameExclusive: 360 },
  ],
});
assert.deepEqual(
  parseCutRestoreSpeechV1(picture).sourceVideoFrameRange,
  { startFrame: 31, endFrameExclusive: 33 },
);
delete picture.sourceFrameRate;
assert.throws(
  () => parseCutRestoreSpeechV1(picture),
  /sourceFrameRate/,
);

console.log("cut-restore-speech-v1 tests passed");
