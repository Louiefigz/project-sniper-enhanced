import {
  exactKeys,
  isoDate,
  objectValue,
  sha256,
  uuid,
} from "./validation";

export type CutRepairTransitionStatusV1 =
  | "CUT_REVIEW_COMMITTED"
  | "PICTURE_LOCKED_COMMITTED";

export interface CutRepairTransitionReceiptV1 {
  schemaVersion: 1;
  kind: "cut-repair-transition-receipt";
  status: CutRepairTransitionStatusV1;
  idempotencyKey: string;
  actionHash: string;
  expectedParentRevisionHash: string;
  childRevisionHash: string;
  originalPictureLockedParentHash: string;
  operationHash: string;
  selectionPolicyHash: string;
  childPictureLockHash: string | null;
  recordedAt: string;
}

const KEYS = [
  "schemaVersion", "kind", "status", "idempotencyKey", "actionHash",
  "expectedParentRevisionHash", "childRevisionHash",
  "originalPictureLockedParentHash", "operationHash", "selectionPolicyHash",
  "childPictureLockHash", "recordedAt",
] as const;

/** Parse either phase receipt while keeping its lifecycle state explicit. */
export function parseCutRepairTransitionReceiptV1(
  value: unknown,
): CutRepairTransitionReceiptV1 {
  const row = objectValue(value, "CutRepairTransitionReceiptV1");
  exactKeys(row, KEYS, KEYS, "CutRepairTransitionReceiptV1");
  const status = row.status;
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-transition-receipt"
      || (status !== "CUT_REVIEW_COMMITTED"
        && status !== "PICTURE_LOCKED_COMMITTED")) {
    throw new Error("cut repair transition receipt type is unsupported");
  }
  const childLock = row.childPictureLockHash === null
    ? null : sha256(row.childPictureLockHash, "receipt child lock");
  if ((status === "CUT_REVIEW_COMMITTED") !== (childLock === null)) {
    throw new Error("cut repair transition receipt has the wrong lock state");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-transition-receipt",
    status,
    idempotencyKey: uuid(row.idempotencyKey, "receipt idempotencyKey"),
    actionHash: sha256(row.actionHash, "receipt action hash"),
    expectedParentRevisionHash: sha256(
      row.expectedParentRevisionHash, "receipt expected parent"),
    childRevisionHash: sha256(row.childRevisionHash, "receipt child revision"),
    originalPictureLockedParentHash: sha256(
      row.originalPictureLockedParentHash, "receipt original parent"),
    operationHash: sha256(row.operationHash, "receipt operation hash"),
    selectionPolicyHash: sha256(
      row.selectionPolicyHash, "receipt selection policy hash"),
    childPictureLockHash: childLock,
    recordedAt: isoDate(row.recordedAt, "receipt recordedAt"),
  };
}
