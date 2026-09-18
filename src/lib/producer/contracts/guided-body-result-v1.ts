import { exactKeys, objectValue, sha256, uuid } from "./validation";
import { openingAbsolutePath } from "./guided-opening-media-v1";
import { parseOpeningCleanupGraphic, type OpeningCleanupGraphicV1 } from "./guided-opening-cleanup-v1";

interface BodyResultIdentity {
  executionId: string; inputSha256: string; executionActivationSha256: string;
  receiptPath: string; receiptSha256: string; receiptHash: string;
}
export interface BodyMediaCompletionV1 extends BodyResultIdentity {
  schemaVersion: 1; kind: "guided-body-media-completion"; status: "complete"; bodyApproved: false; deliveryApproved: false;
}
export interface BodyMediaReadbackV1 extends BodyResultIdentity {
  schemaVersion: 1; kind: "guided-body-media-readback"; status: "verified";
  scope: "exact-held-private-body-media-not-body-or-delivery-approval"; elapsedMs: number;
  stages: Array<{ stage: string; status: "complete"; elapsedMs: number }>;
  processGroupAndDockerCleanup: "requires-separate-owned-controller-observation";
  currentJournalAndLease: "requires-separate-owned-controller-observation"; bodyApproved: false; deliveryApproved: false;
}
export interface BodyCleanupResultV1 {
  schemaVersion: 1; kind: "guided-body-cleanup-result"; activationPath: string; activationSha256: string;
  inputSha256: string; outputRoot: string; executionId: string; cleanupVerified: true;
  graphics: OpeningCleanupGraphicV1[]; elapsedMs: number;
  stages: Array<{ stage: string; status: "complete"; elapsedMs: number }>;
  budgetScope: "separate-protected-cleanup-not-render-allowance";
  processGroupStopped: "requires-owned-controller-observation"; bodyApproved: false; deliveryApproved: false;
}
const IDENTITY_KEYS = ["executionId", "inputSha256", "executionActivationSha256", "receiptPath", "receiptSha256", "receiptHash"];
const RESULT_KEYS = ["schemaVersion", "kind", "status", ...IDENTITY_KEYS, "bodyApproved", "deliveryApproved"];
const READ_STAGES = ["body-read-control", "body-read-current-inputs", "body-read-held-result", "body-read-current-pipeline",
  "body-read-whole-base-master", "body-read-all-graphics", "body-read-final-media-and-qc", "body-read-final-revalidation"];

function parseOutput(stdout: string, maximum = 128 * 1024) {
  if (Buffer.byteLength(stdout, "utf8") > maximum || stdout.includes("\0")) throw new Error("Body output is unsafe or over its closed bound");
  return objectValue(JSON.parse(stdout.trim()), "body owned output");
}
function identity(row: Record<string, unknown>): void {
  uuid(row.executionId, "body executionId"); openingAbsolutePath(row.receiptPath);
  for (const key of ["inputSha256", "executionActivationSha256", "receiptSha256", "receiptHash"]) sha256(row[key], key);
  if (row.schemaVersion !== 1 || row.bodyApproved !== false || row.deliveryApproved !== false) throw new Error("Body output cannot grant approval");
}
function timing(row: Record<string, unknown>, names: string[], limit: number): void {
  if (!Number.isSafeInteger(row.elapsedMs) || Number(row.elapsedMs) < 0 || Number(row.elapsedMs) > limit
      || !Array.isArray(row.stages) || row.stages.length !== names.length) throw new Error("Body work timing/coverage is incomplete");
  row.stages.forEach((value, index) => {
    const stage = objectValue(value, "body timed stage");
    exactKeys(stage, ["stage", "status", "elapsedMs"], ["stage", "status", "elapsedMs"], "body timed stage");
    if (stage.stage !== names[index] || stage.status !== "complete" || !Number.isSafeInteger(stage.elapsedMs)
        || Number(stage.elapsedMs) < 0 || Number(stage.elapsedMs) > Number(row.elapsedMs)) throw new Error("Body stage proof is incomplete");
  });
}

/** Closed actual stdout only. Parsing is never process ownership, media decoding or candidate selection. */
export function parseBodyMediaCompletion(stdout: string): BodyMediaCompletionV1 {
  const row = parseOutput(stdout); exactKeys(row, RESULT_KEYS, RESULT_KEYS, "body completion"); identity(row);
  if (row.kind !== "guided-body-media-completion" || row.status !== "complete") throw new Error("Body worker did not complete");
  return row as unknown as BodyMediaCompletionV1;
}

export function parseBodyMediaReadback(stdout: string): BodyMediaReadbackV1 {
  const row = parseOutput(stdout), keys = [...RESULT_KEYS, "scope", "elapsedMs", "stages", "processGroupAndDockerCleanup", "currentJournalAndLease"];
  exactKeys(row, keys, keys, "body readback"); identity(row); timing(row, READ_STAGES, 3_300_000);
  if (row.kind !== "guided-body-media-readback" || row.status !== "verified"
      || row.scope !== "exact-held-private-body-media-not-body-or-delivery-approval"
      || row.processGroupAndDockerCleanup !== "requires-separate-owned-controller-observation"
      || row.currentJournalAndLease !== "requires-separate-owned-controller-observation") throw new Error("Body readback role is invalid");
  return row as unknown as BodyMediaReadbackV1;
}

/** Shares the exact existing armed/unarmed/container-absence shape; only the body envelope and all-row bound differ. */
export function parseBodyCleanupResult(stdout: string): BodyCleanupResultV1 {
  const row = parseOutput(stdout), keys = ["schemaVersion", "kind", "activationPath", "activationSha256", "inputSha256", "outputRoot",
    "executionId", "cleanupVerified", "graphics", "elapsedMs", "stages", "budgetScope", "processGroupStopped", "bodyApproved", "deliveryApproved"];
  exactKeys(row, keys, keys, "body cleanup"); openingAbsolutePath(row.activationPath); openingAbsolutePath(row.outputRoot);
  uuid(row.executionId, "executionId"); sha256(row.activationSha256, "activationSha256"); sha256(row.inputSha256, "inputSha256");
  if (row.schemaVersion !== 1 || row.kind !== "guided-body-cleanup-result" || row.cleanupVerified !== true
      || row.budgetScope !== "separate-protected-cleanup-not-render-allowance" || row.processGroupStopped !== "requires-owned-controller-observation"
      || row.bodyApproved !== false || row.deliveryApproved !== false || !Array.isArray(row.graphics) || row.graphics.length > 128) {
    throw new Error("Body cleanup is incomplete or has an unsupported role");
  }
  const graphics = row.graphics.map(parseOpeningCleanupGraphic), names = graphics.flatMap((item) => item.containerNames);
  if (graphics.some((item, index) => item.order !== index) || new Set(names).size !== names.length) throw new Error("Body cleanup omits or duplicates a resource");
  timing(row, ["body-cleanup-control", ...graphics.map((item) => `reconcile-graphic-${item.order}`), "body-cleanup-control-after"], 300_000);
  return row as unknown as BodyCleanupResultV1;
}
