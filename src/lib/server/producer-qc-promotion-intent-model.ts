import {
  enumValue,
  exactKeys,
  objectValue,
  sha256,
} from "@/lib/producer/contracts/validation";

export type QcPromotionIntentPhase = "prepared" | "child-materialized";

export interface QcPromotionOldStateV1 {
  finalMediaFileHash: string | null;
  finalProofFileHash: string | null;
  approvalFileHash: string | null;
  previewMarkerFileHash: string | null;
  activeGraphPointerFileHash: string | null;
}

export interface ProducerQcPromotionIntentV1 {
  schemaVersion: 1;
  kind: "producer-qc-promotion";
  intentId: string;
  phase: QcPromotionIntentPhase;
  parentRevisionHash: string;
  expectedApprovedHead: string | null;
  intendedGraphHash: string;
  intendedApprovalHash: string;
  intendedFinalHash: string;
  intendedPlanHash: string;
  intendedManifestHash: string;
  oldState: QcPromotionOldStateV1;
  childRevisionHash: string | null;
  graphReceiptHash: string | null;
  graphPointerHash: string | null;
}

const INTENT_KEYS = [
  "schemaVersion", "kind", "intentId", "phase", "parentRevisionHash",
  "expectedApprovedHead", "intendedGraphHash", "intendedApprovalHash",
  "intendedFinalHash", "intendedPlanHash", "intendedManifestHash",
  "oldState", "childRevisionHash", "graphReceiptHash", "graphPointerHash",
] as const;
const OLD_KEYS = [
  "finalMediaFileHash", "finalProofFileHash", "approvalFileHash",
  "previewMarkerFileHash", "activeGraphPointerFileHash",
] as const;

function nullableHash(value: unknown, label: string): string | null {
  return value === null ? null : sha256(value, label);
}

function oldState(value: unknown): QcPromotionOldStateV1 {
  const state = objectValue(value, "QC promotion old state");
  exactKeys(state, OLD_KEYS, OLD_KEYS, "QC promotion old state");
  return {
    finalMediaFileHash: nullableHash(
      state.finalMediaFileHash, "old final media hash"),
    finalProofFileHash: nullableHash(
      state.finalProofFileHash, "old final proof hash"),
    approvalFileHash: nullableHash(
      state.approvalFileHash, "old approval file hash"),
    previewMarkerFileHash: nullableHash(
      state.previewMarkerFileHash, "old preview marker hash"),
    activeGraphPointerFileHash: nullableHash(
      state.activeGraphPointerFileHash, "old active graph pointer hash"),
  };
}

export function parseProducerQcPromotionIntentV1(
  value: unknown,
): ProducerQcPromotionIntentV1 {
  const intent = objectValue(value, "ProducerQcPromotionIntentV1");
  exactKeys(
    intent, INTENT_KEYS, INTENT_KEYS, "ProducerQcPromotionIntentV1");
  if (intent.schemaVersion !== 1
      || intent.kind !== "producer-qc-promotion") {
    throw new Error("ProducerQcPromotionIntentV1 version is unsupported");
  }
  return {
    schemaVersion: 1,
    kind: "producer-qc-promotion",
    intentId: sha256(intent.intentId, "QC promotion intentId"),
    phase: enumValue(
      intent.phase,
      ["prepared", "child-materialized"] as const,
      "QC promotion phase",
    ),
    parentRevisionHash: sha256(
      intent.parentRevisionHash, "QC promotion parent"),
    expectedApprovedHead: nullableHash(
      intent.expectedApprovedHead, "expected approved head"),
    intendedGraphHash: sha256(
      intent.intendedGraphHash, "intended graph hash"),
    intendedApprovalHash: sha256(
      intent.intendedApprovalHash, "intended approval hash"),
    intendedFinalHash: sha256(
      intent.intendedFinalHash, "intended final hash"),
    intendedPlanHash: sha256(
      intent.intendedPlanHash, "intended plan hash"),
    intendedManifestHash: sha256(
      intent.intendedManifestHash, "intended manifest hash"),
    oldState: oldState(intent.oldState),
    childRevisionHash: nullableHash(
      intent.childRevisionHash, "QC child revision hash"),
    graphReceiptHash: nullableHash(
      intent.graphReceiptHash, "QC graph receipt hash"),
    graphPointerHash: nullableHash(
      intent.graphPointerHash, "QC graph pointer hash"),
  };
}
