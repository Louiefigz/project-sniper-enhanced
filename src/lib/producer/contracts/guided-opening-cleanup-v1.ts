import { exactKeys, objectValue, sha256, uuid } from "./validation";
import { openingAbsolutePath } from "./guided-opening-media-v1";

export interface OpeningAbsenceV1 {
  containerRef: string; canonicalAbsenceProved: true;
  method: "late-create-reconciliation" | "docker-force-remove-plus-exact-inspect-absence";
}
export type OpeningCleanupGraphicV1 = {
  order: number; state: "not-initialized" | "initialized-unarmed"; containerNames: []; cleanupVerified: true;
} | { order: number; state: "reconciled-absence"; containerNames: [string]; cleanupVerified: true;
  reconciliation: OpeningAbsenceV1[]; absence: [OpeningAbsenceV1] };
export interface OpeningCleanupResultV1 {
  schemaVersion: 1; kind: "guided-opening-cleanup-result"; claimPath: string; claimSha256: string;
  inputSha256: string; outputRoot: string; executionId: string; cleanupVerified: true;
  graphics: OpeningCleanupGraphicV1[]; elapsedMs: number;
  stages: Array<{ stage: string; status: "complete"; elapsedMs: number }>;
  budgetScope: "separate-protected-cleanup-not-render-allowance";
  processGroupStopped: "requires-owned-server-observation"; openingApproved: false;
}

function exact(value: unknown, keys: string[], label: string) {
  const row = objectValue(value, label); exactKeys(row, keys, keys, label); return row;
}
function integer(value: unknown, maximum: number): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0 && Number(value) <= maximum;
}
function container(value: unknown): string {
  if (typeof value !== "string" || !/^sniper-render-[0-9a-f]{32}$/u.test(value)) throw new Error("Opening cleanup container identity is malformed");
  return value;
}
function absence(value: unknown, expected: string, method: OpeningAbsenceV1["method"]): OpeningAbsenceV1 {
  const row = exact(value, ["containerRef", "canonicalAbsenceProved", "method"], "opening absence");
  if (container(row.containerRef) !== expected || row.canonicalAbsenceProved !== true || row.method !== method) {
    throw new Error("Opening cleanup did not prove its exact named resource absent");
  }
  return row as unknown as OpeningAbsenceV1;
}
export function parseOpeningCleanupGraphic(value: unknown): OpeningCleanupGraphicV1 {
  const row = objectValue(value, "cleanup graphic"), keys = ["order", "state", "containerNames", "cleanupVerified"];
  if (row.state === "reconciled-absence") keys.push("reconciliation", "absence");
  exactKeys(row, keys, keys, "cleanup graphic");
  if (!integer(row.order, 127) || row.cleanupVerified !== true || !Array.isArray(row.containerNames)) throw new Error("Invalid cleanup graphic");
  if (row.state === "not-initialized" || row.state === "initialized-unarmed") {
    if (row.containerNames.length) throw new Error("Unarmed opening cleanup cannot claim a registered name");
    return row as unknown as OpeningCleanupGraphicV1;
  }
  if (row.state !== "reconciled-absence" || row.containerNames.length !== 1 || !Array.isArray(row.reconciliation)
      || row.reconciliation.length > 1 || !Array.isArray(row.absence) || row.absence.length !== 1) throw new Error("Opening registered cleanup is incomplete");
  const name = container(row.containerNames[0]);
  row.reconciliation.forEach((item) => absence(item, name, "late-create-reconciliation"));
  absence(row.absence[0], name, "docker-force-remove-plus-exact-inspect-absence");
  return row as unknown as OpeningCleanupGraphicV1;
}

/** Schema only: JSON cannot establish invocation provenance, stopped groups or live daemon absence. */
export function parseOpeningCleanupResult(value: unknown): OpeningCleanupResultV1 {
  const keys = ["schemaVersion", "kind", "claimPath", "claimSha256", "inputSha256", "outputRoot", "executionId", "cleanupVerified",
    "graphics", "elapsedMs", "stages", "budgetScope", "processGroupStopped", "openingApproved"];
  const row = exact(value, keys, "opening cleanup result");
  openingAbsolutePath(row.claimPath); openingAbsolutePath(row.outputRoot);
  sha256(row.claimSha256, "claimSha256"); sha256(row.inputSha256, "inputSha256"); uuid(row.executionId, "executionId");
  if (row.schemaVersion !== 1 || row.kind !== "guided-opening-cleanup-result" || row.cleanupVerified !== true
      || row.budgetScope !== "separate-protected-cleanup-not-render-allowance"
      || row.processGroupStopped !== "requires-owned-server-observation" || row.openingApproved !== false
      || !integer(row.elapsedMs, 300_000) || !Array.isArray(row.graphics) || row.graphics.length > 8
      || !Array.isArray(row.stages) || row.stages.length !== row.graphics.length + 2) throw new Error("Opening cleanup result is unsupported or incomplete");
  const graphics = row.graphics.map(parseOpeningCleanupGraphic), orders = graphics.map((item) => item.order);
  if (orders.some((order, index) => index > 0 && order <= orders[index - 1])) throw new Error("Opening cleanup graphic orders are duplicate or unsorted");
  const names = graphics.flatMap((item) => item.containerNames);
  if (new Set(names).size !== names.length) throw new Error("Opening cleanup repeats a resource across graphic orders");
  const stages = ["cleanup-claim-and-controls", ...orders.map((order) => `reconcile-graphic-${order}`), "cleanup-controls-after"];
  row.stages.forEach((item, index) => {
    const stage = exact(item, ["stage", "status", "elapsedMs"], "cleanup stage");
    if (stage.stage !== stages[index] || stage.status !== "complete" || !integer(stage.elapsedMs, Number(row.elapsedMs))) throw new Error("Opening cleanup stage coverage is incomplete");
  });
  return row as unknown as OpeningCleanupResultV1;
}

/** Exactly one bounded completion; progress must be on stderr, not guessed from a final matching row. */
export function parseOpeningCleanupStdout(stdout: string): OpeningCleanupResultV1 {
  if (Buffer.byteLength(stdout, "utf8") > 128 * 1024 || stdout.includes("\u0000")) throw new Error("Opening cleanup stdout is unsafe or over budget");
  return parseOpeningCleanupResult(JSON.parse(stdout.trim()));
}
