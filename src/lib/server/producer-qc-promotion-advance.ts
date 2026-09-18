import { existsSync } from "node:fs";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  readAuthorityJsonSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";
import { advancePath } from "./producer-revision-head";
import {
  parseProducerAdvanceRecordV1,
  type ProducerAdvanceRecordV1,
} from "./producer-revision-store-model";

interface QcPromotionAdvanceInput {
  parentRevisionHash: string;
  childRevisionHash: string;
  graphHash: string;
  graphReceiptHash: string;
  approvalHash: string;
}

function deterministicUuid(digest: string): string {
  const hex = digest.slice(0, 32);
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    `5${hex.slice(13, 16)}`,
    `a${hex.slice(17, 20)}`,
    hex.slice(20),
  ].join("-");
}

export function qcPromotionAdvanceRecord(
  input: QcPromotionAdvanceInput,
): ProducerAdvanceRecordV1 {
  const requestDigest = canonicalJsonSha256({
    kind: "producer-qc-promotion-v2",
    ...input,
  });
  return parseProducerAdvanceRecordV1({
    schemaVersion: 1,
    expectedParentRevisionHash: input.parentRevisionHash,
    childRevisionHash: input.childRevisionHash,
    idempotencyKey: deterministicUuid(requestDigest),
    requestDigest,
  });
}

export function qcPromotionAdvanceSelectedSync(
  paths: ProducerAuthorityPaths,
  expected: ProducerAdvanceRecordV1,
): boolean {
  const destination = advancePath(
    paths, expected.expectedParentRevisionHash);
  if (!existsSync(destination)) return false;
  const observed = parseProducerAdvanceRecordV1(
    readAuthorityJsonSync(destination));
  return canonicalJsonSha256(observed) === canonicalJsonSha256(expected);
}
