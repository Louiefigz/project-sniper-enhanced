import type { EditBatchV1 } from "./edit-batch";
import {
  TREATMENT_OPERATION_NAMES,
  type TreatmentOperationNameV1,
} from "./treatment-operation";
import type { InvalidationReceiptV1 } from "./render-graph";
import {
  enumValue,
  exactKeys,
  isoDate,
  objectValue,
  sha256,
  stringValue,
  uniqueStrings,
  uuid,
} from "./validation";

export const EDIT_RECEIPT_STATUSES = [
  "candidate-proved",
  "committed",
  "not-promoted",
  "reconciliation-required",
] as const;

export type EditReceiptStatusV1 = typeof EDIT_RECEIPT_STATUSES[number];

export interface EditOperationReceiptV1 {
  operationId: string;
  clauseId: string;
  operation:
    | "SetGraphicTextV1"
    | "cut.restoreSpeech"
    | TreatmentOperationNameV1;
  executionState: "candidate-executed" | "committed";
  beforeHash: string;
  afterHash: string;
  dirtyNodeIds: string[];
  explanation: string;
}

export interface EditReceiptV1 {
  schemaVersion: 1;
  receiptId: string;
  requestId: string;
  batchId: string;
  idempotencyKey: string;
  parentRevisionHash: string;
  childRevisionHash: string;
  status: EditReceiptStatusV1;
  recordedAt: string;
  operations: EditOperationReceiptV1[];
  dirtyWindows: Array<{ startFrame: number; endFrameExclusive: number }>;
  invariantProofHash: string;
}

const RECEIPT_KEYS = [
  "schemaVersion", "receiptId", "requestId", "batchId", "idempotencyKey",
  "parentRevisionHash", "childRevisionHash", "status", "recordedAt",
  "operations", "dirtyWindows", "invariantProofHash",
] as const;
const OPERATION_KEYS = [
  "operationId", "clauseId", "operation", "executionState", "beforeHash",
  "afterHash", "dirtyNodeIds", "explanation",
] as const;

function parseOperation(value: unknown): EditOperationReceiptV1 {
  const row = objectValue(value, "EditOperationReceiptV1");
  exactKeys(row, OPERATION_KEYS, OPERATION_KEYS, "EditOperationReceiptV1");
  if (![
    "SetGraphicTextV1",
    "cut.restoreSpeech",
    ...TREATMENT_OPERATION_NAMES,
  ].includes(row.operation as never)) {
    throw new Error("EditOperationReceiptV1 operation is unsupported");
  }
  return {
    operationId: uuid(row.operationId, "operation receipt operationId"),
    clauseId: uuid(row.clauseId, "operation receipt clauseId"),
    operation: row.operation as EditOperationReceiptV1["operation"],
    executionState: enumValue(
      row.executionState,
      ["candidate-executed", "committed"] as const,
      "operation receipt executionState",
    ),
    beforeHash: sha256(row.beforeHash, "operation receipt beforeHash"),
    afterHash: sha256(row.afterHash, "operation receipt afterHash"),
    dirtyNodeIds: uniqueStrings(row.dirtyNodeIds, "operation receipt dirtyNodeIds"),
    explanation: stringValue(row.explanation, "operation receipt explanation", 2_000),
  };
}

function parseWindows(value: unknown): EditReceiptV1["dirtyWindows"] {
  if (!Array.isArray(value)) throw new Error("EditReceiptV1.dirtyWindows must be an array");
  return value.map((item, index) => {
    const row = objectValue(item, `dirtyWindows[${index}]`);
    exactKeys(
      row,
      ["startFrame", "endFrameExclusive"],
      ["startFrame", "endFrameExclusive"],
      `dirtyWindows[${index}]`,
    );
    if (!Number.isSafeInteger(row.startFrame)
        || !Number.isSafeInteger(row.endFrameExclusive)
        || Number(row.startFrame) < 0
        || Number(row.endFrameExclusive) <= Number(row.startFrame)) {
      throw new Error(`dirtyWindows[${index}] is invalid`);
    }
    return {
      startFrame: Number(row.startFrame),
      endFrameExclusive: Number(row.endFrameExclusive),
    };
  });
}

export function parseEditReceiptV1(value: unknown): EditReceiptV1 {
  const receipt = objectValue(value, "EditReceiptV1");
  exactKeys(receipt, RECEIPT_KEYS, RECEIPT_KEYS, "EditReceiptV1");
  if (receipt.schemaVersion !== 1 || !Array.isArray(receipt.operations)
      || receipt.operations.length === 0) {
    throw new Error("EditReceiptV1 version or operations are invalid");
  }
  const operations = receipt.operations.map(parseOperation);
  if (new Set(operations.map((row) => row.operationId)).size !== operations.length) {
    throw new Error("EditReceiptV1 operation ids must be unique");
  }
  const parsed: EditReceiptV1 = {
    schemaVersion: 1,
    receiptId: uuid(receipt.receiptId, "EditReceiptV1.receiptId"),
    requestId: uuid(receipt.requestId, "EditReceiptV1.requestId"),
    batchId: uuid(receipt.batchId, "EditReceiptV1.batchId"),
    idempotencyKey: uuid(receipt.idempotencyKey, "EditReceiptV1.idempotencyKey"),
    parentRevisionHash: sha256(receipt.parentRevisionHash, "parentRevisionHash"),
    childRevisionHash: sha256(receipt.childRevisionHash, "childRevisionHash"),
    status: enumValue(receipt.status, EDIT_RECEIPT_STATUSES, "EditReceiptV1.status"),
    recordedAt: isoDate(receipt.recordedAt, "EditReceiptV1.recordedAt"),
    operations,
    dirtyWindows: parseWindows(receipt.dirtyWindows),
    invariantProofHash: sha256(receipt.invariantProofHash, "invariantProofHash"),
  };
  const states = new Set(parsed.operations.map((operation) => operation.executionState));
  if ((parsed.status === "committed" && (
    states.size !== 1 || !states.has("committed")
  )) || (parsed.status === "candidate-proved" && (
    states.size !== 1 || !states.has("candidate-executed")
  ))) {
    throw new Error("EditReceiptV1 status and operation execution states disagree");
  }
  return parsed;
}

interface BuildReceiptOptions {
  batch: EditBatchV1;
  childRevisionHash: string;
  afterPlanHash: string;
  receiptId: string;
  recordedAt: string;
  invalidation: InvalidationReceiptV1;
  invariantProofHash: string;
  committed: boolean;
}

export function buildEditReceiptV1(options: BuildReceiptOptions): EditReceiptV1 {
  const state = options.committed ? "committed" as const : "candidate-executed" as const;
  return parseEditReceiptV1({
    schemaVersion: 1,
    receiptId: options.receiptId,
    requestId: options.batch.requestId,
    batchId: options.batch.batchId,
    idempotencyKey: options.batch.idempotencyKey,
    parentRevisionHash: options.batch.base.projectRevisionHash,
    childRevisionHash: options.childRevisionHash,
    status: options.committed ? "committed" : "candidate-proved",
    recordedAt: options.recordedAt,
    operations: options.batch.operations.map((operation) => ({
      operationId: operation.operationId,
      clauseId: operation.clauseId,
      operation: operation.action.operation,
      executionState: state,
      beforeHash: options.batch.base.planContentHash,
      afterHash: options.afterPlanHash,
      dirtyNodeIds: options.invalidation.dirtyNodeIds,
      explanation: options.committed
        ? "deterministic operation committed with the bound revision"
        : "deterministic operation executed in the private candidate",
    })),
    dirtyWindows: options.invalidation.dirtyWindows,
    invariantProofHash: options.invariantProofHash,
  });
}
