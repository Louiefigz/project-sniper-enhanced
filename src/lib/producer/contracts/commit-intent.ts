import {
  enumValue,
  exactKeys,
  hashRecord,
  isoDate,
  objectValue,
  sha256,
  stringValue,
  uuid,
} from "./validation";

export const COMMIT_INTENT_STATES = [
  "PREPARING",
  "CANDIDATES_PROVED",
  "PALMIER_ACTIVATING",
  "PALMIER_ACTIVE",
  "LOCAL_COMMITTING",
  "COMMITTED",
  "ABORTED",
  "RECONCILIATION_REQUIRED",
] as const;

export type CommitIntentStateV1 = typeof COMMIT_INTENT_STATES[number];

export interface CommitIntentV1 {
  schemaVersion: 1;
  idempotencyKey: string;
  requestDigest: string;
  expectedParentRevisionHash: string;
  childRevisionHash: string;
  state: CommitIntentStateV1;
  artifactHashes: Record<string, string>;
  receiptHash: string | null;
  recordedAt: string;
  updatedAt: string;
  failureReason?: string;
}

const KEYS = [
  "schemaVersion", "idempotencyKey", "requestDigest",
  "expectedParentRevisionHash", "childRevisionHash", "state",
  "artifactHashes", "receiptHash", "recordedAt", "updatedAt", "failureReason",
] as const;
const REQUIRED = KEYS.filter((key) => key !== "failureReason");

export function parseCommitIntentV1(value: unknown): CommitIntentV1 {
  const intent = objectValue(value, "CommitIntentV1");
  exactKeys(intent, KEYS, REQUIRED, "CommitIntentV1");
  if (intent.schemaVersion !== 1) {
    throw new Error("CommitIntentV1 version is unsupported");
  }
  const result: CommitIntentV1 = {
    schemaVersion: 1,
    idempotencyKey: uuid(intent.idempotencyKey, "CommitIntentV1.idempotencyKey"),
    requestDigest: sha256(intent.requestDigest, "CommitIntentV1.requestDigest"),
    expectedParentRevisionHash: sha256(
      intent.expectedParentRevisionHash,
      "CommitIntentV1.expectedParentRevisionHash",
    ),
    childRevisionHash: sha256(intent.childRevisionHash, "childRevisionHash"),
    state: enumValue(intent.state, COMMIT_INTENT_STATES, "CommitIntentV1.state"),
    artifactHashes: hashRecord(intent.artifactHashes, "artifactHashes"),
    receiptHash: intent.receiptHash === null
      ? null : sha256(intent.receiptHash, "receiptHash"),
    recordedAt: isoDate(intent.recordedAt, "CommitIntentV1.recordedAt"),
    updatedAt: isoDate(intent.updatedAt, "CommitIntentV1.updatedAt"),
  };
  if (intent.failureReason !== undefined) {
    result.failureReason = stringValue(intent.failureReason, "failureReason", 2_000);
  }
  if (result.state === "COMMITTED" && result.receiptHash === null) {
    throw new Error("committed intent requires a receipt hash");
  }
  if (result.state !== "COMMITTED" && result.receiptHash !== null) {
    throw new Error("only a committed intent may bind a committed receipt");
  }
  const failed = result.state === "ABORTED"
    || result.state === "RECONCILIATION_REQUIRED";
  if (failed !== Boolean(result.failureReason)) {
    throw new Error("failed intent state and failureReason must agree");
  }
  return result;
}
