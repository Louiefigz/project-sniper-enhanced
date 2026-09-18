import { existsSync, readdirSync } from "node:fs";
import path from "node:path";
import {
  parseCommitIntentV1,
  type CommitIntentStateV1,
  type CommitIntentV1,
} from "@/lib/producer/contracts/commit-intent";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  authorityKey,
  producerAuthorityPaths,
  readAuthorityJsonSync,
  writeMutableAuthorityJsonSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";
import {
  verifyProducerCommitArtifactsSync,
  verifyCommittedProducerReceiptSync,
  writeCommittedProducerReceiptSync,
} from "./producer-revision-artifacts";
import {
  advancePath,
  publishProducerAdvanceSync,
  resolveProducerAuthorityHeadSync,
  revisionIsAncestorSync,
} from "./producer-revision-head";
import {
  parseProducerAdvanceRecordV1,
  parseProducerIdempotencyRecordV1,
  type ProducerIdempotencyRecordV1,
} from "./producer-revision-store-model";

export type ProducerCommitBoundary =
  | "after-materialized"
  | "after-candidates-proved"
  | "after-local-commit-intent"
  | "after-advance"
  | "after-head"
  | "after-receipt"
  | "after-committed";

export interface ProducerCommitHooks {
  after?: (boundary: ProducerCommitBoundary) => void;
}

export interface ProducerCommitOutcome {
  status: "committed" | "replayed" | "aborted" | "reconciliation-required";
  childRevisionHash: string;
  receiptHash: string | null;
}

interface RecoveryContext {
  producerDir: string;
  paths: ProducerAuthorityPaths;
  record: ProducerIdempotencyRecordV1;
  intent: CommitIntentV1;
  hooks: ProducerCommitHooks;
}

interface IntentTransition {
  state: CommitIntentStateV1;
  receiptHash?: string | null;
  failureReason?: string;
}

const TERMINAL = new Set<CommitIntentStateV1>([
  "COMMITTED",
  "ABORTED",
  "RECONCILIATION_REQUIRED",
]);

function intentPath(paths: ProducerAuthorityPaths, key: string): string {
  return path.join(paths.intents, `${authorityKey(key)}.json`);
}

function idempotencyPath(paths: ProducerAuthorityPaths, key: string): string {
  return path.join(paths.idempotency, `${authorityKey(key)}.json`);
}

function readRecord(
  paths: ProducerAuthorityPaths,
  key: string,
): ProducerIdempotencyRecordV1 {
  return parseProducerIdempotencyRecordV1(
    readAuthorityJsonSync(idempotencyPath(paths, key)),
  );
}

function readIntent(
  paths: ProducerAuthorityPaths,
  key: string,
): CommitIntentV1 {
  return parseCommitIntentV1(readAuthorityJsonSync(intentPath(paths, key)));
}

function preparedIntent(record: ProducerIdempotencyRecordV1): CommitIntentV1 {
  return parseCommitIntentV1({
    schemaVersion: 1,
    idempotencyKey: record.idempotencyKey,
    requestDigest: record.requestDigest,
    expectedParentRevisionHash: record.expectedParentRevisionHash,
    childRevisionHash: record.childRevisionHash,
    state: "PREPARING",
    artifactHashes: record.artifactHashes,
    receiptHash: null,
    recordedAt: record.recordedAt,
    updatedAt: record.recordedAt,
  });
}

function restoreMissingIntents(paths: ProducerAuthorityPaths): void {
  for (const name of readdirSync(paths.idempotency).filter((row) => row.endsWith(".json"))) {
    const record = parseProducerIdempotencyRecordV1(
      readAuthorityJsonSync(path.join(paths.idempotency, name)),
    );
    const destination = intentPath(paths, record.idempotencyKey);
    if (!existsSync(destination)) {
      writeMutableAuthorityJsonSync(destination, preparedIntent(record));
    }
  }
}

function transitionIntent(
  paths: ProducerAuthorityPaths,
  intent: CommitIntentV1,
  transition: IntentTransition,
): CommitIntentV1 {
  const receiptHash = transition.receiptHash === undefined
    ? intent.receiptHash : transition.receiptHash;
  const next = parseCommitIntentV1({
    ...intent,
    state: transition.state,
    receiptHash,
    updatedAt: new Date().toISOString(),
    ...(transition.failureReason
      ? { failureReason: transition.failureReason } : {}),
  });
  writeMutableAuthorityJsonSync(intentPath(paths, intent.idempotencyKey), next);
  return next;
}

function matchingAdvance(
  paths: ProducerAuthorityPaths,
  record: ProducerIdempotencyRecordV1,
): boolean {
  const destination = advancePath(paths, record.expectedParentRevisionHash);
  try {
    if (!existsSync(destination)) {
      publishProducerAdvanceSync(paths, {
        schemaVersion: 1,
        expectedParentRevisionHash: record.expectedParentRevisionHash,
        childRevisionHash: record.childRevisionHash,
        idempotencyKey: record.idempotencyKey,
        requestDigest: record.requestDigest,
      });
    }
  } catch (error) {
    if (!existsSync(destination)) throw error;
  }
  const advance = parseProducerAdvanceRecordV1(readAuthorityJsonSync(destination));
  return advance.childRevisionHash === record.childRevisionHash
    && advance.idempotencyKey === record.idempotencyKey
    && advance.requestDigest === record.requestDigest;
}

function validateIntentBinding(
  intent: CommitIntentV1,
  record: ProducerIdempotencyRecordV1,
): void {
  if (intent.idempotencyKey !== record.idempotencyKey
      || intent.requestDigest !== record.requestDigest
      || intent.expectedParentRevisionHash !== record.expectedParentRevisionHash
      || intent.childRevisionHash !== record.childRevisionHash
      || canonicalJsonSha256(intent.artifactHashes)
        !== canonicalJsonSha256(record.artifactHashes)) {
    throw new Error("commit intent does not bind its idempotency record");
  }
}

function finalizeCommitted(
  paths: ProducerAuthorityPaths,
  record: ProducerIdempotencyRecordV1,
  intent: CommitIntentV1,
  hooks: ProducerCommitHooks,
): ProducerCommitOutcome {
  const receiptHash = writeCommittedProducerReceiptSync(paths, record);
  hooks.after?.("after-receipt");
  transitionIntent(paths, intent, { state: "COMMITTED", receiptHash });
  hooks.after?.("after-committed");
  return { status: "committed", childRevisionHash: record.childRevisionHash, receiptHash };
}

function advancePreparedCommit(context: RecoveryContext): ProducerCommitOutcome {
  const { producerDir, paths, record, hooks } = context;
  let { intent } = context;
  const before = resolveProducerAuthorityHeadSync(producerDir);
  if (before !== record.expectedParentRevisionHash
      && !revisionIsAncestorSync(paths, record.childRevisionHash, before)) {
    intent = transitionIntent(paths, intent, {
      state: "ABORTED", receiptHash: null, failureReason: "expected parent lost",
    });
    return { status: "aborted", childRevisionHash: record.childRevisionHash,
      receiptHash: intent.receiptHash };
  }
  if (intent.state !== "LOCAL_COMMITTING") {
    intent = transitionIntent(paths, intent, { state: "LOCAL_COMMITTING" });
    hooks.after?.("after-local-commit-intent");
  }
  if (!matchingAdvance(paths, record)) {
    intent = transitionIntent(paths, intent, {
      state: "ABORTED", receiptHash: null, failureReason: "parent advance lost",
    });
    return { status: "aborted", childRevisionHash: record.childRevisionHash,
      receiptHash: intent.receiptHash };
  }
  hooks.after?.("after-advance");
  const head = resolveProducerAuthorityHeadSync(producerDir);
  hooks.after?.("after-head");
  if (!revisionIsAncestorSync(paths, record.childRevisionHash, head)) {
    intent = transitionIntent(
      paths,
      intent,
      {
        state: "RECONCILIATION_REQUIRED",
        receiptHash: null,
        failureReason: "selected head does not contain the reserved child",
      },
    );
    return { status: "reconciliation-required",
      childRevisionHash: record.childRevisionHash, receiptHash: intent.receiptHash };
  }
  return finalizeCommitted(paths, record, intent, hooks);
}

export function recoverProducerCommitSync(
  producerDir: string,
  idempotencyKey: string,
  hooks: ProducerCommitHooks = {},
): ProducerCommitOutcome {
  const paths = producerAuthorityPaths(producerDir);
  const record = readRecord(paths, idempotencyKey);
  let intent = readIntent(paths, idempotencyKey);
  validateIntentBinding(intent, record);
  verifyProducerCommitArtifactsSync(paths, record);
  if (intent.state === "COMMITTED") {
    verifyCommittedProducerReceiptSync(paths, record, intent.receiptHash!);
    const head = resolveProducerAuthorityHeadSync(producerDir);
    if (!revisionIsAncestorSync(paths, record.childRevisionHash, head)) {
      throw new Error("committed child is not in the selected revision lineage");
    }
    return {
      status: "replayed",
      childRevisionHash: record.childRevisionHash,
      receiptHash: intent.receiptHash,
    };
  }
  if (intent.state === "ABORTED" || intent.state === "RECONCILIATION_REQUIRED") {
    return {
      status: intent.state === "ABORTED" ? "aborted" : "reconciliation-required",
      childRevisionHash: record.childRevisionHash,
      receiptHash: intent.receiptHash,
    };
  }
  if (intent.state === "PALMIER_ACTIVATING" || intent.state === "PALMIER_ACTIVE") {
    intent = transitionIntent(paths, intent, {
      state: "RECONCILIATION_REQUIRED", receiptHash: null,
      failureReason: "local recovery cannot prove the selected Palmier head",
    });
    return {
      status: "reconciliation-required",
      childRevisionHash: record.childRevisionHash,
      receiptHash: intent.receiptHash,
    };
  }
  if (intent.state === "PREPARING") {
    intent = transitionIntent(paths, intent, { state: "CANDIDATES_PROVED" });
    hooks.after?.("after-candidates-proved");
  }
  return advancePreparedCommit({ producerDir, paths, record, intent, hooks });
}

export function unresolvedProducerIntentsSync(producerDir: string): CommitIntentV1[] {
  const paths = producerAuthorityPaths(producerDir);
  restoreMissingIntents(paths);
  return readdirSync(paths.intents)
    .filter((name) => name.endsWith(".json"))
    .map((name) => parseCommitIntentV1(
      readAuthorityJsonSync(path.join(paths.intents, name)),
    ))
    .filter((intent) => !TERMINAL.has(intent.state));
}

export function reconcileProducerAuthoritySync(
  producerDir: string,
): ProducerCommitOutcome[] {
  return unresolvedProducerIntentsSync(producerDir)
    .map((intent) => recoverProducerCommitSync(producerDir, intent.idempotencyKey));
}
