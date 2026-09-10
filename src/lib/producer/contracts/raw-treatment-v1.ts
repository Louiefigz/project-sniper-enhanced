import { exactKeys, objectValue, sha256, stringValue, uuid } from "./validation";

/** A request for an unapproved proposal, never an attestation or executable treatment. */
export interface RawTreatmentSubmissionV1 {
  schemaVersion: 1; operation: "propose-post-cut-treatment";
  requestId: string; idempotencyKey: string;
  expectedToken: string; expectedJournalHash: string; cutDecisionHash: string; parentRevisionHash: string;
  rawIntent: string;
}

export function parseRawTreatmentSubmissionV1(value: unknown): RawTreatmentSubmissionV1 {
  const row = objectValue(value, "RawTreatmentSubmissionV1");
  const keys = ["schemaVersion", "operation", "requestId", "idempotencyKey", "expectedToken",
    "expectedJournalHash", "cutDecisionHash", "parentRevisionHash", "rawIntent"];
  exactKeys(row, keys, keys, "RawTreatmentSubmissionV1");
  if (row.schemaVersion !== 1 || row.operation !== "propose-post-cut-treatment") throw new Error("Unsupported raw treatment request");
  const rawIntent = stringValue(row.rawIntent, "rawIntent", 20_000);
  if (!rawIntent.trim() || rawIntent.length > 20_000) throw new Error("A raw treatment request must contain at most 20000 UTF-16 units of nonblank text");
  return { schemaVersion: 1, operation: "propose-post-cut-treatment",
    requestId: uuid(row.requestId, "requestId"), idempotencyKey: uuid(row.idempotencyKey, "idempotencyKey"),
    expectedToken: stringValue(row.expectedToken, "expectedToken", 200),
    expectedJournalHash: sha256(row.expectedJournalHash, "expectedJournalHash"),
    cutDecisionHash: sha256(row.cutDecisionHash, "cutDecisionHash"),
    parentRevisionHash: sha256(row.parentRevisionHash, "parentRevisionHash"), rawIntent };
}

/** Explicit retry names the already admitted raw request; it supplies no new intent. */
export interface TreatmentCompileSubmissionV1 {
  schemaVersion: 1; operation: "compile-post-cut-proposal"; idempotencyKey: string;
  expectedToken: string; expectedJournalHash: string; treatmentAdmissionHash: string;
}

export function parseTreatmentCompileSubmissionV1(value: unknown): TreatmentCompileSubmissionV1 {
  const row = objectValue(value, "TreatmentCompileSubmissionV1");
  const keys = ["schemaVersion", "operation", "idempotencyKey", "expectedToken", "expectedJournalHash", "treatmentAdmissionHash"];
  exactKeys(row, keys, keys, "TreatmentCompileSubmissionV1");
  if (row.schemaVersion !== 1 || row.operation !== "compile-post-cut-proposal") throw new Error("Unsupported treatment compile action");
  return { schemaVersion: 1, operation: "compile-post-cut-proposal", idempotencyKey: uuid(row.idempotencyKey, "idempotencyKey"),
    expectedToken: stringValue(row.expectedToken, "expectedToken", 200), expectedJournalHash: sha256(row.expectedJournalHash, "expectedJournalHash"),
    treatmentAdmissionHash: sha256(row.treatmentAdmissionHash, "treatmentAdmissionHash") };
}

/** Stable, explicit capability report; proposal creation does not enable video generation. */
export function rawTreatmentScope() {
  return { scope: "raw-treatment-request-not-executed-or-approved" as const, available: false as const,
    requiresHumanAttestation: false as const,
    reason: "Request intake and unapproved proposal only; playable opening and body continuation are not connected" };
}
