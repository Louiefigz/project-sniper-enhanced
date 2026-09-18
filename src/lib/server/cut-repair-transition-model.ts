import {
  exactKeys,
  hashRecord,
  isoDate,
  objectValue,
  sha256,
  uuid,
} from "@/lib/producer/contracts/validation";

export type CutRepairTransitionKind =
  | "ripple-reopen"
  | "review"
  | "promotion";
export type CutRepairTransitionBoundary =
  | "after-materialized"
  | "after-receipt-proved"
  | "after-local-commit-intent"
  | "after-advance"
  | "after-head"
  | "after-committed";

export interface CutRepairTransitionHooks {
  after?: (boundary: CutRepairTransitionBoundary) => void;
}

export interface CutRepairTransitionRecord {
  schemaVersion: 1;
  kind: "cut-repair-transition-record";
  transition: CutRepairTransitionKind;
  idempotencyKey: string;
  actionHash: string;
  expectedParentRevisionHash: string;
  childRevisionHash: string;
  originalPictureLockedParentHash: string;
  receiptHash: string;
  artifactHashes: Record<string, string>;
  recordedAt: string;
}

export interface CutRepairTransitionOutcome {
  status: "committed" | "replayed" | "aborted" | "reconciliation-required";
  childRevisionHash: string;
  receiptHash: string | null;
}

export interface RecoverCutRepairTransitionInput {
  producerDir: string;
  transition: CutRepairTransitionKind;
  idempotencyKey: string;
  verify: (record: CutRepairTransitionRecord) => void;
}

const RECORD_KEYS = [
  "schemaVersion", "kind", "transition", "idempotencyKey", "actionHash",
  "expectedParentRevisionHash", "childRevisionHash",
  "originalPictureLockedParentHash", "receiptHash", "artifactHashes",
  "recordedAt",
] as const;

export function parseCutRepairTransitionRecord(
  value: unknown,
): CutRepairTransitionRecord {
  const row = objectValue(value, "cut repair transition record");
  exactKeys(row, RECORD_KEYS, RECORD_KEYS, "cut repair transition record");
  const transition = row.transition;
  if (row.schemaVersion !== 1 || row.kind !== "cut-repair-transition-record"
      || (transition !== "ripple-reopen"
        && transition !== "review"
        && transition !== "promotion")) {
    throw new Error("cut repair transition record type is unsupported");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-transition-record",
    transition,
    idempotencyKey: uuid(row.idempotencyKey, "transition idempotency key"),
    actionHash: sha256(row.actionHash, "transition action hash"),
    expectedParentRevisionHash: sha256(
      row.expectedParentRevisionHash, "transition expected parent"),
    childRevisionHash: sha256(
      row.childRevisionHash, "transition child revision"),
    originalPictureLockedParentHash: sha256(
      row.originalPictureLockedParentHash, "transition original parent"),
    receiptHash: sha256(row.receiptHash, "transition receipt hash"),
    artifactHashes: hashRecord(row.artifactHashes, "transition artifacts"),
    recordedAt: isoDate(row.recordedAt, "transition recordedAt"),
  };
}
