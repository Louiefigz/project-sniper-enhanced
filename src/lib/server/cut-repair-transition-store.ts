import { existsSync, lstatSync, mkdirSync } from "node:fs";
import path from "node:path";
import { parseCommitIntentV1, type CommitIntentV1 } from
  "@/lib/producer/contracts/commit-intent";
import {
  assertObjectHashSync,
  authorityKey,
  producerAuthorityPaths,
  publishImmutableAuthorityJsonSync,
  readAuthorityJsonSync,
  writeMutableAuthorityJsonSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";
import {
  advancePath,
  publishProducerAdvanceSync,
  resolveProducerAuthorityHeadSync,
  revisionIsAncestorSync,
} from "./producer-revision-head";
import { parseProducerAdvanceRecordV1 } from "./producer-revision-store-model";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  parseCutRepairTransitionRecord,
  type CutRepairTransitionHooks,
  type CutRepairTransitionKind,
  type CutRepairTransitionOutcome,
  type CutRepairTransitionRecord,
  type RecoverCutRepairTransitionInput,
} from "./cut-repair-transition-model";
export {
  parseCutRepairTransitionRecord,
} from "./cut-repair-transition-model";
export type {
  CutRepairTransitionBoundary,
  CutRepairTransitionHooks,
  CutRepairTransitionKind,
  CutRepairTransitionOutcome,
  CutRepairTransitionRecord,
  RecoverCutRepairTransitionInput,
} from "./cut-repair-transition-model";
interface RecoveryContext {
  producerDir: string;
  authority: ProducerAuthorityPaths;
  record: CutRepairTransitionRecord;
  intent: CommitIntentV1;
  intentPath: string;
}
interface TransitionPaths { records: string; intents: string }
function ensureDirectory(directory: string): void {
  try {
    mkdirSync(directory, { mode: 0o700 });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }
  const stat = lstatSync(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("cut repair transition path must be a real directory");
  }
}

function transitionPaths(
  paths: ProducerAuthorityPaths,
  transition: CutRepairTransitionKind,
): TransitionPaths {
  const root = path.join(paths.sagas, `cut-repair-${transition}`);
  const records = path.join(root, "records");
  const intents = path.join(root, "intents");
  [root, records, intents].forEach(ensureDirectory);
  return { records, intents };
}

function keyed(directory: string, key: string): string {
  return path.join(directory, `${authorityKey(key)}.json`);
}

function preparedIntent(record: CutRepairTransitionRecord): CommitIntentV1 {
  return parseCommitIntentV1({
    schemaVersion: 1,
    idempotencyKey: record.idempotencyKey,
    requestDigest: record.actionHash,
    expectedParentRevisionHash: record.expectedParentRevisionHash,
    childRevisionHash: record.childRevisionHash,
    state: "PREPARING",
    artifactHashes: record.artifactHashes,
    receiptHash: null,
    recordedAt: record.recordedAt,
    updatedAt: record.recordedAt,
  });
}

function assertIntent(
  intent: CommitIntentV1,
  record: CutRepairTransitionRecord,
): void {
  if (intent.idempotencyKey !== record.idempotencyKey
      || intent.requestDigest !== record.actionHash
      || intent.expectedParentRevisionHash !== record.expectedParentRevisionHash
      || intent.childRevisionHash !== record.childRevisionHash
      || canonicalJsonSha256(intent.artifactHashes)
        !== canonicalJsonSha256(record.artifactHashes)) {
    throw new Error("cut repair transition intent is stale or substituted");
  }
}

interface TransitionIntentUpdate {
  filePath: string;
  intent: CommitIntentV1;
  state: CommitIntentV1["state"];
  receiptHash?: string | null;
  failureReason?: string;
}

function transitionIntent(input: TransitionIntentUpdate): CommitIntentV1 {
  const { filePath, intent, state } = input;
  const next = parseCommitIntentV1({
    ...intent,
    state,
    receiptHash: input.receiptHash ?? null,
    updatedAt: new Date().toISOString(),
    ...(input.failureReason ? { failureReason: input.failureReason } : {}),
  });
  writeMutableAuthorityJsonSync(filePath, next);
  return next;
}

export function materializeCutRepairTransitionSync(
  producerDir: string,
  proposed: CutRepairTransitionRecord,
  hooks: CutRepairTransitionHooks = {},
): CutRepairTransitionRecord {
  const record = parseCutRepairTransitionRecord(proposed);
  const paths = transitionPaths(
    producerAuthorityPaths(producerDir), record.transition);
  const recordPath = keyed(paths.records, record.idempotencyKey);
  publishImmutableAuthorityJsonSync(recordPath, record);
  const observed = parseCutRepairTransitionRecord(
    readAuthorityJsonSync(recordPath));
  if (canonicalJsonSha256(observed) !== canonicalJsonSha256(record)) {
    throw new Error("cut repair idempotency key is bound to another action");
  }
  const intentPath = keyed(paths.intents, record.idempotencyKey);
  if (!existsSync(intentPath)) {
    writeMutableAuthorityJsonSync(intentPath, preparedIntent(record));
  }
  hooks.after?.("after-materialized");
  return record;
}

function matchingAdvance(
  paths: ProducerAuthorityPaths,
  record: CutRepairTransitionRecord,
): boolean {
  const destination = advancePath(paths, record.expectedParentRevisionHash);
  try {
    if (!existsSync(destination)) {
      publishProducerAdvanceSync(paths, {
        schemaVersion: 1,
        expectedParentRevisionHash: record.expectedParentRevisionHash,
        childRevisionHash: record.childRevisionHash,
        idempotencyKey: record.idempotencyKey,
        requestDigest: record.actionHash,
      });
    }
  } catch (error) {
    if (!existsSync(destination)) throw error;
  }
  const advance = parseProducerAdvanceRecordV1(
    readAuthorityJsonSync(destination));
  return advance.childRevisionHash === record.childRevisionHash
    && advance.idempotencyKey === record.idempotencyKey
    && advance.requestDigest === record.actionHash;
}

function outcome(
  intent: CommitIntentV1,
  record: CutRepairTransitionRecord,
): CutRepairTransitionOutcome | null {
  if (intent.state === "ABORTED" || intent.state === "RECONCILIATION_REQUIRED") {
    return {
      status: intent.state === "ABORTED"
        ? "aborted" : "reconciliation-required",
      childRevisionHash: record.childRevisionHash,
      receiptHash: null,
    };
  }
  if (intent.state !== "COMMITTED") return null;
  if (intent.receiptHash !== record.receiptHash) {
    throw new Error("committed cut repair receipt binding changed");
  }
  return {
    status: "replayed",
    childRevisionHash: record.childRevisionHash,
    receiptHash: record.receiptHash,
  };
}

function recoveryContext(
  input: RecoverCutRepairTransitionInput,
): RecoveryContext {
  const authority = producerAuthorityPaths(input.producerDir);
  const paths = transitionPaths(authority, input.transition);
  const record = parseCutRepairTransitionRecord(
    readAuthorityJsonSync(keyed(paths.records, input.idempotencyKey)));
  const intentPath = keyed(paths.intents, input.idempotencyKey);
  const intent = existsSync(intentPath)
    ? parseCommitIntentV1(readAuthorityJsonSync(intentPath))
    : preparedIntent(record);
  if (!existsSync(intentPath)) writeMutableAuthorityJsonSync(intentPath, intent);
  assertIntent(intent, record);
  input.verify(record);
  assertObjectHashSync(authority.objects.receipts, record.receiptHash);
  return {
    producerDir: input.producerDir, authority, record, intent, intentPath,
  };
}

function failedOutcome(
  value: RecoveryContext,
  intent: CommitIntentV1,
  state: "ABORTED" | "RECONCILIATION_REQUIRED",
  failureReason: string,
): CutRepairTransitionOutcome {
  const failed = transitionIntent({
    filePath: value.intentPath, intent, state, failureReason,
  });
  return outcome(failed, value.record)!;
}

function advanceRecovery(
  value: RecoveryContext,
  hooks: CutRepairTransitionHooks,
): CutRepairTransitionOutcome {
  const { producerDir, authority, record, intentPath } = value;
  let { intent } = value;
  const head = resolveProducerAuthorityHeadSync(producerDir);
  if (head !== record.expectedParentRevisionHash
      && !revisionIsAncestorSync(authority, record.childRevisionHash, head)) {
    return failedOutcome(value, intent, "ABORTED", "expected parent lost");
  }
  if (intent.state !== "LOCAL_COMMITTING") {
    intent = transitionIntent({
      filePath: intentPath, intent, state: "LOCAL_COMMITTING",
    });
    hooks.after?.("after-local-commit-intent");
  }
  if (!matchingAdvance(authority, record)) {
    return failedOutcome(value, intent, "ABORTED", "parent advance lost");
  }
  hooks.after?.("after-advance");
  const selected = resolveProducerAuthorityHeadSync(producerDir);
  hooks.after?.("after-head");
  if (!revisionIsAncestorSync(authority, record.childRevisionHash, selected)) {
    return failedOutcome(
      value, intent, "RECONCILIATION_REQUIRED",
      "selected head does not contain the cut repair child");
  }
  transitionIntent({
    filePath: intentPath,
    intent,
    state: "COMMITTED",
    receiptHash: record.receiptHash,
  });
  hooks.after?.("after-committed");
  return {
    status: "committed",
    childRevisionHash: record.childRevisionHash,
    receiptHash: record.receiptHash,
  };
}

export function recoverCutRepairTransitionSync(
  input: RecoverCutRepairTransitionInput,
  hooks: CutRepairTransitionHooks = {},
): CutRepairTransitionOutcome {
  const value = recoveryContext(input);
  const { producerDir, authority, record } = value;
  hooks.after?.("after-receipt-proved");
  const terminal = outcome(value.intent, record);
  if (terminal) {
    const head = resolveProducerAuthorityHeadSync(producerDir);
    if (terminal.status === "replayed"
        && !revisionIsAncestorSync(authority, record.childRevisionHash, head)) {
      throw new Error("committed cut repair child left selected lineage");
    }
    return terminal;
  }
  return advanceRecovery(value, hooks);
}
