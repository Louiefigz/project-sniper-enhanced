import {
  exactKeys,
  hashRecord,
  isoDate,
  objectValue,
  sha256,
  uuid,
} from "@/lib/producer/contracts/validation";

export interface ProducerIdempotencyRecordV1 {
  schemaVersion: 1;
  idempotencyKey: string;
  requestDigest: string;
  expectedParentRevisionHash: string;
  childRevisionHash: string;
  artifactHashes: Record<string, string>;
  receiptId: string;
  recordedAt: string;
  invariantProofHash: string;
}

export interface ProducerAdvanceRecordV1 {
  schemaVersion: 1;
  expectedParentRevisionHash: string;
  childRevisionHash: string;
  idempotencyKey: string;
  requestDigest: string;
}

export interface ProducerGenesisRecordV1 {
  schemaVersion: 1;
  revisionHash: string;
}

const IDEMPOTENCY_KEYS = [
  "schemaVersion", "idempotencyKey", "requestDigest",
  "expectedParentRevisionHash", "childRevisionHash", "artifactHashes",
  "receiptId", "recordedAt", "invariantProofHash",
] as const;
const ADVANCE_KEYS = [
  "schemaVersion", "expectedParentRevisionHash", "childRevisionHash",
  "idempotencyKey", "requestDigest",
] as const;

export function parseProducerIdempotencyRecordV1(
  value: unknown,
): ProducerIdempotencyRecordV1 {
  const record = objectValue(value, "ProducerIdempotencyRecordV1");
  exactKeys(record, IDEMPOTENCY_KEYS, IDEMPOTENCY_KEYS, "ProducerIdempotencyRecordV1");
  if (record.schemaVersion !== 1) {
    throw new Error("ProducerIdempotencyRecordV1 version is unsupported");
  }
  return {
    schemaVersion: 1,
    idempotencyKey: uuid(record.idempotencyKey, "idempotencyKey"),
    requestDigest: sha256(record.requestDigest, "requestDigest"),
    expectedParentRevisionHash: sha256(
      record.expectedParentRevisionHash,
      "expectedParentRevisionHash",
    ),
    childRevisionHash: sha256(record.childRevisionHash, "childRevisionHash"),
    artifactHashes: hashRecord(record.artifactHashes, "artifactHashes"),
    receiptId: uuid(record.receiptId, "receiptId"),
    recordedAt: isoDate(record.recordedAt, "recordedAt"),
    invariantProofHash: sha256(record.invariantProofHash, "invariantProofHash"),
  };
}

export function parseProducerAdvanceRecordV1(
  value: unknown,
): ProducerAdvanceRecordV1 {
  const record = objectValue(value, "ProducerAdvanceRecordV1");
  exactKeys(record, ADVANCE_KEYS, ADVANCE_KEYS, "ProducerAdvanceRecordV1");
  if (record.schemaVersion !== 1) {
    throw new Error("ProducerAdvanceRecordV1 version is unsupported");
  }
  return {
    schemaVersion: 1,
    expectedParentRevisionHash: sha256(
      record.expectedParentRevisionHash,
      "expectedParentRevisionHash",
    ),
    childRevisionHash: sha256(record.childRevisionHash, "childRevisionHash"),
    idempotencyKey: uuid(record.idempotencyKey, "idempotencyKey"),
    requestDigest: sha256(record.requestDigest, "requestDigest"),
  };
}

export function sameIdempotencyRecord(
  left: ProducerIdempotencyRecordV1,
  right: ProducerIdempotencyRecordV1,
): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function parseProducerGenesisRecordV1(
  value: unknown,
): ProducerGenesisRecordV1 {
  const record = objectValue(value, "ProducerGenesisRecordV1");
  exactKeys(
    record,
    ["schemaVersion", "revisionHash"],
    ["schemaVersion", "revisionHash"],
    "ProducerGenesisRecordV1",
  );
  if (record.schemaVersion !== 1) {
    throw new Error("ProducerGenesisRecordV1 version is unsupported");
  }
  return {
    schemaVersion: 1,
    revisionHash: sha256(record.revisionHash, "genesis revisionHash"),
  };
}
