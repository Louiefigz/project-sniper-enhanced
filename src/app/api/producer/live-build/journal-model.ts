import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { isLiveBuildMutationTool } from "./process";

export type LiveBuildOperationStatus =
  "applying" | "applied" | "failed" | "not-applied";

export interface LiveBuildJournalOperation {
  operationId: string;
  tool: string;
  inputHash: string;
  mutation: boolean;
  status: LiveBuildOperationStatus;
  transitionIndex: number;
}

export interface LiveBuildJournalHead {
  fingerprint: string;
  verifiedOperationIds: string[];
  index: number;
}

export interface LiveBuildJournalLedger {
  operations: Map<string, LiveBuildJournalOperation>;
  heads: LiveBuildJournalHead[];
  rowCount: number;
}

export class LiveBuildJournalError extends Error {}

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new LiveBuildJournalError(`${label} is not an object`);
  }
  return value as Record<string, unknown>;
}

function strings(value: unknown, label: string): string[] {
  if (!Array.isArray(value)
      || value.some((item) => typeof item !== "string" || !item)
      || new Set(value).size !== value.length) {
    throw new LiveBuildJournalError(`${label} is not unique strings`);
  }
  return value as string[];
}

function operationInputHash(row: Record<string, unknown>): string {
  if (row.truncated === true) {
    throw new LiveBuildJournalError(
      "live-build mutation journal payload is truncated");
  }
  return canonicalJsonSha256({
    tool: row.tool,
    input: object(row.input ?? {}, "live-build operation input"),
  });
}

function duplicatesUnsafePayload(
  ledger: LiveBuildJournalLedger,
  current: LiveBuildJournalOperation,
): boolean {
  return [...ledger.operations.values()].some((operation) =>
    operation.operationId !== current.operationId
    && operation.mutation && operation.status !== "not-applied"
    && operation.tool === current.tool
    && operation.inputHash === current.inputHash);
}

function applyOperation(
  ledger: LiveBuildJournalLedger,
  row: Record<string, unknown>,
  index: number,
): void {
  if (row.status !== "applying" || typeof row.operationId !== "string"
      || !row.operationId || typeof row.tool !== "string" || !row.tool) {
    throw new LiveBuildJournalError(
      "live-build applying operation is malformed");
  }
  const operation: LiveBuildJournalOperation = {
    operationId: row.operationId,
    tool: row.tool,
    inputHash: operationInputHash(row),
    mutation: isLiveBuildMutationTool(row.tool),
    status: "applying",
    transitionIndex: index,
  };
  const prior = ledger.operations.get(operation.operationId);
  if (prior) {
    if (prior.tool !== operation.tool
        || prior.inputHash !== operation.inputHash) {
      throw new LiveBuildJournalError(
        "live-build operation id was rebound to another payload");
    }
    if (prior.status !== "applying") {
      throw new LiveBuildJournalError(
        "live-build replayed a terminal operation identity");
    }
    return;
  }
  if (operation.mutation && duplicatesUnsafePayload(ledger, operation)) {
    throw new LiveBuildJournalError(
      "live-build fail-closed replay fence rejected an unsafe payload");
  }
  ledger.operations.set(operation.operationId, operation);
}

function applyResult(
  ledger: LiveBuildJournalLedger,
  row: Record<string, unknown>,
  index: number,
): void {
  if (typeof row.operationId !== "string"
      || !["applied", "failed"].includes(String(row.status))) {
    throw new LiveBuildJournalError("live-build operation result is malformed");
  }
  const operation = ledger.operations.get(row.operationId);
  if (!operation) {
    throw new LiveBuildJournalError(
      "live-build result has no applying operation");
  }
  const status = row.status as "applied" | "failed";
  if (operation.status === status) return;
  if (operation.status !== "applying") {
    throw new LiveBuildJournalError(
      "live-build operation has conflicting or late results");
  }
  operation.status = status;
  operation.transitionIndex = index;
}

export function appliedMutationIds(
  ledger: LiveBuildJournalLedger,
): string[] {
  return [...ledger.operations.values()]
    .filter((operation) =>
      operation.mutation && operation.status === "applied")
    .map((operation) => operation.operationId)
    .sort();
}

function resolveNotApplied(
  ledger: LiveBuildJournalLedger,
  ids: string[],
  index: number,
): void {
  for (const id of ids) {
    const operation = ledger.operations.get(id);
    if (!operation?.mutation
        || !["applying", "failed"].includes(operation.status)) {
      throw new LiveBuildJournalError(
        "live-build reconciliation resolves an ineligible operation");
    }
    operation.status = "not-applied";
    operation.transitionIndex = index;
  }
}

function applyHead(
  ledger: LiveBuildJournalLedger,
  row: Record<string, unknown>,
  index: number,
): void {
  if (typeof row.fingerprint !== "string"
      || !/^[0-9a-f]{64}$/u.test(row.fingerprint)) {
    throw new LiveBuildJournalError(
      "live-build controller head fingerprint is malformed");
  }
  const resolved = row.event === "live_build_reconciliation"
    ? strings(row.resolvedNotAppliedIds, "resolved operation ids") : [];
  resolveNotApplied(ledger, resolved, index);
  if (unresolvedMutationIds(ledger).length) {
    throw new LiveBuildJournalError(
      "live-build controller head leaves unresolved mutations");
  }
  const priorHead = latestLiveBuildHead(ledger);
  const appliedSinceHead = priorHead
    ? [...ledger.operations.values()].some((operation) =>
      operation.mutation && operation.status === "applied"
      && operation.transitionIndex > priorHead.index)
    : false;
  if (priorHead && appliedSinceHead
      && priorHead.fingerprint === row.fingerprint) {
    throw new LiveBuildJournalError(
      "live-build applied mutation produced no candidate delta");
  }
  const verified = strings(
    row.verifiedOperationIds, "verified operation ids").sort();
  if (JSON.stringify(verified)
      !== JSON.stringify(appliedMutationIds(ledger))) {
    throw new LiveBuildJournalError(
      "live-build controller head omits or invents applied operations");
  }
  ledger.heads.push({
    fingerprint: row.fingerprint,
    verifiedOperationIds: verified,
    index,
  });
}

export function applyLiveBuildJournalRow(
  ledger: LiveBuildJournalLedger,
  row: Record<string, unknown>,
): void {
  const index = ledger.rowCount + 1;
  if (typeof row.at !== "string" || !row.at) {
    throw new LiveBuildJournalError("live-build journal row has no timestamp");
  }
  if (row.event === "palmier_op") applyOperation(ledger, row, index);
  else if (row.event === "palmier_op_result") {
    applyResult(ledger, row, index);
  } else if (["live_build_head", "live_build_reconciliation"]
    .includes(String(row.event))) {
    applyHead(ledger, row, index);
  } else {
    throw new LiveBuildJournalError(
      `live-build journal event is unsupported: ${String(row.event)}`);
  }
  ledger.rowCount = index;
}

export function emptyLiveBuildJournal(): LiveBuildJournalLedger {
  return { operations: new Map(), heads: [], rowCount: 0 };
}

export function unresolvedMutationIds(
  ledger: LiveBuildJournalLedger,
): string[] {
  return [...ledger.operations.values()]
    .filter((operation) => operation.mutation
      && ["applying", "failed"].includes(operation.status))
    .map((operation) => operation.operationId)
    .sort();
}

export function latestLiveBuildHead(
  ledger: LiveBuildJournalLedger,
): LiveBuildJournalHead | null {
  return ledger.heads.at(-1) ?? null;
}
