import { exactKeys, objectValue, sha256, uuid, stringValue } from "./validation";
import { parseBodyFileReference, type BodyFileReference } from "./guided-body-media-v1";
import { bodyTimestamp } from "./guided-body-activation-v1";

export interface GuidedBodyCandidateV1 {
  ok: true; state: "private-candidate-qualified"; replayed: false;
  requestId: string; executionId: string; admissionClaimHash: string; activationHash: string;
  cleanupHash: string; candidateHash: string; journalHash: string; candidate: BodyFileReference;
  bodyApproved: false; deliveryApproved: false;
}
export type BodyStatusState = "unavailable" | "admission-fenced" | "execution-owned" | "process-returned"
  | "cleanup-verified" | "private-candidate-qualified" | "failed-or-unresolved";
export interface GuidedBodyStatusV1 {
  ok: true; state: BodyStatusState; detail: string; journalHash: string;
  requestId: string | null; executionId: string | null; admissionClaimHash: string | null; activationHash: string | null;
  cleanupHash: string | null; candidateHash: string | null; candidate: BodyFileReference | null; observedAt: string;
  sourceFreshness: "not-observed-by-status"; bodyApproved: false; deliveryApproved: false;
}
export type GuidedBodyRunResult = GuidedBodyCandidateV1 | { ok: true; replayed: true; status: GuidedBodyStatusV1 };
const CANDIDATE_KEYS = ["ok", "state", "replayed", "requestId", "executionId", "admissionClaimHash", "activationHash",
  "cleanupHash", "candidateHash", "journalHash", "candidate", "bodyApproved", "deliveryApproved"];
const STATUS_KEYS = ["ok", "state", "detail", "journalHash", "requestId", "executionId", "admissionClaimHash", "activationHash",
  "cleanupHash", "candidateHash", "candidate", "observedAt", "sourceFreshness", "bodyApproved", "deliveryApproved"];

/** Schema only. A status response is last-recorded metadata, never another render or media requalification. */
export function parseGuidedBodyStatus(value: unknown): GuidedBodyStatusV1 {
  const row = objectValue(value, "body status"); exactKeys(row, STATUS_KEYS, STATUS_KEYS, "body status");
  const states: BodyStatusState[] = ["unavailable", "admission-fenced", "execution-owned", "process-returned", "cleanup-verified",
    "private-candidate-qualified", "failed-or-unresolved"];
  if (row.ok !== true || !states.includes(row.state as BodyStatusState) || row.sourceFreshness !== "not-observed-by-status"
      || row.bodyApproved !== false || row.deliveryApproved !== false) throw new Error("Body status role is invalid");
  stringValue(row.detail, "body detail", 4000); bodyTimestamp(row.observedAt); sha256(row.journalHash, "journalHash");
  for (const key of ["requestId", "executionId"]) if (row[key] !== null) uuid(row[key], key);
  for (const key of ["admissionClaimHash", "activationHash", "cleanupHash", "candidateHash"]) if (row[key] !== null) sha256(row[key], key);
  if (row.candidate !== null) parseBodyFileReference(row.candidate);
  if ((row.state === "private-candidate-qualified") !== (row.candidate !== null)
      || (row.candidate !== null && (!row.candidateHash || !row.cleanupHash || !row.activationHash || !row.admissionClaimHash))) {
    throw new Error("Body status misreports selectable private candidate metadata");
  }
  return row as unknown as GuidedBodyStatusV1;
}

/** Fresh success versus read-only replay are distinct closed replies; neither is human/delivery approval. */
export function parseGuidedBodyRunResult(value: unknown): GuidedBodyRunResult {
  const row = objectValue(value, "body run result");
  if (row.replayed === true) {
    exactKeys(row, ["ok", "replayed", "status"], ["ok", "replayed", "status"], "body replay");
    if (row.ok !== true) throw new Error("Body replay is not a valid result");
    parseGuidedBodyStatus(row.status); return row as unknown as GuidedBodyRunResult;
  }
  exactKeys(row, CANDIDATE_KEYS, CANDIDATE_KEYS, "body candidate");
  if (row.ok !== true || row.state !== "private-candidate-qualified" || row.replayed !== false
      || row.bodyApproved !== false || row.deliveryApproved !== false) throw new Error("Body candidate is not qualified private output");
  uuid(row.requestId, "requestId"); uuid(row.executionId, "executionId");
  for (const key of ["admissionClaimHash", "activationHash", "cleanupHash", "candidateHash", "journalHash"]) sha256(row[key], key);
  parseBodyFileReference(row.candidate);
  return row as unknown as GuidedBodyCandidateV1;
}
