import { parseEditRequestV1, type EditRequestV1 } from "./edit-request";
import { parseTreatmentOperationV1 } from "./treatment-operation";
import type { TreatmentOperationV1 } from "./treatment-operation-types";
import { exactKeys, objectValue, sha256, stringValue, uuid } from "./validation";

export interface TreatmentClauseBindingV1 {
  clauseId: string; operationId: string; disposition: "treatment-only";
  action: TreatmentOperationV1;
}
export interface TreatmentHandoffSubmissionV1 {
  schemaVersion: 1; operation: "admit-post-cut-treatment";
  expectedToken: string; expectedJournalHash: string; cutDecisionHash: string;
  request: EditRequestV1; bindings: TreatmentClauseBindingV1[];
  confirmation: { preservesAcceptedCut: true; matchesRequestedTreatment: true };
}

/** Typed compiler output seam, not an NLP semantic oracle or fulfillment receipt. */
function clauseBinding(value: unknown): TreatmentClauseBindingV1 {
  const row = objectValue(value, "TreatmentClauseBindingV1");
  const keys = ["clauseId", "operationId", "disposition", "action"];
  exactKeys(row, keys, keys, "TreatmentClauseBindingV1");
  if (row.disposition !== "treatment-only") throw new Error("Cut-affecting or unresolved clauses require a separate cut decision");
  return { clauseId: uuid(row.clauseId, "clauseId"), operationId: uuid(row.operationId, "operationId"),
    disposition: "treatment-only", action: parseTreatmentOperationV1(row.action) };
}

/** Authorized raw intake may contain unsupported intent, but not an unchecked confirmation. */
export function parseTreatmentIntakeV1(value: unknown) {
  const row = objectValue(value, "TreatmentHandoffSubmissionV1");
  const keys = ["schemaVersion", "operation", "expectedToken", "expectedJournalHash", "cutDecisionHash",
    "request", "bindings", "confirmation"];
  exactKeys(row, keys, keys, "TreatmentHandoffSubmissionV1");
  if (row.schemaVersion !== 1 || row.operation !== "admit-post-cut-treatment") throw new Error("Unsupported treatment handoff operation");
  stringValue(row.expectedToken, "expectedToken", 200); sha256(row.expectedJournalHash, "expectedJournalHash");
  sha256(row.cutDecisionHash, "cutDecisionHash");
  const request = parseEditRequestV1(row.request);
  if (request.workflow !== "cut-first" || request.clauses.length > 64 || !Array.isArray(row.bindings)
      || row.bindings.length !== request.clauses.length) throw new Error("Every guided treatment clause needs one explicit binding (maximum 64)");
  const confirmation = objectValue(row.confirmation, "confirmation");
  const flags = ["preservesAcceptedCut", "matchesRequestedTreatment"];
  exactKeys(confirmation, flags, flags, "confirmation");
  if (!flags.every((key) => confirmation[key] === true)) throw new Error("Treatment-only disposition needs explicit confirmation; it proves no execution");
  for (const value of row.bindings) {
    const binding = objectValue(value, "raw treatment binding"), keys = ["clauseId", "operationId", "disposition", "action"];
    exactKeys(binding, keys, keys, "raw treatment binding");
    uuid(binding.clauseId, "clauseId"); uuid(binding.operationId, "operationId"); objectValue(binding.action, "action");
    if (binding.disposition !== "treatment-only") throw new Error("Treatment intake requires explicit treatment-only disposition");
  }
  return { ...row, request, bindings: row.bindings } as Record<string, unknown> & { request: EditRequestV1; bindings: unknown[] };
}

export function parseTreatmentHandoffSubmissionV1(value: unknown): TreatmentHandoffSubmissionV1 {
  const row = parseTreatmentIntakeV1(value), { request } = row;
  const bindings = row.bindings.map(clauseBinding);
  if (new Set(bindings.map((item) => item.clauseId)).size !== bindings.length
      || new Set(bindings.map((item) => item.operationId)).size !== bindings.length) throw new Error("Treatment bindings must be unique");
  const ids = new Set(bindings.map((item) => item.clauseId));
  if (request.clauses.some((clause) => clause.state !== "compiled" || clause.blockingClauseIds.length
      || !ids.has(clause.clauseId))) throw new Error("Pending, unsupported, cut-affecting, or unresolved treatment clauses block admission");
  return { ...row, request, bindings } as unknown as TreatmentHandoffSubmissionV1;
}

/** Machine-readable intake diagnostic can retain the complete raw request on rejection. */
export function treatmentAdmissionScope() {
  return { scope: "compiled-treatment-intent-only-not-executed-or-approved" as const,
    available: false as const, reason: "Opening preview and body continuation are not connected",
    semanticCompilerRequired: true as const, unsupportedActions: ["music", "caption-policy", "density", "cut-change"] };
}
