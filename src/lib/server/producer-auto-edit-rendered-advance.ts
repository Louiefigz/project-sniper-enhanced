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

/** Build the one deterministic parent-CAS record for rendered authority. */
export function renderedAdvanceRecord(
  parentHash: string,
  childHash: string,
  evidenceHash: string,
): ProducerAdvanceRecordV1 {
  const requestDigest = canonicalJsonSha256({
    kind: "producer-auto-edit-rendered-advance",
    transitionEvidenceHash: evidenceHash,
    childRevisionHash: childHash,
  });
  return parseProducerAdvanceRecordV1({
    schemaVersion: 1,
    expectedParentRevisionHash: parentHash,
    childRevisionHash: childHash,
    idempotencyKey: deterministicUuid(requestDigest),
    requestDigest,
  });
}

/** Resolve an ambiguous immutable publication only from the exact winner. */
export function renderedAdvanceSelected(
  paths: ProducerAuthorityPaths,
  expected: ProducerAdvanceRecordV1,
): boolean {
  const file = advancePath(paths, expected.expectedParentRevisionHash);
  if (!existsSync(file)) return false;
  const observed = parseProducerAdvanceRecordV1(readAuthorityJsonSync(file));
  return canonicalJsonSha256(observed) === canonicalJsonSha256(expected);
}
