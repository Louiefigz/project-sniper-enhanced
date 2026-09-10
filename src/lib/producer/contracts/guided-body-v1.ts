import { exactKeys, objectValue, sha256, stringValue, uuid } from "./validation";

/** Explicit continuation request only. Opening approval never implicitly submits this action. */
export interface ContinueApprovedOpeningV1 {
  schemaVersion: 1; operation: "continue-approved-opening"; idempotencyKey: string;
  expectedToken: string; expectedJournalHash: string; openingApprovalHash: string;
  selectionHash: string; proposalReadinessHash: string; treatmentDraftRevisionHash: string;
}

/** No client-selected plan, file path, renderer, deadline or approval flags. */
export function parseContinueApprovedOpening(value: unknown): ContinueApprovedOpeningV1 {
  const row = objectValue(value, "body continuation request");
  const keys = ["schemaVersion", "operation", "idempotencyKey", "expectedToken", "expectedJournalHash",
    "openingApprovalHash", "selectionHash", "proposalReadinessHash", "treatmentDraftRevisionHash"];
  exactKeys(row, keys, keys, "body continuation request");
  if (row.schemaVersion !== 1 || row.operation !== "continue-approved-opening") throw new Error("Unsupported body continuation action");
  uuid(row.idempotencyKey, "body idempotencyKey"); stringValue(row.expectedToken, "expectedToken", 200);
  for (const key of keys.slice(4)) sha256(row[key], key);
  return row as unknown as ContinueApprovedOpeningV1;
}

export const GUIDED_BODY_INPUT_SCOPE = "held-body-input-not-launch-body-readiness-or-delivery-approval" as const;
