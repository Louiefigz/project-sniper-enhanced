import {
  parseSetGraphicTextV1,
  type SetGraphicTextV1,
} from "../set-graphic-text-v1";
import {
  parseCutRestoreSpeechV1,
  type CutRestoreSpeechV1,
} from "./cut-restore-speech-v1";
import {
  parseTreatmentOperationV1,
  type TreatmentOperationV1,
} from "./treatment-operation";
import type { EditRequestV1 } from "./edit-request";
import {
  exactKeys,
  objectValue,
  sha256,
  uniqueStrings,
  uuid,
} from "./validation";

export interface EditBatchBaseRevisionV1 {
  projectRevisionHash: string;
  planContentHash: string;
  manifestHash: string;
  sourceSnapshotSetHash: string;
  timelineMapHash: string;
  canvasProfileHash: string;
  destinationProfileHashes: string[];
  pictureLockHash: string;
}

export interface TypedOperationEnvelopeV1 {
  schemaVersion: 1;
  operationId: string;
  clauseId: string;
  action: SetGraphicTextV1 | CutRestoreSpeechV1 | TreatmentOperationV1;
}

export interface EditBatchV1 {
  schemaVersion: 1;
  batchId: string;
  requestId: string;
  idempotencyKey: string;
  stage: "cut" | "treatment";
  atomic: true;
  preserveUnrelated: true;
  base: EditBatchBaseRevisionV1;
  operations: TypedOperationEnvelopeV1[];
}

const BASE_KEYS = [
  "projectRevisionHash", "planContentHash", "manifestHash",
  "sourceSnapshotSetHash", "timelineMapHash", "canvasProfileHash",
  "destinationProfileHashes", "pictureLockHash",
] as const;
const OPERATION_KEYS = ["schemaVersion", "operationId", "clauseId", "action"] as const;
const BATCH_KEYS = [
  "schemaVersion", "batchId", "requestId", "idempotencyKey", "stage",
  "atomic", "preserveUnrelated", "base", "operations",
] as const;

function parseBase(value: unknown): EditBatchBaseRevisionV1 {
  const base = objectValue(value, "EditBatchV1.base");
  exactKeys(base, BASE_KEYS, BASE_KEYS, "EditBatchV1.base");
  return {
    projectRevisionHash: sha256(base.projectRevisionHash, "base.projectRevisionHash"),
    planContentHash: sha256(base.planContentHash, "base.planContentHash"),
    manifestHash: sha256(base.manifestHash, "base.manifestHash"),
    sourceSnapshotSetHash: sha256(
      base.sourceSnapshotSetHash,
      "base.sourceSnapshotSetHash",
    ),
    timelineMapHash: sha256(base.timelineMapHash, "base.timelineMapHash"),
    canvasProfileHash: sha256(base.canvasProfileHash, "base.canvasProfileHash"),
    destinationProfileHashes: uniqueStrings(
      base.destinationProfileHashes,
      "base.destinationProfileHashes",
      sha256,
    ),
    pictureLockHash: sha256(base.pictureLockHash, "base.pictureLockHash"),
  };
}

function parseOperation(value: unknown): TypedOperationEnvelopeV1 {
  const operation = objectValue(value, "TypedOperationEnvelopeV1");
  exactKeys(operation, OPERATION_KEYS, OPERATION_KEYS, "TypedOperationEnvelopeV1");
  if (operation.schemaVersion !== 1) {
    throw new Error("TypedOperationEnvelopeV1 version is unsupported");
  }
  const action = objectValue(operation.action, "TypedOperationEnvelopeV1.action");
  const parsedAction = action.operation === "cut.restoreSpeech"
    ? parseCutRestoreSpeechV1(action)
    : action.operation === "SetGraphicTextV1"
      ? parseSetGraphicTextV1(action)
      : parseTreatmentOperationV1(action);
  return {
    schemaVersion: 1,
    operationId: uuid(operation.operationId, "operationId"),
    clauseId: uuid(operation.clauseId, "clauseId"),
    action: parsedAction,
  };
}

function assertStageOperations(
  stage: EditBatchV1["stage"],
  operations: TypedOperationEnvelopeV1[],
): void {
  const hasWrongStage = operations.some((operation) => (
    stage === "cut"
      ? operation.action.operation !== "cut.restoreSpeech"
      : operation.action.operation === "cut.restoreSpeech"
  ));
  if (hasWrongStage) {
    throw new Error(`${stage} batch contains an operation from another stage`);
  }
}

function assertCutBindings(
  batch: EditBatchV1,
): void {
  if (batch.stage !== "cut") return;
  for (const operation of batch.operations) {
    const action = operation.action as CutRestoreSpeechV1;
    if (action.parentPictureLockHash !== batch.base.pictureLockHash
        || action.parentTimelineMapHash !== batch.base.timelineMapHash) {
      throw new Error("cut repair does not bind the batch parent lock and timeline");
    }
  }
}

/** Parse one closed cut or treatment batch; unreleased actions fail closed. */
export function parseEditBatchV1(
  value: unknown,
  request?: EditRequestV1,
): EditBatchV1 {
  const batch = objectValue(value, "EditBatchV1");
  exactKeys(batch, BATCH_KEYS, BATCH_KEYS, "EditBatchV1");
  if (batch.schemaVersion !== 1
      || !["cut", "treatment"].includes(String(batch.stage))
      || batch.atomic !== true || batch.preserveUnrelated !== true) {
    throw new Error("EditBatchV1 policy or stage is unsupported");
  }
  if (!Array.isArray(batch.operations) || batch.operations.length === 0) {
    throw new Error("EditBatchV1.operations must be a non-empty array");
  }
  const operations = batch.operations.map(parseOperation);
  const stage = batch.stage as EditBatchV1["stage"];
  assertStageOperations(stage, operations);
  const operationIds = operations.map((operation) => operation.operationId);
  const clauseIds = operations.map((operation) => operation.clauseId);
  if (new Set(operationIds).size !== operations.length
      || new Set(clauseIds).size !== operations.length) {
    throw new Error("EditBatchV1 operation and clause ids must be unique");
  }
  const parsed: EditBatchV1 = {
    schemaVersion: 1,
    batchId: uuid(batch.batchId, "EditBatchV1.batchId"),
    requestId: uuid(batch.requestId, "EditBatchV1.requestId"),
    idempotencyKey: uuid(batch.idempotencyKey, "EditBatchV1.idempotencyKey"),
    stage,
    atomic: true,
    preserveUnrelated: true,
    base: parseBase(batch.base),
    operations,
  };
  assertCutBindings(parsed);
  if (request) assertRequestBinding(parsed, request);
  return parsed;
}

function assertRequestBinding(batch: EditBatchV1, request: EditRequestV1): void {
  if (batch.requestId !== request.requestId
      || batch.idempotencyKey !== request.idempotencyKey
      || batch.base.projectRevisionHash !== request.parentRevisionHash) {
    throw new Error("EditBatchV1 does not bind the supplied request and parent");
  }
  const clauses = new Map(request.clauses.map((clause) => [clause.clauseId, clause]));
  for (const operation of batch.operations) {
    const clause = clauses.get(operation.clauseId);
    if (!clause || clause.state !== "candidate-executed") {
      throw new Error(`operation clause ${operation.clauseId} is not candidate-executed`);
    }
  }
}
