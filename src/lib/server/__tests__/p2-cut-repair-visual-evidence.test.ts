import assert from "node:assert/strict";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { parseCutRestoreSpeechV1 } from
  "../../producer/contracts/cut-restore-speech-v1";
import { cutRestoreAction } from
  "../../producer/__tests__/_cut-restore-speech-fixture";
import { validateCutRepairPromotionEvidence } from
  "../producer-cut-repair-promotion-evidence";
import { promotionEvidence } from
  "./_p2-cut-repair-promotion-fixture";

const hash = (value: string): string => value.repeat(64);
function pictureOperation() {
  const value = cutRestoreAction();
  delete value.replacedAudioSampleRanges;
  delete value.replaceableAudioEvidenceHash;
  Object.assign(value, {
    method: "extend-and-reclaim-silence",
    pictureDirtyWindows: [{ startFrame: 40, endFrameExclusive: 70 }],
    audioDirtyWindows: [{ startFrame: 40, endFrameExclusive: 70 }],
    audioDirtySampleRanges: [{
      startSample: 64_000, endSampleExclusive: 112_000,
    }],
    sourceVideoFrameRange: { startFrame: 31, endFrameExclusive: 33 },
    sourceFrameRate: { numerator: "30", denominator: "1" },
    reclaimedSilence: {
      silenceId: "silence-1",
      sourceSampleRange: {
        startSample: 10_000, endSampleExclusive: 13_200,
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
  return parseCutRestoreSpeechV1(value);
}

const operation = pictureOperation();
const operationHash = canonicalJsonSha256(operation);
const candidateHash = hash("2");
const selectionReceiptHash = hash("3");

function frameRange(): Record<string, unknown> {
  return {
    firstFrame: 30,
    endFrameExclusive: 60,
    fpsNumerator: 30,
    fpsDenominator: 1,
  };
}

function sampleRange(): Record<string, unknown> {
  return {
    startSample: 48_000,
    endSampleExclusive: 96_000,
    sampleRate: 48_000,
  };
}

function visualImplementation(): Record<string, unknown> {
  return {
    toolManifestHash: hash("8"),
    ffmpegSha256: hash("9"),
    runtimeSha256: hash("a"),
    implementationSha256: hash("b"),
    implementationScope: "visual-choice-seam-repository-code-v1",
    implementationNonClaims: [
      "audio-seam-measurement",
      "candidate-qc-orchestration-storage-or-promotion",
      "python-stdlib-os-dylibs",
    ],
    implementationClosureHash: hash("c"),
    implementationFileHashes: [
      { role: "controller", sha256: hash("b") },
      { role: "media-decoder", sha256: hash("c") },
      { role: "receipt-projector", sha256: hash("d") },
      { role: "visual-value-types", sha256: hash("e") },
      { role: "authority-hashing", sha256: hash("f") },
      { role: "candidate-qc-value-types", sha256: hash("0") },
      { role: "candidate-qc-visual-adapter", sha256: hash("1") },
      { role: "candidate-qc-seam-projector", sha256: hash("2") },
      { role: "visual-seam-contract", sha256: hash("3") },
    ],
    policySha256: hash("c"),
    policyHash: hash("d"),
  };
}

function visualReceipt(): Record<string, unknown> {
  return {
    schemaVersion: 1,
    kind: "cut-repair-visual-lip-sync-qc",
    status: "bounded-pass",
    protocol: "deterministic-selected-source-av-offset-v1",
    evidenceSemantics:
      "caller-supplied-roi-source-av-temporal-mapping-"
      + "not-face-mouth-or-phoneme-proof",
    preparationHash: hash("4"),
    operationHash,
    candidateCompositeSha256: candidateHash,
    alternateTakeSelectionReceiptHash: selectionReceiptHash,
    candidateSetHash: hash("5"),
    selectionHash: hash("6"),
    selectedCandidateId: "candidate-visible-take-1",
    sourceId: "raw-selected-take",
    sourceMediaSha256: hash("7"),
    sourceFrameRange: frameRange(),
    sourceSampleRange: sampleRange(),
    outputFrameRange: frameRange(),
    outputSampleRange: sampleRange(),
    visualSpeechRegionPpm: {
      x: 300_000, y: 500_000, width: 400_000, height: 300_000,
    },
    ...visualImplementation(),
    sourceVisualTraceSha256: hash("e"),
    candidateVisualTraceSha256: hash("f"),
    sourcePcmSha256: hash("0"),
    candidatePcmSha256: hash("1"),
    visibleUncoveredFrameCount: 30,
    visualDynamicPpm: 50_000,
    visualScorePpm: 990_000,
    visualPeakSeparationPpm: 20_000,
    audioScorePpm: 990_000,
    audioPeakSeparationPpm: 20_000,
    visualMappingOffsetFrames: 0,
    audioMappingOffsetFrames: 0,
    avOffsetFrames: 0,
    maximumMappingOffsetFrames: 1,
    maximumAvOffsetFrames: 1,
    lipSyncDisposition: "passed",
  };
}

function withVisualProof(): Record<string, unknown> {
  const value = promotionEvidence(operationHash, candidateHash);
  const seam = value.seam as Record<string, unknown>;
  const oldReceipt = seam.receipt as Record<string, unknown>;
  const visual = visualReceipt();
  const receipt = {
    ...oldReceipt,
    lipSyncDisposition: "passed",
    alternateTakeSelectionReceiptHash: selectionReceiptHash,
    visualOracleReceiptHash: canonicalJsonSha256(visual),
    visualOracleReceipt: visual,
    sourceFrameRange: visual.sourceFrameRange,
    sourceSampleRange: visual.sourceSampleRange,
    outputFrameRange: visual.outputFrameRange,
    outputSampleRange: visual.outputSampleRange,
  };
  return {
    ...value,
    seam: {
      ...seam,
      receiptHash: canonicalJsonSha256(receipt),
      receipt,
    },
  };
}

const valid = withVisualProof();
assert.doesNotThrow(() => validateCutRepairPromotionEvidence(
  valid, operation, candidateHash));

assert.throws(
  () => validateCutRepairPromotionEvidence(
    promotionEvidence(operationHash, candidateHash), operation, candidateHash),
  /acceptable boundary/,
);

const visualSeam = valid.seam as Record<string, unknown>;
const visualSeamReceipt = visualSeam.receipt as Record<string, unknown>;
const missing = {
  ...visualSeamReceipt,
  visualOracleReceipt: undefined,
};
assert.throws(
  () => validateCutRepairPromotionEvidence({
    ...valid,
    seam: {
      ...visualSeam,
      receipt: missing,
      receiptHash: canonicalJsonSha256(missing),
    },
  }, operation, candidateHash),
  /visual oracle receipt/,
);

const stale = {
  ...(visualSeamReceipt.visualOracleReceipt as Record<string, unknown>),
  candidateVisualTraceSha256: hash("a"),
};
const staleSeam = {
  ...visualSeamReceipt,
  visualOracleReceipt: stale,
};
assert.throws(
  () => validateCutRepairPromotionEvidence({
    ...valid,
    seam: {
      ...visualSeam,
      receipt: staleSeam,
      receiptHash: canonicalJsonSha256(staleSeam),
    },
  }, operation, candidateHash),
  /receipt hash is stale/,
);

console.log("p2-cut-repair-visual-evidence tests passed");
