import { exactKeys, objectValue, sha256, stringValue, uuid } from "./validation";

export const GUIDED_OPENING_SCOPE = "opening-preparation-not-playback-approval-body-or-delivery";
export const OPENING_BLOCKER_CODES = ["opening-renderer-unavailable", "legacy-presentation-unbound",
  "inherited-graphics-unbound", "caption-rendering-unqualified", "audio-treatment-unqualified",
  "repeated-source-execution-unqualified"] as const;
export type OpeningBlockerCode = typeof OPENING_BLOCKER_CODES[number];
export interface PrepareGuidedOpeningV1 {
  schemaVersion: 1; operation: "prepare-guided-opening"; idempotencyKey: string;
  expectedToken: string; expectedJournalHash: string; proposalReadinessHash: string; treatmentDraftRevisionHash: string;
}
export interface RecoverGuidedOpeningCleanupV1 {
  schemaVersion: 1; operation: "recover-guided-opening-cleanup";
  expectedToken: string; expectedJournalHash: string; claimHash: string;
}
export interface RecoverCompletedOpeningCleanupV1 {
  schemaVersion: 1; operation: "recover-completed-guided-opening-cleanup";
  expectedToken: string; expectedJournalHash: string; claimHash: string;
  cleanupAttemptId: string; preparedSha256: string;
}
export interface OpeningFrameRange { startFrame: number; endFrameExclusive: number }
export interface OpeningPreparationReceiptV1 {
  schemaVersion: 1; kind: "guided-opening-preparation"; scope: typeof GUIDED_OPENING_SCOPE;
  submission: PrepareGuidedOpeningV1; beforeJournalHash: string; executionId: string; executionStartHash: string;
  inputHash: string; implementationHash: string; frameBindingsHash: string | null;
  clockHash: string; generationStartedAt: string; createdAt: string;
  state: "unsupported-before-render"; blockerCodes: OpeningBlockerCode[];
  sourceObservation: "not-run-known-unsupported"; renderBudget: "not-admitted-renderer-unavailable";
  media: null; executable: false; approved: false;
}

export function parsePrepareGuidedOpening(value: unknown): PrepareGuidedOpeningV1 {
  const row = objectValue(value, "guided opening request");
  const keys = ["schemaVersion", "operation", "idempotencyKey", "expectedToken", "expectedJournalHash", "proposalReadinessHash", "treatmentDraftRevisionHash"];
  exactKeys(row, keys, keys, "guided opening request");
  if (row.schemaVersion !== 1 || row.operation !== "prepare-guided-opening") throw new Error("Unsupported opening action");
  uuid(row.idempotencyKey, "opening idempotencyKey"); stringValue(row.expectedToken, "expectedToken", 200);
  for (const name of ["expectedJournalHash", "proposalReadinessHash", "treatmentDraftRevisionHash"]) sha256(row[name], name);
  return row as unknown as PrepareGuidedOpeningV1;
}

/** Exact current cleanup checkpoint only; no render retry, reset clock or approval flags are accepted. */
export function parseRecoverGuidedOpeningCleanup(value: unknown): RecoverGuidedOpeningCleanupV1 {
  const row = objectValue(value, "guided opening cleanup recovery request");
  const keys = ["schemaVersion", "operation", "expectedToken", "expectedJournalHash", "claimHash"];
  exactKeys(row, keys, keys, "guided opening cleanup recovery request");
  if (row.schemaVersion !== 1 || row.operation !== "recover-guided-opening-cleanup") throw new Error("Unsupported opening cleanup recovery action");
  stringValue(row.expectedToken, "expectedToken", 200);
  sha256(row.expectedJournalHash, "expectedJournalHash"); sha256(row.claimHash, "claimHash");
  return row as unknown as RecoverGuidedOpeningCleanupV1;
}

/** Explicit existing completed attempt only; never a new UUID, native retry, clock or approval. */
export function parseRecoverCompletedOpeningCleanup(value: unknown): RecoverCompletedOpeningCleanupV1 {
  const row = objectValue(value, "completed opening cleanup recovery request");
  const keys = ["schemaVersion", "operation", "expectedToken", "expectedJournalHash", "claimHash", "cleanupAttemptId", "preparedSha256"];
  exactKeys(row, keys, keys, "completed opening cleanup recovery request");
  if (row.schemaVersion !== 1 || row.operation !== "recover-completed-guided-opening-cleanup"
      || uuid(row.cleanupAttemptId, "cleanupAttemptId")[14] !== "4") throw new Error("Unsupported completed cleanup recovery action");
  stringValue(row.expectedToken, "expectedToken", 200);
  for (const name of ["expectedJournalHash", "claimHash", "preparedSha256"]) sha256(row[name], name);
  return row as unknown as RecoverCompletedOpeningCleanupV1;
}

export function parseOpeningFrameRange(value: unknown, totalFrames: number): OpeningFrameRange {
  const row = objectValue(value, "opening frame range");
  exactKeys(row, ["startFrame", "endFrameExclusive"], ["startFrame", "endFrameExclusive"], "opening frame range");
  if (!Number.isSafeInteger(totalFrames) || totalFrames <= 0 || !Number.isSafeInteger(row.startFrame) || Number(row.startFrame) < 0
      || !Number.isSafeInteger(row.endFrameExclusive) || Number(row.endFrameExclusive) <= Number(row.startFrame)
      || Number(row.endFrameExclusive) > totalFrames) throw new Error("Opening frame range is outside its exact program");
  return row as unknown as OpeningFrameRange;
}

/** The initial adapter has no success/media shape: tests cannot inject a fake qualified preview. */
export function parseOpeningPreparationReceipt(value: unknown): OpeningPreparationReceiptV1 {
  const row = objectValue(value, "opening preparation receipt");
  const keys = ["schemaVersion", "kind", "scope", "submission", "beforeJournalHash", "executionId", "executionStartHash", "inputHash",
    "implementationHash", "frameBindingsHash", "clockHash", "generationStartedAt", "createdAt", "state", "blockerCodes",
    "sourceObservation", "renderBudget", "media", "executable", "approved"];
  exactKeys(row, keys, keys, "opening preparation receipt");
  const submission = parsePrepareGuidedOpening(row.submission); uuid(row.executionId, "opening executionId");
  for (const key of ["beforeJournalHash", "executionStartHash", "inputHash", "implementationHash", "clockHash"]) sha256(row[key], key);
  if (row.frameBindingsHash !== null) sha256(row.frameBindingsHash, "frameBindingsHash");
  const codes = row.blockerCodes;
  if (row.schemaVersion !== 1 || row.kind !== "guided-opening-preparation" || row.scope !== GUIDED_OPENING_SCOPE
      || row.beforeJournalHash !== submission.expectedJournalHash || row.state !== "unsupported-before-render"
      || row.sourceObservation !== "not-run-known-unsupported" || row.renderBudget !== "not-admitted-renderer-unavailable"
      || row.media !== null || row.executable !== false || row.approved !== false || !Array.isArray(codes)
      || codes.length > OPENING_BLOCKER_CODES.length || new Set(codes).size !== codes.length
      || !codes.includes("opening-renderer-unavailable") || codes.some((code) => !OPENING_BLOCKER_CODES.includes(code))) {
    throw new Error("Opening preparation cannot claim a renderer, media or approval that does not exist");
  }
  for (const key of ["generationStartedAt", "createdAt"]) {
    const value = stringValue(row[key], key, 30);
    if (!Number.isFinite(Date.parse(value)) || new Date(value).toISOString() !== value) throw new Error("Opening receipt timestamp is invalid");
  }
  if (String(row.createdAt) < String(row.generationStartedAt)) throw new Error("Opening receipt predates the original brief");
  return { ...row, submission } as unknown as OpeningPreparationReceiptV1;
}
