import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  exactKeys,
  objectValue,
  sha256,
  stableId,
} from "@/lib/producer/contracts/validation";

export const VISUAL_SEAM_FIELDS = [
  "alternateTakeSelectionReceiptHash",
  "visualOracleReceiptHash",
  "visualOracleReceipt",
  "sourceFrameRange",
  "sourceSampleRange",
  "outputFrameRange",
  "outputSampleRange",
] as const;

const VISUAL_FIELDS = [
  "schemaVersion", "kind", "status", "protocol", "evidenceSemantics",
  "preparationHash", "operationHash", "candidateCompositeSha256",
  "alternateTakeSelectionReceiptHash", "candidateSetHash", "selectionHash",
  "selectedCandidateId", "sourceId", "sourceMediaSha256",
  "sourceFrameRange", "sourceSampleRange", "outputFrameRange",
  "outputSampleRange", "visualSpeechRegionPpm", "toolManifestHash",
  "ffmpegSha256", "runtimeSha256", "implementationSha256", "policySha256",
  "implementationScope", "implementationNonClaims",
  "implementationClosureHash", "implementationFileHashes",
  "policyHash", "sourceVisualTraceSha256", "candidateVisualTraceSha256",
  "sourcePcmSha256", "candidatePcmSha256", "visibleUncoveredFrameCount",
  "visualDynamicPpm", "visualScorePpm", "visualPeakSeparationPpm",
  "audioScorePpm", "audioPeakSeparationPpm", "visualMappingOffsetFrames",
  "audioMappingOffsetFrames", "avOffsetFrames",
  "maximumMappingOffsetFrames", "maximumAvOffsetFrames",
  "lipSyncDisposition",
] as const;

function integer(value: unknown, minimum: number, label: string): number {
  if (!Number.isInteger(value) || Number(value) < minimum) {
    throw new Error(`${label} must be an integer >= ${minimum}`);
  }
  return Number(value);
}

function frameRange(value: unknown, label: string): Record<string, unknown> {
  const row = objectValue(value, label);
  const keys = [
    "firstFrame", "endFrameExclusive", "fpsNumerator", "fpsDenominator",
  ];
  exactKeys(row, keys, keys, label);
  const first = integer(row.firstFrame, 0, `${label}.firstFrame`);
  const end = integer(row.endFrameExclusive, 1, `${label}.endFrameExclusive`);
  integer(row.fpsNumerator, 1, `${label}.fpsNumerator`);
  integer(row.fpsDenominator, 1, `${label}.fpsDenominator`);
  if (end <= first) throw new Error(`${label} must be non-empty`);
  return row;
}

function sampleRange(value: unknown, label: string): Record<string, unknown> {
  const row = objectValue(value, label);
  const keys = ["startSample", "endSampleExclusive", "sampleRate"];
  exactKeys(row, keys, keys, label);
  const start = integer(row.startSample, 0, `${label}.startSample`);
  const end = integer(row.endSampleExclusive, 1, `${label}.endSampleExclusive`);
  integer(row.sampleRate, 1, `${label}.sampleRate`);
  if (end <= start) throw new Error(`${label} must be non-empty`);
  return row;
}

function region(value: unknown): void {
  const row = objectValue(value, "visualSpeechRegionPpm");
  const keys = ["x", "y", "width", "height"];
  exactKeys(row, keys, keys, "visualSpeechRegionPpm");
  const x = integer(row.x, 0, "visualSpeechRegionPpm.x");
  const y = integer(row.y, 0, "visualSpeechRegionPpm.y");
  const width = integer(row.width, 1, "visualSpeechRegionPpm.width");
  const height = integer(row.height, 1, "visualSpeechRegionPpm.height");
  if (x + width > 1_000_000 || y + height > 1_000_000) {
    throw new Error("visualSpeechRegionPpm escapes the source frame");
  }
}

function hashes(receipt: Record<string, unknown>): void {
  [
    "preparationHash", "operationHash", "candidateCompositeSha256",
    "alternateTakeSelectionReceiptHash", "candidateSetHash", "selectionHash",
    "sourceMediaSha256", "toolManifestHash", "ffmpegSha256", "runtimeSha256",
    "implementationSha256", "implementationClosureHash",
    "policySha256", "policyHash",
    "sourceVisualTraceSha256", "candidateVisualTraceSha256",
    "sourcePcmSha256", "candidatePcmSha256",
  ].forEach((key) => sha256(receipt[key], `visual receipt ${key}`));
}

function implementationFiles(value: unknown): void {
  const roles = [
    "controller", "media-decoder", "receipt-projector",
    "visual-value-types", "authority-hashing",
    "candidate-qc-value-types", "candidate-qc-visual-adapter",
    "candidate-qc-seam-projector", "visual-seam-contract",
  ];
  if (!Array.isArray(value) || value.length !== roles.length) {
    throw new Error("visual implementationFileHashes is incomplete");
  }
  value.forEach((item, index) => {
    const row = objectValue(item, `implementationFileHashes[${index}]`);
    const keys = ["role", "sha256"];
    exactKeys(row, keys, keys, `implementationFileHashes[${index}]`);
    if (row.role !== roles[index]) {
      throw new Error("visual implementation file role is stale");
    }
    sha256(row.sha256, `visual ${roles[index]} implementation`);
  });
}

function measurements(receipt: Record<string, unknown>): void {
  [
    "visibleUncoveredFrameCount", "visualDynamicPpm",
    "visualPeakSeparationPpm", "audioPeakSeparationPpm",
  ].forEach((key) => integer(receipt[key], 1, `visual receipt ${key}`));
  ["visualScorePpm", "audioScorePpm"].forEach((key) => {
    const value = integer(receipt[key], 0, `visual receipt ${key}`);
    if (value > 1_000_000) throw new Error(`${key} exceeds one million PPM`);
  });
  const visual = integer(
    receipt.visualMappingOffsetFrames, -Number.MAX_SAFE_INTEGER,
    "visualMappingOffsetFrames");
  const audio = integer(
    receipt.audioMappingOffsetFrames, -Number.MAX_SAFE_INTEGER,
    "audioMappingOffsetFrames");
  const offset = integer(
    receipt.avOffsetFrames, -Number.MAX_SAFE_INTEGER, "avOffsetFrames");
  const mapping = integer(
    receipt.maximumMappingOffsetFrames, 1, "maximumMappingOffsetFrames");
  const tolerance = integer(
    receipt.maximumAvOffsetFrames, 1, "maximumAvOffsetFrames");
  const released = Number(receipt.visibleUncoveredFrameCount) >= 12
    && Number(receipt.visualDynamicPpm) >= 6_000
    && Number(receipt.visualScorePpm) >= 940_000
    && Number(receipt.audioScorePpm) >= 940_000
    && Number(receipt.visualPeakSeparationPpm) >= 2_500
    && Number(receipt.audioPeakSeparationPpm) >= 2_500
    && mapping === 1 && tolerance === 1;
  if (!released || Math.abs(visual) > mapping || Math.abs(audio) > mapping
      || Math.abs(offset) > tolerance) {
    throw new Error("visual receipt does not prove released thresholds");
  }
}

function visualReceipt(
  value: unknown,
  operationHash: string,
  compositeSha256: string,
  selectionReceiptHash: string,
): Record<string, unknown> {
  const receipt = objectValue(value, "visual oracle receipt");
  exactKeys(receipt, VISUAL_FIELDS, VISUAL_FIELDS, "visual oracle receipt");
  if (receipt.schemaVersion !== 1
      || receipt.kind !== "cut-repair-visual-lip-sync-qc"
      || receipt.status !== "bounded-pass"
      || receipt.protocol !== "deterministic-selected-source-av-offset-v1"
      || receipt.evidenceSemantics
        !== "caller-supplied-roi-source-av-temporal-mapping-"
          + "not-face-mouth-or-phoneme-proof"
      || receipt.operationHash !== operationHash
      || receipt.candidateCompositeSha256 !== compositeSha256
      || receipt.alternateTakeSelectionReceiptHash !== selectionReceiptHash
      || receipt.lipSyncDisposition !== "passed") {
    throw new Error("visual oracle receipt is stale or substituted");
  }
  hashes(receipt);
  if (receipt.implementationScope
        !== "visual-choice-seam-repository-code-v1"
      || canonicalJsonSha256(receipt.implementationNonClaims)
        !== canonicalJsonSha256([
          "audio-seam-measurement",
          "candidate-qc-orchestration-storage-or-promotion",
          "python-stdlib-os-dylibs",
        ])) {
    throw new Error("visual implementation scope or nonclaims are stale");
  }
  implementationFiles(receipt.implementationFileHashes);
  stableId(receipt.selectedCandidateId, "visual selectedCandidateId");
  stableId(receipt.sourceId, "visual sourceId");
  frameRange(receipt.sourceFrameRange, "visual sourceFrameRange");
  frameRange(receipt.outputFrameRange, "visual outputFrameRange");
  sampleRange(receipt.sourceSampleRange, "visual sourceSampleRange");
  sampleRange(receipt.outputSampleRange, "visual outputSampleRange");
  region(receipt.visualSpeechRegionPpm);
  measurements(receipt);
  return receipt;
}

/** Require a passed seam to close over one exact governed visual proof. */
export function validateVisualSeamClosure(
  seam: Record<string, unknown>,
  operationHash: string,
  compositeSha256: string,
): void {
  const selectionHash = sha256(
    seam.alternateTakeSelectionReceiptHash,
    "seam alternateTakeSelectionReceiptHash");
  const visualHash = sha256(
    seam.visualOracleReceiptHash, "seam visualOracleReceiptHash");
  const receipt = visualReceipt(
    seam.visualOracleReceipt, operationHash, compositeSha256, selectionHash);
  if (canonicalJsonSha256(receipt) !== visualHash) {
    throw new Error("embedded visual oracle receipt hash is stale");
  }
  [
    "sourceFrameRange", "sourceSampleRange",
    "outputFrameRange", "outputSampleRange",
  ].forEach((key) => {
    if (canonicalJsonSha256(seam[key])
        !== canonicalJsonSha256(receipt[key])) {
      throw new Error(`seam ${key} does not close over visual evidence`);
    }
  });
}
