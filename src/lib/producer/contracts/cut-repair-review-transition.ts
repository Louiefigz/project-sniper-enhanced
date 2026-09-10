import {
  parseCutRestoreSpeechV1,
  type CutRestoreSpeechV1,
} from "./cut-restore-speech-v1";
import {
  exactKeys,
  isoDate,
  objectValue,
  sha256,
  uuid,
} from "./validation";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";

export const CUT_REPAIR_SELECTION_ORDER = [
  "audio-only-before-picture",
  "fewest-picture-dirty-frames",
  "fewest-audio-dirty-frames",
  "shortest-source-extension",
  "operation-hash-tiebreak",
] as const;

export interface CutRepairSelectionPolicyV1 {
  schemaVersion: 1;
  kind: "cut-repair-selection-policy";
  order: string[];
}

export interface CutRepairReviewActionV1 {
  schemaVersion: 1;
  kind: "cut-repair-review-action";
  idempotencyKey: string;
  expectedParentRevisionHash: string;
  operation: CutRestoreSpeechV1;
  operationHash: string;
  selectionPolicy: CutRepairSelectionPolicyV1;
  selectionPolicyHash: string;
  reviewPlanObjectHash: string;
  reviewPlanContentHash: string;
  reviewTimelineMapHash: string;
  reviewRenderGraphHash: string;
  reviewProjectionReceiptHash: string | null;
  workflowPolicy: "cut-first" | "autopilot";
  requestedAt: string;
}

const ACTION_KEYS = [
  "schemaVersion", "kind", "idempotencyKey",
  "expectedParentRevisionHash", "operation", "operationHash",
  "selectionPolicy", "selectionPolicyHash", "reviewPlanObjectHash",
  "reviewPlanContentHash",
  "reviewTimelineMapHash", "reviewRenderGraphHash",
  "reviewProjectionReceiptHash", "workflowPolicy", "requestedAt",
] as const;

export function parseCutRepairSelectionPolicyV1(
  value: unknown,
): CutRepairSelectionPolicyV1 {
  const row = objectValue(value, "CutRepairSelectionPolicyV1");
  exactKeys(
    row,
    ["schemaVersion", "kind", "order"],
    ["schemaVersion", "kind", "order"],
    "CutRepairSelectionPolicyV1",
  );
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-selection-policy"
      || !Array.isArray(row.order)
      || JSON.stringify(row.order) !== JSON.stringify(CUT_REPAIR_SELECTION_ORDER)) {
    throw new Error("cut repair selection policy is unsupported");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-selection-policy",
    order: [...CUT_REPAIR_SELECTION_ORDER],
  };
}

/** Parse the immutable action that creates one CUT_REVIEW child. */
export function parseCutRepairReviewActionV1(
  value: unknown,
): CutRepairReviewActionV1 {
  const row = objectValue(value, "CutRepairReviewActionV1");
  exactKeys(row, ACTION_KEYS, ACTION_KEYS, "CutRepairReviewActionV1");
  if (row.schemaVersion !== 1 || row.kind !== "cut-repair-review-action") {
    throw new Error("CutRepairReviewActionV1 version is unsupported");
  }
  const operation = parseCutRestoreSpeechV1(row.operation);
  const operationHash = sha256(row.operationHash, "review operationHash");
  const policy = parseCutRepairSelectionPolicyV1(row.selectionPolicy);
  const policyHash = sha256(
    row.selectionPolicyHash, "review selectionPolicyHash");
  if (canonicalJsonSha256(operation) !== operationHash
      || canonicalJsonSha256(policy) !== policyHash) {
    throw new Error("cut repair review action contains a stale operation or policy");
  }
  const workflow = row.workflowPolicy;
  if (workflow !== "cut-first" && workflow !== "autopilot") {
    throw new Error("cut repair review workflow policy is unsupported");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-review-action",
    idempotencyKey: uuid(row.idempotencyKey, "review idempotencyKey"),
    expectedParentRevisionHash: sha256(
      row.expectedParentRevisionHash, "review expected parent"),
    operation,
    operationHash,
    selectionPolicy: policy,
    selectionPolicyHash: policyHash,
    reviewPlanObjectHash: sha256(
      row.reviewPlanObjectHash, "review plan object hash"),
    reviewPlanContentHash: sha256(
      row.reviewPlanContentHash, "review plan content hash"),
    reviewTimelineMapHash: sha256(
      row.reviewTimelineMapHash, "review timeline hash"),
    reviewRenderGraphHash: sha256(
      row.reviewRenderGraphHash, "review render graph hash"),
    reviewProjectionReceiptHash: row.reviewProjectionReceiptHash === null
      ? null : sha256(row.reviewProjectionReceiptHash, "review projection hash"),
    workflowPolicy: workflow,
    requestedAt: isoDate(row.requestedAt, "review requestedAt"),
  };
}
