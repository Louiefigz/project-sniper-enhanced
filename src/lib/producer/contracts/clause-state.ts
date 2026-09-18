import {
  enumValue,
  exactKeys,
  objectValue,
  stableId,
  stringValue,
  type JsonRecord,
} from "./validation";

export const CLAUSE_STATES = [
  "pending",
  "deferred",
  "compiled",
  "ambiguous",
  "unsupported",
  "conflict",
  "candidate-executed",
  "not-promoted",
  "superseded",
  "committed",
] as const;

export type ClauseStatusV1 = typeof CLAUSE_STATES[number];

export interface ClauseStateV1 {
  schemaVersion: 1;
  clauseId: string;
  text: string;
  state: ClauseStatusV1;
  disposition: string;
  blockingClauseIds: string[];
  supersedesClauseId?: string;
}

const ALLOWED = [
  "schemaVersion", "clauseId", "text", "state", "disposition",
  "blockingClauseIds", "supersedesClauseId",
] as const;
const REQUIRED = [
  "schemaVersion", "clauseId", "text", "state", "disposition",
  "blockingClauseIds",
] as const;

function blockingIds(value: unknown, label: string): string[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  const ids = value.map((item, index) => stableId(item, `${label}[${index}]`));
  if (new Set(ids).size !== ids.length) throw new Error(`${label} must be unique`);
  return ids;
}

/** Parse the one clause-state shape shared by storage, receipts, and UI. */
export function parseClauseStateV1(value: unknown): ClauseStateV1 {
  const row = objectValue(value, "ClauseStateV1");
  exactKeys(row, ALLOWED, REQUIRED, "ClauseStateV1");
  if (row.schemaVersion !== 1) throw new Error("ClauseStateV1 version is unsupported");
  const result: ClauseStateV1 = {
    schemaVersion: 1,
    clauseId: stableId(row.clauseId, "ClauseStateV1.clauseId"),
    text: stringValue(row.text, "ClauseStateV1.text", 20_000),
    state: enumValue(row.state, CLAUSE_STATES, "ClauseStateV1.state"),
    disposition: stringValue(row.disposition, "ClauseStateV1.disposition", 2_000),
    blockingClauseIds: blockingIds(
      row.blockingClauseIds,
      "ClauseStateV1.blockingClauseIds",
    ),
  };
  if (row.supersedesClauseId !== undefined) {
    result.supersedesClauseId = stableId(
      row.supersedesClauseId,
      "ClauseStateV1.supersedesClauseId",
    );
  }
  if (result.blockingClauseIds.includes(result.clauseId)) {
    throw new Error("ClauseStateV1 cannot block itself");
  }
  return result;
}

export function commitClauseStates(
  clauses: ClauseStateV1[],
  committedIds: ReadonlySet<string>,
): ClauseStateV1[] {
  return clauses.map((clause) => {
    if (!committedIds.has(clause.clauseId)) return clause;
    if (clause.state !== "candidate-executed") {
      throw new Error(`clause ${clause.clauseId} is not candidate-executed`);
    }
    return {
      ...clause,
      state: "committed" as const,
      disposition: "committed by the bound stage batch",
    };
  });
}

export function clauseById(
  clauses: ClauseStateV1[],
): Map<string, ClauseStateV1> {
  const indexed = new Map<string, ClauseStateV1>();
  for (const clause of clauses) {
    if (indexed.has(clause.clauseId)) {
      throw new Error(`duplicate clause id ${clause.clauseId}`);
    }
    indexed.set(clause.clauseId, clause);
  }
  return indexed;
}

export function clauseRecord(value: unknown): JsonRecord {
  return objectValue(value, "clause record");
}
