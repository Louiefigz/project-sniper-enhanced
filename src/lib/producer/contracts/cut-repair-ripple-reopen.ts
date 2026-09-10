import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import {
  exactKeys,
  isoDate,
  objectValue,
  sha256,
  uniqueStrings,
  uuid,
} from "./validation";
import {
  parseCutRepairRippleAnalysisV1,
  type CutRepairRippleAnalysisV1,
} from "./cut-repair-ripple-analysis";
import {
  parseCutRepairTargetV1,
  type CutRepairTargetV1,
} from "./cut-repair-target";

export interface CutRepairRippleReopenActionV1 {
  schemaVersion: 1;
  kind: "cut-repair-ripple-reopen-action";
  idempotencyKey: string;
  expectedParentRevisionHash: string;
  parentPictureLockHash: string;
  target: CutRepairTargetV1;
  targetHash: string;
  analysis: CutRepairRippleAnalysisV1;
  analysisHash: string;
  impactHash: string;
  preservedPlanObjectHash: string;
  preservedPlanContentHash: string;
  preservedTimelineMapHash: string;
  preservedRenderGraphHash: string;
  preservedProjectionReceiptHash: string | null;
  requestedAt: string;
}

export interface CutRepairRippleReopenReceiptV1 {
  schemaVersion: 1;
  kind: "cut-repair-ripple-reopen-receipt";
  status: "CUT_DRAFT_REOPENED";
  idempotencyKey: string;
  actionHash: string;
  expectedParentRevisionHash: string;
  childRevisionHash: string;
  originalPictureLockHash: string;
  analysisHash: string;
  impactHash: string;
  preservedPlanObjectHash: string;
  preservedPlanContentHash: string;
  preservedTimelineMapHash: string;
  preservedRenderGraphHash: string;
  preservedProjectionReceiptHash: string | null;
  affectedDependentIds: string[];
  unchangedOutputLockedIds: string[];
  recordedAt: string;
}

const ACTION_KEYS = [
  "schemaVersion", "kind", "idempotencyKey", "expectedParentRevisionHash",
  "parentPictureLockHash", "target", "targetHash", "analysis", "analysisHash",
  "impactHash", "preservedPlanObjectHash", "preservedPlanContentHash",
  "preservedTimelineMapHash", "preservedRenderGraphHash",
  "preservedProjectionReceiptHash", "requestedAt",
] as const;
const RECEIPT_KEYS = [
  "schemaVersion", "kind", "status", "idempotencyKey", "actionHash",
  "expectedParentRevisionHash", "childRevisionHash", "originalPictureLockHash",
  "analysisHash", "impactHash", "preservedPlanObjectHash",
  "preservedPlanContentHash", "preservedTimelineMapHash",
  "preservedRenderGraphHash", "preservedProjectionReceiptHash",
  "affectedDependentIds", "unchangedOutputLockedIds", "recordedAt",
] as const;

function optionalHash(value: unknown, label: string): string | null {
  return value === null ? null : sha256(value, label);
}

/** Parse one immutable request to reopen a locked cut for explicit ripple work. */
export function parseCutRepairRippleReopenActionV1(
  value: unknown,
): CutRepairRippleReopenActionV1 {
  const row = objectValue(value, "CutRepairRippleReopenActionV1");
  exactKeys(row, ACTION_KEYS, ACTION_KEYS, "CutRepairRippleReopenActionV1");
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-ripple-reopen-action") {
    throw new Error("CutRepairRippleReopenActionV1 version is unsupported");
  }
  const target = parseCutRepairTargetV1(row.target);
  const analysis = parseCutRepairRippleAnalysisV1(row.analysis);
  const targetHash = sha256(row.targetHash, "ripple reopen targetHash");
  const analysisHash = sha256(row.analysisHash, "ripple reopen analysisHash");
  const impactHash = sha256(row.impactHash, "ripple reopen impactHash");
  const expectedParent = sha256(
    row.expectedParentRevisionHash, "ripple reopen expected parent");
  if (canonicalJsonSha256(target) !== targetHash
      || canonicalJsonSha256(analysis) !== analysisHash
      || canonicalJsonSha256(analysis.rippleImpact) !== impactHash
      || analysis.parentRevisionHash !== expectedParent) {
    throw new Error("ripple reopen action has stale target or analysis bindings");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-ripple-reopen-action",
    idempotencyKey: uuid(row.idempotencyKey, "ripple reopen idempotencyKey"),
    expectedParentRevisionHash: expectedParent,
    parentPictureLockHash: sha256(
      row.parentPictureLockHash, "ripple reopen parent picture lock"),
    target,
    targetHash,
    analysis,
    analysisHash,
    impactHash,
    preservedPlanObjectHash: sha256(
      row.preservedPlanObjectHash, "ripple preserved plan object"),
    preservedPlanContentHash: sha256(
      row.preservedPlanContentHash, "ripple preserved plan content"),
    preservedTimelineMapHash: sha256(
      row.preservedTimelineMapHash, "ripple preserved timeline"),
    preservedRenderGraphHash: sha256(
      row.preservedRenderGraphHash, "ripple preserved render graph"),
    preservedProjectionReceiptHash: optionalHash(
      row.preservedProjectionReceiptHash, "ripple preserved projection"),
    requestedAt: isoDate(row.requestedAt, "ripple reopen requestedAt"),
  };
}

/** Parse the receipt proving no timeline/media artifact changed on reopen. */
export function parseCutRepairRippleReopenReceiptV1(
  value: unknown,
): CutRepairRippleReopenReceiptV1 {
  const row = objectValue(value, "CutRepairRippleReopenReceiptV1");
  exactKeys(row, RECEIPT_KEYS, RECEIPT_KEYS, "CutRepairRippleReopenReceiptV1");
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-ripple-reopen-receipt"
      || row.status !== "CUT_DRAFT_REOPENED") {
    throw new Error("CutRepairRippleReopenReceiptV1 version is unsupported");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-ripple-reopen-receipt",
    status: "CUT_DRAFT_REOPENED",
    idempotencyKey: uuid(row.idempotencyKey, "ripple receipt idempotencyKey"),
    actionHash: sha256(row.actionHash, "ripple receipt action"),
    expectedParentRevisionHash: sha256(
      row.expectedParentRevisionHash, "ripple receipt expected parent"),
    childRevisionHash: sha256(
      row.childRevisionHash, "ripple receipt child revision"),
    originalPictureLockHash: sha256(
      row.originalPictureLockHash, "ripple receipt original lock"),
    analysisHash: sha256(row.analysisHash, "ripple receipt analysis"),
    impactHash: sha256(row.impactHash, "ripple receipt impact"),
    preservedPlanObjectHash: sha256(
      row.preservedPlanObjectHash, "ripple receipt plan object"),
    preservedPlanContentHash: sha256(
      row.preservedPlanContentHash, "ripple receipt plan content"),
    preservedTimelineMapHash: sha256(
      row.preservedTimelineMapHash, "ripple receipt timeline"),
    preservedRenderGraphHash: sha256(
      row.preservedRenderGraphHash, "ripple receipt render graph"),
    preservedProjectionReceiptHash: optionalHash(
      row.preservedProjectionReceiptHash, "ripple receipt projection"),
    affectedDependentIds: uniqueStrings(
      row.affectedDependentIds, "ripple receipt affected dependents"),
    unchangedOutputLockedIds: uniqueStrings(
      row.unchangedOutputLockedIds, "ripple receipt output-locked dependents"),
    recordedAt: isoDate(row.recordedAt, "ripple receipt recordedAt"),
  };
}
