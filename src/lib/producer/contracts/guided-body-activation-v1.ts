import { exactKeys, objectValue, sha256, uuid } from "./validation";
import { openingAbsolutePath } from "./guided-opening-media-v1";
import { parseOpeningRuntimeControl, type OpeningRuntimeControlV1 } from "./guided-opening-claim-v1";
import { parseBodyGraphicOrders, type BodyFileReference, type CurrentGuidedBodyMediaInput } from "./guided-body-media-v1";

export interface GuidedBodyExecutionActivationV1 {
  schemaVersion: 1; kind: "guided-body-execution-activation"; scope: "private-body-owned-execution-not-approval";
  requestId: string; executionId: string; admissionClaimHash: string; beforeJournalHash: string;
  inputPath: string; inputSha256: string; outputRoot: string; clockHash: string; generationStartedAt: string;
  budgetAdmissionHash: string; budgetPrecommitHash: string; selectedGraphicOrders: number[];
  runtime: OpeningRuntimeControlV1; createdAt: string;
}

/** Canonical UTC only; this parser never invents a new body deadline or human-wait exclusion. */
export function bodyTimestamp(value: unknown): string {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString() !== value) {
    throw new Error("Body original/activation timestamp is malformed");
  }
  return value;
}

/** A distinct actual invocation claim, not an upgrade of historical non-executable admission. */
export function parseGuidedBodyExecutionActivation(value: unknown): GuidedBodyExecutionActivationV1 {
  const row = objectValue(value, "body activation"), keys = ["schemaVersion", "kind", "scope", "requestId", "executionId",
    "admissionClaimHash", "beforeJournalHash", "inputPath", "inputSha256", "outputRoot", "clockHash", "generationStartedAt",
    "budgetAdmissionHash", "budgetPrecommitHash", "selectedGraphicOrders", "runtime", "createdAt"];
  exactKeys(row, keys, keys, "body activation");
  if (row.schemaVersion !== 1 || row.kind !== "guided-body-execution-activation"
      || row.scope !== "private-body-owned-execution-not-approval") throw new Error("Body activation role is unsupported");
  uuid(row.requestId, "body requestId"); uuid(row.executionId, "body executionId");
  for (const key of ["admissionClaimHash", "beforeJournalHash", "inputSha256", "clockHash", "budgetAdmissionHash", "budgetPrecommitHash"]) {
    sha256(row[key], key);
  }
  openingAbsolutePath(row.inputPath); openingAbsolutePath(row.outputRoot);
  parseOpeningRuntimeControl(row.runtime); parseBodyGraphicOrders(row.selectedGraphicOrders);
  if (bodyTimestamp(row.generationStartedAt) > bodyTimestamp(row.createdAt)) throw new Error("Body activation predates its original request");
  return row as unknown as GuidedBodyExecutionActivationV1;
}

/** Cross-bind two closed documents. Actual file observations and durable activation selection remain mandatory. */
export function assertBodyActivationInput(activation: GuidedBodyExecutionActivationV1,
  input: CurrentGuidedBodyMediaInput, reference: BodyFileReference): void {
  if (activation.inputPath !== reference.path || activation.inputSha256 !== reference.sha256
      || activation.requestId !== input.requestId || activation.executionId !== input.executionId
      || activation.admissionClaimHash !== input.references.admissionClaim.sha256
      || activation.budgetAdmissionHash !== input.references.budgetAdmission.sha256
      || activation.budgetPrecommitHash !== input.references.budgetPrecommit.sha256
      || activation.selectedGraphicOrders.length !== input.selectedGraphicOrders.length
      || activation.selectedGraphicOrders.some((order, index) => order !== input.selectedGraphicOrders[index])
      || Object.entries(activation.runtime).some(([key, value]) => input.runtime[key as keyof OpeningRuntimeControlV1] !== value)) {
    throw new Error("Body activation differs from its independently held exact input");
  }
}
