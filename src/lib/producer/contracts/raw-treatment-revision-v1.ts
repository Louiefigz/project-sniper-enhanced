import { exactKeys, objectValue, sha256 } from "./validation";
import { parseRawTreatmentSubmissionV1, type RawTreatmentSubmissionV1 } from "./raw-treatment-v1";

/** Explicit complete replacement text only. Accepted intent, cut and source are not editable here. */
export interface RawTreatmentRevisionSubmissionV1 extends Omit<RawTreatmentSubmissionV1, "operation"> {
  operation: "revise-post-cut-treatment";
  supersession: "replace-complete-prior-brief";
  parentAdmissionHash: string;
  supersedesRequestHash: string;
}

export function parseRawTreatmentRevisionSubmissionV1(value: unknown): RawTreatmentRevisionSubmissionV1 {
  const row = objectValue(value, "RawTreatmentRevisionSubmissionV1");
  const keys = ["schemaVersion", "operation", "requestId", "idempotencyKey", "expectedToken", "expectedJournalHash",
    "cutDecisionHash", "parentRevisionHash", "rawIntent", "supersession", "parentAdmissionHash", "supersedesRequestHash"];
  exactKeys(row, keys, keys, "RawTreatmentRevisionSubmissionV1");
  if (row.operation !== "revise-post-cut-treatment" || row.supersession !== "replace-complete-prior-brief") {
    throw new Error("A treatment revision must explicitly replace the complete prior brief");
  }
  const { supersession, parentAdmissionHash, supersedesRequestHash, ...base } = row;
  const parsed = parseRawTreatmentSubmissionV1({ ...base, operation: "propose-post-cut-treatment" });
  return { ...parsed, operation: "revise-post-cut-treatment", supersession,
    parentAdmissionHash: sha256(parentAdmissionHash, "parentAdmissionHash"),
    supersedesRequestHash: sha256(supersedesRequestHash, "supersedesRequestHash") };
}

export type RawTreatmentRequest = RawTreatmentSubmissionV1 | RawTreatmentRevisionSubmissionV1;
