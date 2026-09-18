import { exactKeys, objectValue, sha256, uuid } from "./validation";

/** Admission owns a durable fence only. No installed worker or recovery capability is implied. */
export interface GuidedBodyExecutionClaimV1 {
  schemaVersion: 1; kind: "guided-body-execution-claim";
  scope: "private-body-admission-not-execution-or-approval";
  requestId: string; executionId: string; beforeJournalHash: string;
  heldInputHash: string; budgetAdmissionHash: string; budgetPrecommitHash: string;
  clockHash: string; generationStartedAt: string; createdAt: string;
  executable: false; workerState: "not-installed"; bodyGenerated: false; deliveryApproved: false;
}

function timestamp(value: unknown): string {
  if (typeof value !== "string" || !Number.isSafeInteger(Date.parse(value))
      || new Date(value).toISOString() !== value) throw new Error("Body claim timestamp is malformed");
  return value;
}

/** Closed metadata cannot be promoted into rendering or approval by adding success flags. */
export function parseGuidedBodyExecutionClaim(value: unknown): GuidedBodyExecutionClaimV1 {
  const row = objectValue(value, "body execution claim");
  const keys = ["schemaVersion", "kind", "scope", "requestId", "executionId", "beforeJournalHash", "heldInputHash",
    "budgetAdmissionHash", "budgetPrecommitHash", "clockHash", "generationStartedAt", "createdAt",
    "executable", "workerState", "bodyGenerated", "deliveryApproved"];
  exactKeys(row, keys, keys, "body execution claim");
  if (row.schemaVersion !== 1 || row.kind !== "guided-body-execution-claim"
      || row.scope !== "private-body-admission-not-execution-or-approval" || row.executable !== false
      || row.workerState !== "not-installed" || row.bodyGenerated !== false || row.deliveryApproved !== false) {
    throw new Error("Body claim grants no worker, body generation or delivery approval");
  }
  uuid(row.requestId, "body requestId"); uuid(row.executionId, "body executionId");
  for (const key of ["beforeJournalHash", "heldInputHash", "budgetAdmissionHash", "budgetPrecommitHash", "clockHash"]) sha256(row[key], key);
  if (timestamp(row.createdAt) < timestamp(row.generationStartedAt)) throw new Error("Body claim predates its original clock");
  return row as unknown as GuidedBodyExecutionClaimV1;
}

/** Stable single-edge message is part of the exact journal transition, not presentation-only copy. */
export const BODY_CLAIM_MESSAGE = "Private body admission is fenced. No body worker or recovery command is installed; no body or delivery is approved.";
