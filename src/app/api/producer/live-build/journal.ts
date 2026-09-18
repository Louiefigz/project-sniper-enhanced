import fs from "node:fs";
import { canonicalJsonSha256, fileSha256 } from
  "@/lib/server/auto-edit-hash";
import type { PalmierOpEvent } from "@/lib/producer/palmier-op-event";
import {
  appliedMutationIds,
  applyLiveBuildJournalRow,
  emptyLiveBuildJournal,
  latestLiveBuildHead,
  LiveBuildJournalError,
  unresolvedMutationIds,
  type LiveBuildJournalLedger,
  type LiveBuildJournalOperation,
} from "./journal-model";
import {
  appendLiveBuildJournal,
  liveBuildJournalPath,
} from "./state";

const MAX_JOURNAL_BYTES = 64 * 1024 * 1024;
const MAX_JOURNAL_ROW_BYTES = 16_000;

export interface ClosedLiveBuildJournal {
  path: string;
  hash: string;
  operationCount: number;
  lifecycleDigest: string;
  headFingerprint: string;
}

function assertDurableRow(row: Record<string, unknown>): void {
  if (Buffer.byteLength(JSON.stringify(row)) > MAX_JOURNAL_ROW_BYTES) {
    throw new LiveBuildJournalError(
      "live-build operation exceeds the durable journal limit; split it");
  }
}

/** Parse every retained row; malformed or torn JSONL is blocking authority. */
export function readStrictLiveBuildJournal(
  dir: string,
): LiveBuildJournalLedger {
  const filePath = liveBuildJournalPath(dir);
  if (!fs.existsSync(filePath)) return emptyLiveBuildJournal();
  const bytes = fs.readFileSync(filePath);
  if (bytes.length > MAX_JOURNAL_BYTES) {
    throw new LiveBuildJournalError("live-build journal exceeds 64 MiB");
  }
  if (bytes.length && bytes.at(-1) !== 0x0a) {
    throw new LiveBuildJournalError("live-build journal has a torn final row");
  }
  const ledger = emptyLiveBuildJournal();
  for (const line of bytes.toString("utf8").split("\n").filter(Boolean)) {
    if (Buffer.byteLength(line) > MAX_JOURNAL_ROW_BYTES) {
      throw new LiveBuildJournalError(
        "live-build journal row exceeds the durable limit");
    }
    let value: unknown;
    try { value = JSON.parse(line); } catch {
      throw new LiveBuildJournalError("live-build journal contains invalid JSON");
    }
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new LiveBuildJournalError("live-build journal row is not an object");
    }
    applyLiveBuildJournalRow(
      ledger, value as Record<string, unknown>);
  }
  return ledger;
}

export function appendLiveBuildOperationEvent(
  dir: string,
  ledger: LiveBuildJournalLedger,
  event: PalmierOpEvent,
): void {
  const row = { at: new Date().toISOString(), ...event };
  assertDurableRow(row);
  applyLiveBuildJournalRow(ledger, row);
  appendLiveBuildJournal(dir, row);
}

export function appendLiveBuildHead(
  dir: string,
  ledger: LiveBuildJournalLedger,
  fingerprint: string,
  resolvedNotAppliedIds: string[] = [],
): void {
  const event = resolvedNotAppliedIds.length
    ? "live_build_reconciliation" : "live_build_head";
  const row = {
    at: new Date().toISOString(),
    event,
    fingerprint,
    verifiedOperationIds: appliedMutationIds(ledger),
    ...(resolvedNotAppliedIds.length
      ? { resolvedNotAppliedIds: [...resolvedNotAppliedIds].sort() } : {}),
  };
  assertDurableRow(row);
  applyLiveBuildJournalRow(ledger, row);
  appendLiveBuildJournal(dir, row);
}

export function operationsAfterHead(
  ledger: LiveBuildJournalLedger,
): LiveBuildJournalOperation[] {
  const head = latestLiveBuildHead(ledger);
  if (!head) return [...ledger.operations.values()];
  return [...ledger.operations.values()].filter(
    (operation) => operation.mutation
      && operation.transitionIndex > head.index);
}

export function pendingMutationIds(
  ledger: LiveBuildJournalLedger,
): string[] {
  return unresolvedMutationIds(ledger);
}

export function liveBuildJournalCounts(
  ledger: LiveBuildJournalLedger,
): { operationsSeen: number; operationsCompleted: number } {
  const mutations = [...ledger.operations.values()].filter(
    (operation) => operation.mutation);
  return {
    operationsSeen: mutations.length,
    operationsCompleted: mutations.filter(
      (operation) => operation.status === "applied").length,
  };
}

export function verifiedLiveBuildOperations(
  ledger: LiveBuildJournalLedger,
): Array<{ operationId: string; tool: string; inputHash: string }> {
  return [...ledger.operations.values()]
    .filter((operation) =>
      operation.mutation && operation.status === "applied")
    .map(({ operationId, tool, inputHash }) => ({
      operationId, tool, inputHash,
    }))
    .sort((left, right) =>
      left.operationId.localeCompare(right.operationId));
}

function lifecycleDigest(
  ledger: LiveBuildJournalLedger,
  fingerprint: string,
): string {
  const operations = [...ledger.operations.values()]
    .filter((operation) => operation.mutation)
    .map(({ operationId, tool, inputHash, status }) => ({
      operationId, tool, inputHash, status,
    }))
    .sort((left, right) =>
      left.operationId.localeCompare(right.operationId));
  return canonicalJsonSha256({ fingerprint, operations });
}

/** Freeze only a fully read-back journal with no unresolved mutation. */
export function closeLiveBuildJournal(
  dir: string,
  expectedFingerprint: string,
): ClosedLiveBuildJournal {
  const beforeHash = fileSha256(liveBuildJournalPath(dir));
  const ledger = readStrictLiveBuildJournal(dir);
  const hash = fileSha256(liveBuildJournalPath(dir));
  const head = latestLiveBuildHead(ledger);
  if (!head || head.index !== ledger.rowCount
      || head.fingerprint !== expectedFingerprint
      || unresolvedMutationIds(ledger).length) {
    throw new LiveBuildJournalError(
      "live-build journal is not closed at the exact candidate readback");
  }
  const counts = liveBuildJournalCounts(ledger);
  if (!hash || hash !== beforeHash || counts.operationsCompleted < 1) {
    throw new LiveBuildJournalError(
      "live-build closed journal changed or has no applied mutation");
  }
  return {
    path: liveBuildJournalPath(dir),
    hash,
    operationCount: counts.operationsCompleted,
    lifecycleDigest: lifecycleDigest(ledger, head.fingerprint),
    headFingerprint: head.fingerprint,
  };
}

export {
  emptyLiveBuildJournal,
  latestLiveBuildHead,
  LiveBuildJournalError,
  type LiveBuildJournalLedger,
};
