import { exactKeys, objectValue, sha256, stringValue, uuid } from "./validation";

/** Explicit local-operator approval of the exact selected opening media. Never body or delivery approval. */
export const GUIDED_OPENING_APPROVAL_SCOPE = "human-opening-approval-not-body-or-delivery-approval" as const;
export const GUIDED_OPENING_APPROVAL_ATTESTATIONS = ["watchedOpening", "watchedBodyTransition", "listened", "approvesOpening", "understandsBodyPending"] as const;

export interface GuidedOpeningApprovalSubmissionV1 {
  schemaVersion: 1; operation: "approve-guided-opening"; idempotencyKey: string;
  expectedToken: string; expectedJournalHash: string; selectionHash: string;
  coreMediaSha256: string; reviewMediaSha256: string;
  attestation: Record<typeof GUIDED_OPENING_APPROVAL_ATTESTATIONS[number], true>;
}

export function parseGuidedOpeningApprovalSubmission(value: unknown): GuidedOpeningApprovalSubmissionV1 {
  const row = objectValue(value, "opening approval submission");
  const keys = ["schemaVersion", "operation", "idempotencyKey", "expectedToken", "expectedJournalHash", "selectionHash",
    "coreMediaSha256", "reviewMediaSha256", "attestation"];
  exactKeys(row, keys, keys, "opening approval submission");
  if (row.schemaVersion !== 1 || row.operation !== "approve-guided-opening") throw new Error("Unsupported opening approval operation");
  uuid(row.idempotencyKey, "idempotencyKey"); stringValue(row.expectedToken, "expectedToken", 200);
  for (const key of ["expectedJournalHash", "selectionHash", "coreMediaSha256", "reviewMediaSha256"]) sha256(row[key], key);
  const attestation = objectValue(row.attestation, "opening approval attestation");
  const flags = [...GUIDED_OPENING_APPROVAL_ATTESTATIONS];
  exactKeys(attestation, flags, flags, "opening approval attestation");
  if (!flags.every((key) => attestation[key] === true)) throw new Error("Every opening approval attestation must be explicitly true");
  return row as unknown as GuidedOpeningApprovalSubmissionV1;
}

/** Display-side approval evidence: a verified pointer only, never inferred from playback or time. */
export interface GuidedOpeningApprovalDisplayV1 { approvalHash: string; approvedAt: string }
