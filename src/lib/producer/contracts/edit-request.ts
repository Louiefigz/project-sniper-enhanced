import {
  clauseById,
  commitClauseStates,
  parseClauseStateV1,
  type ClauseStateV1,
} from "./clause-state";
import {
  enumValue,
  exactKeys,
  isoDate,
  objectValue,
  sha256,
  stringValue,
  uuid,
} from "./validation";

export interface EditRequestV1 {
  schemaVersion: 1;
  requestId: string;
  idempotencyKey: string;
  parentRevisionHash: string;
  workflow: "cut-first" | "autopilot";
  rawIntent: string;
  submittedAt: string;
  clauses: ClauseStateV1[];
}

const KEYS = [
  "schemaVersion", "requestId", "idempotencyKey", "parentRevisionHash",
  "workflow", "rawIntent", "submittedAt", "clauses",
] as const;

export function parseEditRequestV1(value: unknown): EditRequestV1 {
  const request = objectValue(value, "EditRequestV1");
  exactKeys(request, KEYS, KEYS, "EditRequestV1");
  if (request.schemaVersion !== 1) throw new Error("EditRequestV1 version is unsupported");
  if (!Array.isArray(request.clauses) || request.clauses.length === 0) {
    throw new Error("EditRequestV1.clauses must be a non-empty array");
  }
  const clauses = request.clauses.map(parseClauseStateV1);
  clauseById(clauses);
  return {
    schemaVersion: 1,
    requestId: uuid(request.requestId, "EditRequestV1.requestId"),
    idempotencyKey: uuid(request.idempotencyKey, "EditRequestV1.idempotencyKey"),
    parentRevisionHash: sha256(
      request.parentRevisionHash,
      "EditRequestV1.parentRevisionHash",
    ),
    workflow: enumValue(
      request.workflow,
      ["cut-first", "autopilot"] as const,
      "EditRequestV1.workflow",
    ),
    rawIntent: stringValue(request.rawIntent, "EditRequestV1.rawIntent", 100_000),
    submittedAt: isoDate(request.submittedAt, "EditRequestV1.submittedAt"),
    clauses,
  };
}

export function committedRequest(
  request: EditRequestV1,
  clauseIds: ReadonlySet<string>,
): EditRequestV1 {
  const parsed = parseEditRequestV1(request);
  const indexed = clauseById(parsed.clauses);
  for (const clauseId of clauseIds) {
    if (!indexed.has(clauseId)) throw new Error(`batch references unknown clause ${clauseId}`);
  }
  return { ...parsed, clauses: commitClauseStates(parsed.clauses, clauseIds) };
}
