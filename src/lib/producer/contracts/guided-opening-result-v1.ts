import { exactKeys, objectValue, sha256, uuid } from "./validation";
import { openingAbsolutePath } from "./guided-opening-media-v1";

export interface GuidedOpeningMediaCompletionV1 {
  schemaVersion: 1; kind: "guided-opening-media-completion"; status: "complete";
  executionId: string; inputSha256: string; executionInputHash: string; executionClaimSha256: string;
  receiptPath: string; receiptSha256: string; receiptHash: string; openingApproved: false; deliveryApproved: false;
}
export interface GuidedOpeningMediaReadbackV1 {
  schemaVersion: 1; kind: "guided-opening-media-readback"; status: "verified";
  scope: "exact-held-private-media-not-opening-or-delivery-approval";
  executionId: string; inputSha256: string; executionInputHash: string; claimSha256: string;
  receiptPath: string; receiptSha256: string; receiptHash: string; elapsedMs: number;
  stages: Array<{ stage: string; status: "complete"; elapsedMs: number }>;
  processGroupAndDockerCleanup: "requires-separate-owned-server-observation";
  currentJournalAndLease: "requires-separate-owned-server-observation";
  openingApproved: false; deliveryApproved: false;
}

function stdoutValue(value: string): unknown {
  if (Buffer.byteLength(value, "utf8") > 128 * 1024 || value.includes("\u0000")) throw new Error("Opening completion stdout exceeds its bound or contains unsafe bytes");
  return JSON.parse(value.trim()); // Exactly one object. No progress/last-match/duplicate-completion fallback.
}
function common(row: Record<string, unknown>, keys: string[]) {
  exactKeys(row, keys, keys, "opening completion"); uuid(row.executionId, "executionId"); openingAbsolutePath(row.receiptPath);
  for (const key of ["inputSha256", "executionInputHash", "receiptSha256", "receiptHash"]) sha256(row[key], key);
  if (row.schemaVersion !== 1 || row.openingApproved !== false || row.deliveryApproved !== false) throw new Error("Opening completion is not private unapproved evidence");
}

/** Shape only. Only a separately journal-bound actual stopped worker may supply these identities. */
export function parseOpeningMediaCompletion(stdout: string): GuidedOpeningMediaCompletionV1 {
  const row = objectValue(stdoutValue(stdout), "opening media completion");
  common(row, ["schemaVersion", "kind", "status", "executionId", "inputSha256", "executionInputHash", "executionClaimSha256",
    "receiptPath", "receiptSha256", "receiptHash", "openingApproved", "deliveryApproved"]);
  sha256(row.executionClaimSha256, "executionClaimSha256");
  if (row.kind !== "guided-opening-media-completion" || row.status !== "complete") throw new Error("Opening worker did not return its exact complete protocol");
  return row as unknown as GuidedOpeningMediaCompletionV1;
}

const READBACK_STAGES = ["held-result", "held-claim", "current-input-and-sources", "exact-profile-and-frames", "current-code-and-tools",
  "held-whole-master-and-excerpts", "exact-graphic-artifacts", "actual-range-media-readback", "final-source-result-recheck"];

/** Shape only. Reading a receipt never creates source freshness, cleanup, lease, or invocation authority. */
export function parseOpeningMediaReadback(stdout: string): GuidedOpeningMediaReadbackV1 {
  const row = objectValue(stdoutValue(stdout), "opening readback completion");
  common(row, ["schemaVersion", "kind", "status", "scope", "executionId", "inputSha256", "executionInputHash", "claimSha256",
    "receiptPath", "receiptSha256", "receiptHash", "elapsedMs", "stages", "processGroupAndDockerCleanup", "currentJournalAndLease", "openingApproved", "deliveryApproved"]);
  sha256(row.claimSha256, "claimSha256");
  if (row.kind !== "guided-opening-media-readback" || row.status !== "verified"
      || row.scope !== "exact-held-private-media-not-opening-or-delivery-approval"
      || row.processGroupAndDockerCleanup !== "requires-separate-owned-server-observation"
      || row.currentJournalAndLease !== "requires-separate-owned-server-observation"
      || !Number.isSafeInteger(row.elapsedMs) || Number(row.elapsedMs) < 0 || Number(row.elapsedMs) > 1_500_000
      || !Array.isArray(row.stages) || row.stages.length !== READBACK_STAGES.length) throw new Error("Opening readback protocol or coverage is incomplete");
  row.stages.forEach((value, index) => {
    const stage = objectValue(value, "opening readback stage"); exactKeys(stage, ["stage", "status", "elapsedMs"], ["stage", "status", "elapsedMs"], "opening readback stage");
    if (stage.stage !== READBACK_STAGES[index] || stage.status !== "complete" || !Number.isSafeInteger(stage.elapsedMs)
        || Number(stage.elapsedMs) < 0 || Number(stage.elapsedMs) > Number(row.elapsedMs)) throw new Error("Opening readback stage was failed, omitted, reordered or unbounded");
  });
  return row as unknown as GuidedOpeningMediaReadbackV1;
}
