import { canonicalJsonSha256 } from "./auto-edit-hash";
import { parseCutRestoreSpeechV1 } from
  "@/lib/producer/contracts/cut-restore-speech-v1";
import { exactKeys, objectValue, sha256 } from
  "@/lib/producer/contracts/validation";
import {
  validateVisualSeamClosure,
  VISUAL_SEAM_FIELDS,
} from "./producer-cut-repair-visual-evidence";

type Lane = "alignment" | "vad" | "retranscription" | "seam" | "audition";
interface PromotionBinding {
  operationHash: string;
  compositeSha256: string;
  pictureChanged: boolean;
}

const COMMON = [
  "schemaVersion", "kind", "status", "operationHash",
  "candidateCompositeSha256",
] as const;

const SPECS: Record<Lane, {
  status: string;
  kind: string;
  fields: readonly string[];
}> = {
  alignment: {
    status: "bounded-pass",
    kind: "cut-repair-alignment-qc",
    fields: [
      "alignmentProtocol", "evidenceSemantics", "runtimeSha256",
      "implementationSha256", "policySha256", "sourceMediaSha256",
      "candidateWaveSha256", "referenceWaveSha256", "targetWordIds",
      "observedOccurrenceCount", "sourceSpanBoundaryMatch",
      "bestScorePpm", "minimumScorePpm",
      "matchStartSampleInCandidateWindow", "boundaryToleranceSamples",
      "referenceSampleCount",
    ],
  },
  vad: {
    status: "bounded-pass",
    kind: "cut-repair-vad-qc",
    fields: [
      "runtimeSha256", "speechContinuityPassed",
      "unintendedSpeechGapCount",
    ],
  },
  retranscription: {
    status: "bounded-pass",
    kind: "cut-repair-retranscription-qc",
    fields: [
      "runtimeSha256", "modelSha256", "targetPhraseHash",
      "observedOccurrenceCount", "wordOrderPreserved",
    ],
  },
  seam: {
    status: "bounded-pass",
    kind: "cut-repair-seam-qc",
    fields: [
      "runtimeSha256", "clickFree", "duplicateFree",
      "roomToneContinuous", "lipSyncDisposition",
    ],
  },
  audition: {
    status: "operator-approved-candidate",
    kind: "cut-repair-audition-qc",
    fields: [
      "operatorReceiptId", "approvalPolicyHash", "reviewedAt",
      "decision", "reportedDamageResolved",
    ],
  },
};

function assertStringArray(value: unknown, label: string): void {
  if (!Array.isArray(value) || !value.length
      || value.some((row) => typeof row !== "string" || !row)
      || new Set(value).size !== value.length) {
    throw new Error(`${label} must contain unique non-empty strings`);
  }
}

function nonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function assertAlignmentReceipt(receipt: Record<string, unknown>): void {
  [
    "runtimeSha256", "implementationSha256", "policySha256",
    "sourceMediaSha256", "candidateWaveSha256", "referenceWaveSha256",
  ].forEach((key) => sha256(receipt[key], `alignment receipt ${key}`));
  assertStringArray(receipt.targetWordIds, "alignment targetWordIds");
  const integers = [
    receipt.bestScorePpm, receipt.minimumScorePpm,
    receipt.matchStartSampleInCandidateWindow,
    receipt.boundaryToleranceSamples, receipt.referenceSampleCount,
  ];
  if (receipt.alignmentProtocol !== "deterministic-source-waveform-v1"
      || receipt.evidenceSemantics
        !== "transcript-bound-source-waveform-presence-not-audibility"
      || integers.some((value) => !nonNegativeInteger(value))
      || receipt.minimumScorePpm !== 850_000
      || Number(receipt.bestScorePpm) < 850_000
      || Number(receipt.bestScorePpm) > 1_000_000
      || receipt.boundaryToleranceSamples !== 240
      || Number(receipt.referenceSampleCount) <= 0
      || receipt.observedOccurrenceCount !== 1
      || receipt.sourceSpanBoundaryMatch !== true) {
    throw new Error(
      "alignment receipt did not prove one transcript-bound source waveform",
    );
  }
}

function assertLaneFields(
  lane: Lane,
  receipt: Record<string, unknown>,
  pictureChanged: boolean,
): void {
  if (lane === "alignment") {
    assertAlignmentReceipt(receipt);
  } else if (lane === "vad") {
    sha256(receipt.runtimeSha256, "vad receipt runtimeSha256");
    if (receipt.speechContinuityPassed !== true
        || receipt.unintendedSpeechGapCount !== 0) {
      throw new Error("VAD receipt did not prove continuous intended speech");
    }
  } else if (lane === "retranscription") {
    sha256(receipt.runtimeSha256, "retranscription receipt runtimeSha256");
    sha256(receipt.modelSha256, "retranscription receipt modelSha256");
    sha256(receipt.targetPhraseHash, "retranscription targetPhraseHash");
    if (receipt.observedOccurrenceCount !== 1
        || receipt.wordOrderPreserved !== true) {
      throw new Error("retranscription receipt did not prove the target phrase");
    }
  } else if (lane === "seam") {
    sha256(receipt.runtimeSha256, "seam receipt runtimeSha256");
    const requiredLipSync = pictureChanged
      ? "passed" : "not-applicable-audio-only";
    if (receipt.clickFree !== true || receipt.duplicateFree !== true
        || receipt.roomToneContinuous !== true
        || receipt.lipSyncDisposition !== requiredLipSync) {
      throw new Error("seam receipt did not prove an acceptable boundary");
    }
    if (pictureChanged) {
      validateVisualSeamClosure(
        receipt,
        String(receipt.operationHash),
        String(receipt.candidateCompositeSha256),
      );
    }
  } else {
    sha256(receipt.approvalPolicyHash, "audition approvalPolicyHash");
    const timestamp = typeof receipt.reviewedAt === "string"
      ? Date.parse(receipt.reviewedAt) : Number.NaN;
    if (typeof receipt.operatorReceiptId !== "string"
        || !receipt.operatorReceiptId || !Number.isFinite(timestamp)
        || receipt.decision !== "approved"
        || receipt.reportedDamageResolved !== true) {
      throw new Error("audition receipt lacks explicit candidate approval");
    }
  }
}

function validateLane(
  lane: Lane,
  value: unknown,
  binding: PromotionBinding,
): void {
  const item = objectValue(value, `promotion evidence ${lane}`);
  exactKeys(
    item,
    ["status", "receiptHash", "candidateCompositeSha256", "receipt"],
    ["status", "receiptHash", "candidateCompositeSha256", "receipt"],
    `promotion evidence ${lane}`,
  );
  const spec = SPECS[lane];
  const receipt = objectValue(item.receipt, `${lane} receipt`);
  const fields = lane === "seam" && receipt.lipSyncDisposition === "passed"
    ? [...spec.fields, ...VISUAL_SEAM_FIELDS] : spec.fields;
  exactKeys(
    receipt, [...COMMON, ...fields], [...COMMON, ...fields],
    `${lane} receipt`,
  );
  if (item.status !== spec.status || receipt.status !== spec.status
      || receipt.schemaVersion !== 1 || receipt.kind !== spec.kind
      || receipt.operationHash !== binding.operationHash
      || item.candidateCompositeSha256 !== binding.compositeSha256
      || receipt.candidateCompositeSha256 !== binding.compositeSha256
      || item.receiptHash !== canonicalJsonSha256(receipt)) {
    throw new Error(`cut repair ${lane} receipt is stale or substituted`);
  }
  assertLaneFields(lane, receipt, binding.pictureChanged);
}

/** Validate full QC receipts and compute their enclosing evidence hash. */
export function validateCutRepairPromotionEvidence(
  value: unknown,
  operationValue: unknown,
  compositeSha256: string,
): string {
  const operation = parseCutRestoreSpeechV1(operationValue);
  const binding = {
    operationHash: canonicalJsonSha256(operation),
    compositeSha256,
    pictureChanged: operation.pictureDirtyWindows.length > 0,
  };
  const row = objectValue(value, "cut repair promotion evidence");
  const lanes: Lane[] = [
    "alignment", "vad", "retranscription", "seam", "audition",
  ];
  const keys = [
    "schemaVersion", "kind", "operationHash",
    "candidateCompositeSha256", ...lanes,
  ];
  exactKeys(row, keys, keys, "cut repair promotion evidence");
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-promotion-evidence"
      || row.operationHash !== binding.operationHash
      || row.candidateCompositeSha256 !== compositeSha256) {
    throw new Error("cut repair promotion evidence is stale");
  }
  lanes.forEach((lane) => validateLane(lane, row[lane], binding));
  return canonicalJsonSha256(row);
}
