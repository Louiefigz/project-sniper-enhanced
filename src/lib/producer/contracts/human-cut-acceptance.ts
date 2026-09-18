import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { parseCutApprovalRequest, type CutApprovalRequestV1 } from "./cut-approval-request";

export interface HumanCutSubmissionV1 {
  schemaVersion: 1; operation: "accept"; idempotencyKey: string; expectedToken: string;
  requestHash: string; executionKey: string; receiptHash: string; mediaSha256: string;
  attestation: { watched: true; listened: true; acceptsExactCut: true; acknowledgesUnfinished: true };
}
export interface HumanCutRetryV1 {
  schemaVersion: 1; operation: "retry-continuation"; acceptanceHash: string; requestHash: string;
}
export interface HumanCutAcceptancePointer { acceptanceHash: string; activationHash?: string }
export interface HumanCutActivationV1 {
  schemaVersion: 1; kind: "human-cut-activation"; scope: "human-cut-only-not-delivery";
  producerDir: string; acceptanceHash: string; verifyingJobHash: string;
  decisionHash: string; executionId: string; executionStartHash: string;
  waitStartedAt: string; waitStoppedAt: string; verificationStartedAt: string;
  activationRecordedAt: string;
}
export interface HumanCutAcceptanceAttempt {
  idempotencyKey: string; executionId: string; decisionHash: string;
  receivedAt: string; startedAt: string; state: "verifying" | "failed";
  completedAt: string | null; error: string | null;
}
export interface HumanCutAuthorityContext {
  schemaVersion: 1; qualityPolicyVersion: 1; manifestHash: string;
  operatorIntentDigest: string; transcriptDigest: string; referenceDigest: string; pipelineDigest: string;
}
export interface HumanCutAcceptanceV1 {
  schemaVersion: 1; kind: "human-cut-acceptance"; policyVersion: 1;
  scope: "human-cut-only-not-delivery"; actor: "local-operator";
  producerDir: string; decision: HumanCutSubmissionV1; decisionHash: string;
  originalJobToken: string; originalJobHash: string; acceptedContextHash: string;
  continuationContextHash: string; request: CutApprovalRequestV1;
  authorityContext: HumanCutAuthorityContext;
  preview: { executionKey: string; receiptHash: string; mediaSha256: string; runId: string;
    previewAttempt: number; manifestHash: string; sourceSetDigest: string; sourceSetReceiptHash: string;
    toolchainHash: string; audioClockHash: string };
  sourceVerification: "fresh-admitted-bytes-passed";
  waitStartedAt: string; submittedAt: string; verificationStartedAt: string;
  verifiedAt: string; acceptedAt: string; verificationExecutionId: string;
  continuationToken: string; continuationAttempt: number;
}

const SHA = /^[a-f0-9]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function closed(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).sort().join(",") !== [...keys].sort().join(",")) {
    throw new Error("Human cut acceptance has unknown or missing fields");
  }
  return value as Record<string, unknown>;
}
function hash(value: unknown): value is string { return typeof value === "string" && SHA.test(value); }
function uuid(value: unknown): value is string { return typeof value === "string" && UUID.test(value); }
function token(value: unknown): value is string { return typeof value === "string" && value.length > 0 && value.length <= 200; }
function positive(value: unknown): value is number { return Number.isSafeInteger(value) && Number(value) > 0 && Number(value) <= 10000; }
function timestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value)) && new Date(value).toISOString() === value;
}

/** An explicit human attestation; never infer acceptance from playback telemetry. */
export function parseHumanCutSubmission(value: unknown): HumanCutSubmissionV1 {
  const row = closed(value, ["schemaVersion", "operation", "idempotencyKey", "expectedToken", "requestHash",
    "executionKey", "receiptHash", "mediaSha256", "attestation"]);
  const attestation = closed(row.attestation, ["watched", "listened", "acceptsExactCut", "acknowledgesUnfinished"]);
  if (row.schemaVersion !== 1 || row.operation !== "accept" || !uuid(row.idempotencyKey)
      || !token(row.expectedToken) || ![row.requestHash, row.executionKey, row.receiptHash, row.mediaSha256].every(hash)
      || !Object.values(attestation).every((item) => item === true)) throw new Error("Human cut acceptance submission is invalid");
  return row as unknown as HumanCutSubmissionV1;
}

export function parseHumanCutRetry(value: unknown): HumanCutRetryV1 {
  const row = closed(value, ["schemaVersion", "operation", "acceptanceHash", "requestHash"]);
  if (row.schemaVersion !== 1 || row.operation !== "retry-continuation" || !hash(row.acceptanceHash)
      || !hash(row.requestHash)) throw new Error("Human cut continuation retry is invalid");
  return row as unknown as HumanCutRetryV1;
}

export function parseHumanCutAcceptancePointer(value: unknown): HumanCutAcceptancePointer {
  const keys = value && typeof value === "object" && Object.hasOwn(value, "activationHash")
    ? ["acceptanceHash", "activationHash"] : ["acceptanceHash"];
  const row = closed(value, keys);
  if (!hash(row.acceptanceHash) || (keys.length === 2 && !hash(row.activationHash))) {
    throw new Error("Human cut acceptance pointer is invalid");
  }
  return row as unknown as HumanCutAcceptancePointer;
}

/** A separately journal-activated execution receipt; it never reseals the original decision. */
export function parseHumanCutActivation(value: unknown): HumanCutActivationV1 {
  const row = closed(value, ["schemaVersion", "kind", "scope", "producerDir", "acceptanceHash", "verifyingJobHash",
    "decisionHash", "executionId", "executionStartHash", "waitStartedAt", "waitStoppedAt", "verificationStartedAt", "activationRecordedAt"]);
  const clock = [row.waitStartedAt, row.waitStoppedAt, row.verificationStartedAt, row.activationRecordedAt];
  if (row.schemaVersion !== 1 || row.kind !== "human-cut-activation" || row.scope !== "human-cut-only-not-delivery"
      || typeof row.producerDir !== "string" || !row.producerDir.startsWith("/") || row.producerDir.length > 4096
      || ![row.acceptanceHash, row.verifyingJobHash, row.decisionHash, row.executionStartHash].every(hash)
      || !uuid(row.executionId) || !clock.every(timestamp)
      || clock.some((at, index) => index > 0 && String(at) < String(clock[index - 1]))) {
    throw new Error("Human cut activation is malformed");
  }
  return row as unknown as HumanCutActivationV1;
}

export function parseHumanCutAcceptanceAttempt(value: unknown): HumanCutAcceptanceAttempt {
  const row = closed(value, ["idempotencyKey", "executionId", "decisionHash", "receivedAt", "startedAt", "state", "completedAt", "error"]);
  if (!uuid(row.idempotencyKey) || !uuid(row.executionId) || !hash(row.decisionHash)
      || !timestamp(row.receivedAt) || !timestamp(row.startedAt) || row.startedAt < row.receivedAt
      || (row.state !== "verifying" && row.state !== "failed")
      || (row.state === "verifying" && (row.completedAt !== null || row.error !== null))
      || (row.state === "failed" && (!timestamp(row.completedAt) || row.completedAt < row.startedAt
        || typeof row.error !== "string" || !row.error || row.error.length > 1000))) {
    throw new Error("Human cut acceptance attempt is invalid");
  }
  return row as unknown as HumanCutAcceptanceAttempt;
}

function parseAuthority(value: unknown): HumanCutAuthorityContext {
  const row = closed(value, ["schemaVersion", "qualityPolicyVersion", "manifestHash", "operatorIntentDigest",
    "transcriptDigest", "referenceDigest", "pipelineDigest"]);
  if (row.schemaVersion !== 1 || row.qualityPolicyVersion !== 1
      || !Object.entries(row).filter(([key]) => key.endsWith("Hash") || key.endsWith("Digest")).every(([, item]) => hash(item))) {
    throw new Error("Human cut acceptance authority context is invalid");
  }
  return row as unknown as HumanCutAuthorityContext;
}

function parsePreview(value: unknown): HumanCutAcceptanceV1["preview"] {
  const row = closed(value, ["executionKey", "receiptHash", "mediaSha256", "runId", "previewAttempt", "manifestHash",
    "sourceSetDigest", "sourceSetReceiptHash", "toolchainHash", "audioClockHash"]);
  if (!token(row.runId) || !positive(row.previewAttempt)
      || !Object.entries(row).filter(([key]) => !["runId", "previewAttempt"].includes(key)).every(([, item]) => hash(item))) {
    throw new Error("Human cut acceptance preview identity is invalid");
  }
  return row as unknown as HumanCutAcceptanceV1["preview"];
}

/** Closed immutable fact parser; file integrity and activation by a job reference are separate. */
export function parseHumanCutAcceptance(value: unknown): HumanCutAcceptanceV1 {
  const row = closed(value, ["schemaVersion", "kind", "policyVersion", "scope", "actor", "producerDir", "decision", "decisionHash",
    "originalJobToken", "originalJobHash", "acceptedContextHash", "continuationContextHash", "request", "authorityContext", "preview",
    "sourceVerification", "waitStartedAt", "submittedAt", "verificationStartedAt", "verifiedAt", "acceptedAt",
    "verificationExecutionId", "continuationToken", "continuationAttempt"]);
  const decision = parseHumanCutSubmission(row.decision), request = parseCutApprovalRequest(row.request);
  const authority = parseAuthority(row.authorityContext), preview = parsePreview(row.preview);
  const clock = [row.waitStartedAt, row.submittedAt, row.verificationStartedAt, row.verifiedAt, row.acceptedAt];
  if (row.schemaVersion !== 1 || row.kind !== "human-cut-acceptance" || row.policyVersion !== 1
      || row.scope !== "human-cut-only-not-delivery" || row.actor !== "local-operator"
      || typeof row.producerDir !== "string" || !row.producerDir.startsWith("/") || row.producerDir.length > 4096
      || ![row.decisionHash, row.originalJobHash, row.acceptedContextHash, row.continuationContextHash].every(hash)
      || !token(row.originalJobToken) || !uuid(row.continuationToken) || !uuid(row.verificationExecutionId)
      || !positive(row.continuationAttempt) || row.continuationAttempt !== preview.previewAttempt + 1
      || row.continuationToken === row.originalJobToken || row.sourceVerification !== "fresh-admitted-bytes-passed"
      || !clock.every(timestamp) || clock.some((at, index) => index > 0 && String(at) < String(clock[index - 1]))) {
    throw new Error("Human cut acceptance fact is malformed");
  }
  if (canonicalJsonSha256(decision) !== row.decisionHash || decision.expectedToken !== row.originalJobToken
      || decision.requestHash !== request.requestHash || decision.executionKey !== preview.executionKey
      || decision.receiptHash !== preview.receiptHash || decision.mediaSha256 !== preview.mediaSha256
      || authority.manifestHash !== preview.manifestHash) throw new Error("Human cut acceptance fact bindings disagree");
  return row as unknown as HumanCutAcceptanceV1;
}

export function validHumanCutAcceptancePointer(value: unknown): boolean {
  try { parseHumanCutAcceptancePointer(value); return true; } catch { return false; }
}
export function validHumanCutAcceptanceAttempt(value: unknown): boolean {
  try { parseHumanCutAcceptanceAttempt(value); return true; } catch { return false; }
}
