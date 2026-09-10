import { COMMIT_INTENT_STATES, type CommitIntentStateV1 } from "./commit-intent";
import {
  enumValue,
  exactKeys,
  isoDate,
  objectValue,
  sha256,
  stableId,
  stringValue,
  uuid,
} from "./validation";

export interface PalmierActivationReadbackV1 {
  headId: string;
  candidateHash: string;
  timelineHash: string;
  observedAt: string;
}

export interface PalmierCommitSagaV1 {
  schemaVersion: 1;
  sagaId: string;
  idempotencyKey: string;
  state: CommitIntentStateV1;
  expectedLocalParentHash: string;
  reservedLocalChildHash: string;
  expectedPalmierParentId: string;
  reservedPalmierCandidateId: string;
  reservedPalmierCandidateHash: string;
  reservedPalmierTimelineHash: string;
  activationReadback: PalmierActivationReadbackV1 | null;
  failureReason?: string;
  updatedAt: string;
}

const KEYS = [
  "schemaVersion", "sagaId", "idempotencyKey", "state",
  "expectedLocalParentHash", "reservedLocalChildHash",
  "expectedPalmierParentId", "reservedPalmierCandidateId",
  "reservedPalmierCandidateHash", "reservedPalmierTimelineHash",
  "activationReadback", "failureReason", "updatedAt",
] as const;
const REQUIRED = KEYS.filter((key) => key !== "failureReason");

function readback(value: unknown): PalmierActivationReadbackV1 | null {
  if (value === null) return null;
  const row = objectValue(value, "PalmierActivationReadbackV1");
  const keys = ["headId", "candidateHash", "timelineHash", "observedAt"];
  exactKeys(row, keys, keys, "PalmierActivationReadbackV1");
  return {
    headId: stableId(row.headId, "Palmier readback headId"),
    candidateHash: sha256(row.candidateHash, "Palmier candidateHash"),
    timelineHash: sha256(row.timelineHash, "Palmier timelineHash"),
    observedAt: isoDate(row.observedAt, "Palmier readback observedAt"),
  };
}

/** Parse a durable external/local dual-commit state with exact readback. */
export function parsePalmierCommitSagaV1(value: unknown): PalmierCommitSagaV1 {
  const row = objectValue(value, "PalmierCommitSagaV1");
  exactKeys(row, KEYS, REQUIRED, "PalmierCommitSagaV1");
  if (row.schemaVersion !== 1) throw new Error("PalmierCommitSagaV1 version is unsupported");
  const result: PalmierCommitSagaV1 = {
    schemaVersion: 1,
    sagaId: uuid(row.sagaId, "Palmier sagaId"),
    idempotencyKey: uuid(row.idempotencyKey, "Palmier idempotencyKey"),
    state: enumValue(row.state, COMMIT_INTENT_STATES, "Palmier saga state"),
    expectedLocalParentHash: sha256(
      row.expectedLocalParentHash, "expectedLocalParentHash"),
    reservedLocalChildHash: sha256(
      row.reservedLocalChildHash, "reservedLocalChildHash"),
    expectedPalmierParentId: stableId(
      row.expectedPalmierParentId, "expectedPalmierParentId"),
    reservedPalmierCandidateId: stableId(
      row.reservedPalmierCandidateId, "reservedPalmierCandidateId"),
    reservedPalmierCandidateHash: sha256(
      row.reservedPalmierCandidateHash, "reservedPalmierCandidateHash"),
    reservedPalmierTimelineHash: sha256(
      row.reservedPalmierTimelineHash, "reservedPalmierTimelineHash"),
    activationReadback: readback(row.activationReadback),
    updatedAt: isoDate(row.updatedAt, "Palmier saga updatedAt"),
  };
  if (row.failureReason !== undefined) {
    result.failureReason = stringValue(row.failureReason, "failureReason", 2_000);
  }
  assertStateConsistency(result);
  return result;
}

function assertStateConsistency(saga: PalmierCommitSagaV1): void {
  const needsReadback = [
    "PALMIER_ACTIVE", "LOCAL_COMMITTING", "COMMITTED",
  ].includes(saga.state);
  const forbidsReadback = [
    "PREPARING", "CANDIDATES_PROVED", "PALMIER_ACTIVATING", "ABORTED",
  ].includes(saga.state);
  const failed = ["ABORTED", "RECONCILIATION_REQUIRED"].includes(saga.state);
  if ((needsReadback && !saga.activationReadback)
      || (forbidsReadback && saga.activationReadback)) {
    throw new Error("Palmier saga state and activation readback disagree");
  }
  if (failed !== Boolean(saga.failureReason)) {
    throw new Error("Palmier saga failure state and reason disagree");
  }
  if (saga.activationReadback && (
    saga.activationReadback.headId !== saga.reservedPalmierCandidateId
    || saga.activationReadback.candidateHash !== saga.reservedPalmierCandidateHash
    || saga.activationReadback.timelineHash !== saga.reservedPalmierTimelineHash
  )) {
    throw new Error("Palmier activation readback does not bind the reserved candidate");
  }
}
