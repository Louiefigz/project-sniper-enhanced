/** Source-color result transport only. Parsing grants no public activation, execution or evidence read. */
import { exactKeys, objectValue, sha256, uuid } from "./validation";
import { openingAbsolutePath } from "./guided-opening-media-v1";
import { parseBoundedJson } from "./bounded-json";

export interface SourceColorMediaEvidenceRef {
  path: string; sha256: string; sizeBytes: number; receiptHash: string;
}
interface SourceColorCompletionIdentity {
  schemaVersion: 2; executionId: string; inputSha256: string; executionInputHash: string;
  receiptPath: string; receiptSha256: string; receiptHash: string; sourceColorEvidence: SourceColorMediaEvidenceRef;
  openingApproved: false; deliveryApproved: false;
}
export interface GuidedOpeningMediaCompletionV2 extends SourceColorCompletionIdentity {
  kind: "guided-opening-media-completion"; status: "complete"; executionClaimSha256: string;
}
export interface GuidedOpeningMediaReadbackV2 extends SourceColorCompletionIdentity {
  kind: "guided-opening-media-readback"; status: "verified"; claimSha256: string;
  scope: "exact-source-color-held-private-media-not-opening-or-delivery-approval";
  elapsedMs: number; stages: Array<{ stage: string; status: "complete"; elapsedMs: number }>;
  sourceColorRecordsReplayed: true; basePictureConsumptionVerified: true;
  gamutMeasured: false; gradeApplied: false; colorQualified: false;
  processGroupAndDockerCleanup: "requires-separate-owned-server-observation";
  currentJournalAndLease: "requires-separate-owned-server-observation";
}

const COMMON = ["schemaVersion", "executionId", "inputSha256", "executionInputHash", "receiptPath", "receiptSha256",
  "receiptHash", "sourceColorEvidence", "openingApproved", "deliveryApproved"];
export const SOURCE_COLOR_READBACK_STAGES = ["held-result", "held-claim", "current-input-and-sources", "exact-profile-and-frames",
  "current-code-and-tools", "source-color-original-observation-replay", "held-whole-master-and-excerpts",
  "source-color-base-consumption-readback", "exact-graphic-artifacts", "actual-range-media-readback", "final-source-result-recheck"] as const;

function common(row: Record<string, unknown>, extra: string[]): void {
  const keys = [...COMMON, ...extra];
  exactKeys(row, keys, keys, "source-color opening result");
  uuid(row.executionId, "executionId"); openingAbsolutePath(row.receiptPath);
  for (const key of ["inputSha256", "executionInputHash", "receiptSha256", "receiptHash"]) sha256(row[key], key);
  if (row.schemaVersion !== 2 || row.openingApproved !== false || row.deliveryApproved !== false
      || !(row.receiptPath as string).endsWith("/media-result.json")) throw new Error("Source-color result must retain its exact private schema2 role");
  evidenceReference(row.sourceColorEvidence, row.receiptPath as string);
}

function evidenceReference(value: unknown, receiptPath: string): void {
  const row = objectValue(value, "source-color evidence reference"), keys = ["path", "sha256", "sizeBytes", "receiptHash"];
  exactKeys(row, keys, keys, "source-color evidence reference"); openingAbsolutePath(row.path);
  sha256(row.sha256, "source-color evidence raw SHA"); sha256(row.receiptHash, "source-color evidence semantic SHA");
  const expected = receiptPath.slice(0, -"media-result.json".length) + "source-color-evidence.json";
  if (row.path !== expected || !Number.isSafeInteger(row.sizeBytes) || Number(row.sizeBytes) < 1
      || Number(row.sizeBytes) > 16 * 1024 * 1024) throw new Error("Source-color evidence requires the fixed bounded sibling artifact");
}

/** Shape only: identities must come from the actual journal-bound stopped V3 source-color process. */
export function parseSourceColorOpeningCompletion(stdout: string): GuidedOpeningMediaCompletionV2 {
  const row = objectValue(parseBoundedJson(stdout, "Source-color completion"), "source-color opening completion");
  common(row, ["kind", "status", "executionClaimSha256"]); sha256(row.executionClaimSha256, "executionClaimSha256");
  if (row.kind !== "guided-opening-media-completion" || row.status !== "complete") throw new Error("Source-color worker did not return complete schema2 evidence");
  return row as unknown as GuidedOpeningMediaCompletionV2;
}

function stages(row: Record<string, unknown>): void {
  if (!Number.isSafeInteger(row.elapsedMs) || Number(row.elapsedMs) < 0 || Number(row.elapsedMs) > 1_500_000
      || !Array.isArray(row.stages) || row.stages.length !== SOURCE_COLOR_READBACK_STAGES.length) {
    throw new Error("Source-color readback timing or stage coverage is incomplete");
  }
  let total = 0;
  row.stages.forEach((value, index) => {
    const stage = objectValue(value, "source-color readback stage"), keys = ["stage", "status", "elapsedMs"];
    exactKeys(stage, keys, keys, "source-color readback stage");
    if (stage.stage !== SOURCE_COLOR_READBACK_STAGES[index] || stage.status !== "complete" || !Number.isSafeInteger(stage.elapsedMs)
        || Number(stage.elapsedMs) < 0 || Number(stage.elapsedMs) > Number(row.elapsedMs)) throw new Error("Source-color readback stage is failed, reordered or unbounded");
    total += Number(stage.elapsedMs);
  });
  // Sequential stages and total are independently rounded; this permits rounding, not renewed work time.
  const roundingTolerance = Math.ceil(SOURCE_COLOR_READBACK_STAGES.length / 2);
  if (total > Number(row.elapsedMs) + roundingTolerance) throw new Error("Source-color readback stage sum exceeds its actual elapsed work");
}

/** Shape only: current journal, cleanup and the actual owned read invocation remain separately required. */
export function parseSourceColorOpeningReadback(stdout: string): GuidedOpeningMediaReadbackV2 {
  const row = objectValue(parseBoundedJson(stdout, "Source-color readback"), "source-color opening readback");
  common(row, ["kind", "status", "scope", "claimSha256", "elapsedMs", "stages", "sourceColorRecordsReplayed",
    "basePictureConsumptionVerified", "gamutMeasured", "gradeApplied", "colorQualified", "processGroupAndDockerCleanup", "currentJournalAndLease"]);
  sha256(row.claimSha256, "claimSha256");
  if (row.kind !== "guided-opening-media-readback" || row.status !== "verified"
      || row.scope !== "exact-source-color-held-private-media-not-opening-or-delivery-approval"
      || row.sourceColorRecordsReplayed !== true || row.basePictureConsumptionVerified !== true
      || row.gamutMeasured !== false || row.gradeApplied !== false || row.colorQualified !== false
      || row.processGroupAndDockerCleanup !== "requires-separate-owned-server-observation"
      || row.currentJournalAndLease !== "requires-separate-owned-server-observation") throw new Error("Source-color readback role, coverage or unapproved scope differs");
  stages(row);
  return row as unknown as GuidedOpeningMediaReadbackV2;
}
