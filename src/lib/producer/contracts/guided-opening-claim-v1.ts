import { exactKeys, objectValue, sha256, uuid } from "./validation";
import { openingAbsolutePath } from "./guided-opening-media-v1";

/** Trusted control selection captured by the server, not Docker absence or render proof. */
export interface OpeningRuntimeControlV1 {
  dockerPath: string; dockerSha256: string; dockerSocketPath: string;
  dockerSocketDevice: string; dockerSocketInode: string; imageId: string; userId: string;
  imageApprovalPath: string; imageApprovalSha256: string; runtimeRepoRoot: string;
}
export interface GuidedOpeningExecutionClaimV1 {
  schemaVersion: 1; kind: "guided-opening-execution-claim";
  scope: "private-opening-owned-execution-not-approval";
  requestId: string; executionId: string; beforeJournalHash: string;
  inputPath: string; inputSha256: string; executionInputHash: string; outputRoot: string;
  clockHash: string; generationStartedAt: string; budgetAdmissionHash: string;
  selectedGraphicOrders: number[]; runtime: OpeningRuntimeControlV1;
}
const RUNTIME_KEYS = ["dockerPath", "dockerSha256", "dockerSocketPath", "dockerSocketDevice", "dockerSocketInode",
  "imageId", "userId", "imageApprovalPath", "imageApprovalSha256", "runtimeRepoRoot"];

/** Closed shape only; concrete executable/socket/approval observation is server-owned. */
export function parseOpeningRuntimeControl(value: unknown): OpeningRuntimeControlV1 {
  const row = objectValue(value, "opening runtime controls"); exactKeys(row, RUNTIME_KEYS, RUNTIME_KEYS, "opening runtime controls");
  for (const key of ["dockerPath", "dockerSocketPath", "imageApprovalPath", "runtimeRepoRoot"]) openingAbsolutePath(row[key]);
  for (const key of ["dockerSha256", "imageApprovalSha256"]) sha256(row[key], key);
  for (const key of ["dockerSocketDevice", "dockerSocketInode"]) {
    if (typeof row[key] !== "string" || !/^(?:0|[1-9][0-9]{0,63})$/u.test(row[key])) throw new Error("Opening socket identity is malformed");
  }
  if (typeof row.imageId !== "string" || !/^sha256:[a-f0-9]{64}$/u.test(row.imageId)
      || typeof row.userId !== "string" || !/^[1-9][0-9]{0,9}:[1-9][0-9]{0,9}$/u.test(row.userId)) throw new Error("Opening image/nonroot user identity is malformed");
  return row as unknown as OpeningRuntimeControlV1;
}

/** An unresolved claim blocks another execution; it is never a selectable media result. */
export function parseGuidedOpeningExecutionClaim(value: unknown): GuidedOpeningExecutionClaimV1 {
  const row = objectValue(value, "opening execution claim"), keys = ["schemaVersion", "kind", "scope", "requestId", "executionId",
    "beforeJournalHash", "inputPath", "inputSha256", "executionInputHash", "outputRoot", "clockHash", "generationStartedAt",
    "budgetAdmissionHash", "selectedGraphicOrders", "runtime"];
  exactKeys(row, keys, keys, "opening execution claim");
  if (row.schemaVersion !== 1 || row.kind !== "guided-opening-execution-claim" || row.scope !== "private-opening-owned-execution-not-approval") {
    throw new Error("Opening execution claim role is unsupported");
  }
  uuid(row.requestId, "opening requestId"); uuid(row.executionId, "opening executionId");
  for (const key of ["beforeJournalHash", "inputSha256", "executionInputHash", "clockHash", "budgetAdmissionHash"]) sha256(row[key], key);
  openingAbsolutePath(row.inputPath); openingAbsolutePath(row.outputRoot); parseOpeningRuntimeControl(row.runtime);
  if (typeof row.generationStartedAt !== "string" || !Number.isFinite(Date.parse(row.generationStartedAt))
      || new Date(row.generationStartedAt).toISOString() !== row.generationStartedAt) throw new Error("Opening claim original clock is malformed");
  const orders = row.selectedGraphicOrders;
  if (!Array.isArray(orders) || orders.length > 8 || orders.some((order, index) => !Number.isSafeInteger(order)
      || order < 0 || order >= 128 || index > 0 && order <= orders[index - 1])) throw new Error("Opening claim graphic orders must be bounded, sorted and unique");
  return row as unknown as GuidedOpeningExecutionClaimV1;
}
