/** Additive all-reservation cleanup shape; JSON never proves actual process or daemon ownership. */
import { exactKeys, objectValue, sha256 } from "./validation";
import { openingAbsolutePath } from "./guided-opening-media-v1";
import { parseOpeningCleanupResult, type OpeningCleanupResultV1 } from "./guided-opening-cleanup-v1";

export interface GradeBatchCleanupJob {
  containerName: string; inspections: number; removalAttempts: number; successfulRemovalResponses: number;
  lastObservation: "absent"; canonicalAbsenceProved: true;
}
export interface GradeBatchCleanupResult {
  schemaVersion: 1; kind: "grade-batch-cleanup-result";
  scope: "reserved-name-cleanup-not-process-settlement-work-or-approval";
  cleanupVerified: true; elapsedMs: number; stableAbsenceMs: number; passes: number; jobs: GradeBatchCleanupJob[];
}
export interface OpeningSourceColorCleanupEvidence {
  reservation: { path: string; sha256: string; sizeBytes: number };
  sourceColorHash: string; batch: GradeBatchCleanupResult;
}
export interface OpeningCleanupResultV2 extends Omit<OpeningCleanupResultV1, "schemaVersion"> {
  schemaVersion: 2; sourceColor: OpeningSourceColorCleanupEvidence;
}
export type CurrentOpeningCleanupResult = OpeningCleanupResultV1 | OpeningCleanupResultV2;

function exact(value: unknown, fields: string[], label: string) {
  const row = objectValue(value, label); exactKeys(row, fields, fields, label); return row;
}
function integer(value: unknown, minimum: number, maximum: number): value is number {
  return Number.isSafeInteger(value) && Number(value) >= minimum && Number(value) <= maximum;
}
function job(value: unknown, passes: number): GradeBatchCleanupJob {
  const row = exact(value, ["containerName", "inspections", "removalAttempts", "successfulRemovalResponses",
    "lastObservation", "canonicalAbsenceProved"], "grade batch cleanup job");
  if (typeof row.containerName !== "string" || !/^sniper-grade-observation-[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$/u.test(row.containerName)
      || row.inspections !== passes * 2 || row.removalAttempts !== passes
      || !integer(row.successfulRemovalResponses, 0, passes)
      || row.lastObservation !== "absent" || row.canonicalAbsenceProved !== true) {
    throw new Error("Grade batch cleanup lacks complete exact-name absence observations");
  }
  return row as unknown as GradeBatchCleanupJob;
}

/** Successful result only; partial failure diagnostics can never parse as all-name cleanup. */
export function parseGradeBatchCleanupResult(value: unknown): GradeBatchCleanupResult {
  const row = exact(value, ["schemaVersion", "kind", "scope", "cleanupVerified", "elapsedMs", "stableAbsenceMs", "passes", "jobs"],
    "grade batch cleanup result");
  if (row.schemaVersion !== 1 || row.kind !== "grade-batch-cleanup-result"
      || row.scope !== "reserved-name-cleanup-not-process-settlement-work-or-approval" || row.cleanupVerified !== true
      || !integer(row.elapsedMs, 3000, 300_000) || !integer(row.stableAbsenceMs, 3000, row.elapsedMs)
      || !integer(row.passes, 3, 2 * (Math.ceil(row.elapsedMs / 250) + 1))
      || !Array.isArray(row.jobs) || !row.jobs.length || row.jobs.length > 128) {
    throw new Error("Grade batch cleanup is incomplete or outside its protected bounds");
  }
  const jobs = row.jobs.map(item => job(item, Number(row.passes)));
  if (new Set(jobs.map(item => item.containerName)).size !== jobs.length) throw new Error("Grade batch cleanup repeats a reserved name");
  return row as unknown as GradeBatchCleanupResult;
}

function sourceColor(value: unknown): OpeningSourceColorCleanupEvidence {
  const row = exact(value, ["reservation", "sourceColorHash", "batch"], "opening source color cleanup");
  const ref = exact(row.reservation, ["path", "sha256", "sizeBytes"], "opening source color reservation");
  openingAbsolutePath(ref.path); sha256(ref.sha256, "reservation raw SHA"); sha256(row.sourceColorHash, "sourceColorHash");
  if (typeof ref.path !== "string" || !ref.path.endsWith("/.sniper-color-resource/active.json") || !integer(ref.sizeBytes, 1, 8 * 1024 * 1024)) {
    throw new Error("Opening source color cleanup lacks the exact reservation reference");
  }
  parseGradeBatchCleanupResult(row.batch);
  return row as unknown as OpeningSourceColorCleanupEvidence;
}

function stages(value: unknown, orders: number[], elapsed: number): OpeningCleanupResultV1["stages"] {
  const names = ["cleanup-claim-and-controls", "source-color-reservation-read", ...orders.map(order => `reconcile-graphic-${order}`),
    "cleanup-controls-after", "reconcile-source-color-batch", "source-color-reservation-after"];
  if (!Array.isArray(value) || value.length !== names.length) throw new Error("All-source cleanup stage coverage is incomplete");
  value.forEach((item, index) => {
    const row = exact(item, ["stage", "status", "elapsedMs"], "all-source cleanup stage");
    if (row.stage !== names[index] || row.status !== "complete" || !integer(row.elapsedMs, 0, elapsed)) {
      throw new Error("All-source cleanup stage order, timing or completion differs");
    }
  });
  return value as OpeningCleanupResultV1["stages"];
}

/** Retain the exact legacy parser; V2 must additionally cover source reservation and all stages. */
export function parseCurrentOpeningCleanupResult(value: unknown): CurrentOpeningCleanupResult {
  const row = objectValue(value, "opening cleanup result");
  if (row.schemaVersion === 1) return parseOpeningCleanupResult(row);
  const { sourceColor: selected, stages: rawStages, ...base } = row;
  if (row.schemaVersion !== 2 || !Array.isArray(base.graphics) || !integer(base.elapsedMs, 0, 300_000)) {
    throw new Error("Unsupported all-source opening cleanup version or bounds");
  }
  const colors = sourceColor(selected), orders = base.graphics.map(item => Number(objectValue(item, "cleanup graphic").order));
  const rows = stages(rawStages, orders, base.elapsedMs);
  const legacyStages = [rows[0], ...rows.slice(2, 2 + orders.length), rows[2 + orders.length]];
  parseOpeningCleanupResult({ ...base, schemaVersion: 1, stages: legacyStages });
  const batchStage = rows.at(-2)!;
  if (colors.batch.elapsedMs > batchStage.elapsedMs || batchStage.elapsedMs > base.elapsedMs) {
    throw new Error("Grade cleanup timing exceeds its actual enclosing cleanup stage");
  }
  return row as unknown as OpeningCleanupResultV2;
}

/** Whole bounded stdout only. This parser does not launch, discover or release a resource. */
export function parseCurrentOpeningCleanupStdout(stdout: string): CurrentOpeningCleanupResult {
  if (Buffer.byteLength(stdout, "utf8") > 128 * 1024 || stdout.includes("\u0000")) throw new Error("Opening cleanup stdout is unsafe or over budget");
  return parseCurrentOpeningCleanupResult(JSON.parse(stdout.trim()));
}
