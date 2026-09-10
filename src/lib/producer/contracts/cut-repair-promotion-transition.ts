import {
  exactKeys,
  isoDate,
  objectValue,
  sha256,
  uuid,
} from "./validation";

export interface CutRepairSelectedApprovalV1 {
  approver: "operator" | "system-policy";
  approvalPolicyHash: string;
  approvalReceiptHash: string;
}

export interface CutRepairPromotionActionV1 {
  schemaVersion: 1;
  kind: "cut-repair-promotion-action";
  idempotencyKey: string;
  expectedReviewRevisionHash: string;
  reviewActionHash: string;
  operationHash: string;
  selectionPolicyHash: string;
  selectedApproval: CutRepairSelectedApprovalV1;
  childPictureLockHash: string;
  candidateHash: string;
  promotionEvidenceHash: string;
  requestedAt: string;
}

const ACTION_KEYS = [
  "schemaVersion", "kind", "idempotencyKey",
  "expectedReviewRevisionHash", "reviewActionHash", "operationHash",
  "selectionPolicyHash", "selectedApproval", "childPictureLockHash",
  "candidateHash", "promotionEvidenceHash", "requestedAt",
] as const;

export function parseCutRepairSelectedApprovalV1(
  value: unknown,
): CutRepairSelectedApprovalV1 {
  const row = objectValue(value, "cut repair selected approval");
  const keys = [
    "approver", "approvalPolicyHash", "approvalReceiptHash",
  ] as const;
  exactKeys(row, keys, keys, "cut repair selected approval");
  if (row.approver !== "operator" && row.approver !== "system-policy") {
    throw new Error("cut repair selected approver is unsupported");
  }
  return {
    approver: row.approver,
    approvalPolicyHash: sha256(
      row.approvalPolicyHash, "selected approval policy hash"),
    approvalReceiptHash: sha256(
      row.approvalReceiptHash, "selected approval receipt hash"),
  };
}

/** Parse the separate lifecycle action that locks an approved review child. */
export function parseCutRepairPromotionActionV1(
  value: unknown,
): CutRepairPromotionActionV1 {
  const row = objectValue(value, "CutRepairPromotionActionV1");
  exactKeys(row, ACTION_KEYS, ACTION_KEYS, "CutRepairPromotionActionV1");
  if (row.schemaVersion !== 1 || row.kind !== "cut-repair-promotion-action") {
    throw new Error("CutRepairPromotionActionV1 version is unsupported");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-promotion-action",
    idempotencyKey: uuid(row.idempotencyKey, "promotion idempotencyKey"),
    expectedReviewRevisionHash: sha256(
      row.expectedReviewRevisionHash, "expected review revision"),
    reviewActionHash: sha256(row.reviewActionHash, "review action hash"),
    operationHash: sha256(row.operationHash, "promotion operation hash"),
    selectionPolicyHash: sha256(
      row.selectionPolicyHash, "promotion selection policy hash"),
    selectedApproval: parseCutRepairSelectedApprovalV1(row.selectedApproval),
    childPictureLockHash: sha256(
      row.childPictureLockHash, "promotion child lock hash"),
    candidateHash: sha256(row.candidateHash, "promotion candidate hash"),
    promotionEvidenceHash: sha256(
      row.promotionEvidenceHash, "promotion evidence hash"),
    requestedAt: isoDate(row.requestedAt, "promotion requestedAt"),
  };
}
