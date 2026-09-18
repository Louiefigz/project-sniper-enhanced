import { existsSync } from "node:fs";
import path from "node:path";
import {
  parseCutRepairRippleReopenActionV1,
  parseCutRepairRippleReopenReceiptV1,
  type CutRepairRippleReopenActionV1,
} from "@/lib/producer/contracts/cut-repair-ripple-reopen";
import { rippleAffectedDependentIds } from
  "@/lib/producer/contracts/cut-repair-ripple-impact";
import {
  parseProjectRevision,
  parseProjectRevisionV2,
  type ProjectRevision,
  type ProjectRevisionV2,
} from "@/lib/producer/contracts/project-revision";
import { parseProjectionReceiptV1 } from
  "@/lib/producer/contracts/projection-receipt";
import { parseRenderGraphV1 } from "@/lib/producer/contracts/render-graph";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  assertObjectHashSync,
  authorityKey,
  producerAuthorityPaths,
  readAuthorityJsonSync,
  writeAuthorityObjectSync,
} from "./producer-authority-files";
import {
  materializeCutRepairTransitionSync,
  parseCutRepairTransitionRecord,
  recoverCutRepairTransitionSync,
  type CutRepairTransitionHooks,
  type CutRepairTransitionOutcome,
  type CutRepairTransitionRecord,
} from "./cut-repair-transition-store";
import {
  assertRevisionPlanObjectSync,
  revisionV2WriteFrom,
  writeProjectRevisionV2Sync,
} from "./producer-plan-authority";

export interface CutRepairRippleReopenInput {
  producerDir: string;
  action: unknown;
}

function recordPath(producerDir: string, idempotencyKey: string): string {
  return path.join(
    producerAuthorityPaths(producerDir).sagas,
    "cut-repair-ripple-reopen",
    "records",
    `${authorityKey(idempotencyKey)}.json`,
  );
}

function storedRecord(
  producerDir: string,
  idempotencyKey: string,
): CutRepairTransitionRecord | null {
  const filePath = recordPath(producerDir, idempotencyKey);
  if (!existsSync(filePath)) return null;
  const record = parseCutRepairTransitionRecord(
    readAuthorityJsonSync(filePath));
  if (record.transition !== "ripple-reopen") {
    throw new Error("ripple reopen idempotency record changed transition");
  }
  return record;
}

export function loadCutRepairRippleReopenActionSync(
  producerDir: string,
  idempotencyKey: string,
): CutRepairRippleReopenActionV1 | null {
  const record = storedRecord(producerDir, idempotencyKey);
  if (!record) return null;
  const paths = producerAuthorityPaths(producerDir);
  const action = parseCutRepairRippleReopenActionV1(assertObjectHashSync(
    paths.objects.cutRepairs, record.actionHash));
  if (action.idempotencyKey !== idempotencyKey) {
    throw new Error("stored ripple reopen action changed request identity");
  }
  return action;
}

function parentRevision(
  producerDir: string,
  action: CutRepairRippleReopenActionV1,
): ProjectRevision {
  const paths = producerAuthorityPaths(producerDir);
  const parent = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, action.expectedParentRevisionHash));
  if (parent.schemaVersion !== 2
      || parent.workflowState !== "PICTURE_LOCKED"
      || parent.pictureLockHash !== action.parentPictureLockHash
      || parent.planObjectHash !== action.preservedPlanObjectHash
      || parent.planContentHash !== action.preservedPlanContentHash
      || parent.timelineMapHash !== action.preservedTimelineMapHash
      || parent.renderGraphHash !== action.preservedRenderGraphHash
      || parent.projectionReceiptHash
        !== action.preservedProjectionReceiptHash) {
    throw new Error("ripple reopen action is not bound to its locked parent");
  }
  return parent;
}

function verifyPreservedArtifacts(
  producerDir: string,
  action: CutRepairRippleReopenActionV1,
): Record<string, unknown> {
  const paths = producerAuthorityPaths(producerDir);
  const plan = assertObjectHashSync(
    paths.objects.plans, action.preservedPlanObjectHash);
  parseRenderGraphV1(assertObjectHashSync(
    paths.objects.graphs, action.preservedRenderGraphHash));
  if (action.preservedProjectionReceiptHash) {
    const projection = parseProjectionReceiptV1(assertObjectHashSync(
      paths.objects.projections, action.preservedProjectionReceiptHash));
    if (projection.canonicalPlanHash !== action.preservedPlanContentHash
        || projection.timelineMapHash !== action.preservedTimelineMapHash) {
      throw new Error("ripple reopen projection no longer binds the parent");
    }
  }
  return plan as Record<string, unknown>;
}

function draftRevision(
  parent: ProjectRevision,
  action: CutRepairRippleReopenActionV1,
  actionHash: string,
): ProjectRevisionV2 {
  return parseProjectRevisionV2({
    ...revisionV2WriteFrom(parent),
    schemaVersion: 2,
    planObjectHash: action.preservedPlanObjectHash,
    parentRevisionHash: action.expectedParentRevisionHash,
    pictureLockHash: null,
    workflowState: "CUT_DRAFT",
    authoritativeSidecars: {
      ...parent.authoritativeSidecars,
      cutRepairRippleReopenAction: actionHash,
      cutRepairRippleAnalysis: action.analysisHash,
      cutRepairRippleImpact: action.impactHash,
      reopenedPictureLock: action.parentPictureLockHash,
    },
  });
}

function reopenReceipt(
  action: CutRepairRippleReopenActionV1,
  actionHash: string,
  childRevisionHash: string,
) {
  return parseCutRepairRippleReopenReceiptV1({
    schemaVersion: 1,
    kind: "cut-repair-ripple-reopen-receipt",
    status: "CUT_DRAFT_REOPENED",
    idempotencyKey: action.idempotencyKey,
    actionHash,
    expectedParentRevisionHash: action.expectedParentRevisionHash,
    childRevisionHash,
    originalPictureLockHash: action.parentPictureLockHash,
    analysisHash: action.analysisHash,
    impactHash: action.impactHash,
    preservedPlanObjectHash: action.preservedPlanObjectHash,
    preservedPlanContentHash: action.preservedPlanContentHash,
    preservedTimelineMapHash: action.preservedTimelineMapHash,
    preservedRenderGraphHash: action.preservedRenderGraphHash,
    preservedProjectionReceiptHash: action.preservedProjectionReceiptHash,
    affectedDependentIds: rippleAffectedDependentIds(
      action.analysis.rippleImpact),
    unchangedOutputLockedIds:
      action.analysis.rippleImpact.unchangedOutputLockedIds,
    recordedAt: action.requestedAt,
  });
}

function materialize(
  input: CutRepairRippleReopenInput,
  hooks: CutRepairTransitionHooks,
): CutRepairTransitionRecord {
  const action = parseCutRepairRippleReopenActionV1(input.action);
  const parent = parentRevision(input.producerDir, action);
  const plan = verifyPreservedArtifacts(input.producerDir, action);
  const paths = producerAuthorityPaths(input.producerDir);
  const storedAnalysis = writeAuthorityObjectSync(
    paths.objects.cutRepairs, action.analysis);
  const storedImpact = writeAuthorityObjectSync(
    paths.objects.cutRepairs, action.analysis.rippleImpact);
  if (storedAnalysis.hash !== action.analysisHash
      || storedImpact.hash !== action.impactHash) {
    throw new Error("stored ripple analysis identities changed");
  }
  const storedAction = writeAuthorityObjectSync(paths.objects.cutRepairs, action);
  const expected = draftRevision(parent, action, storedAction.hash);
  const child = writeProjectRevisionV2Sync({
    paths, planObject: plan, revision: revisionV2WriteFrom(expected),
  });
  const receipt = reopenReceipt(
    action, storedAction.hash, child.revisionHash);
  const storedReceipt = writeAuthorityObjectSync(paths.objects.receipts, receipt);
  return materializeCutRepairTransitionSync(input.producerDir, {
    schemaVersion: 1,
    kind: "cut-repair-transition-record",
    transition: "ripple-reopen",
    idempotencyKey: action.idempotencyKey,
    actionHash: storedAction.hash,
    expectedParentRevisionHash: action.expectedParentRevisionHash,
    childRevisionHash: child.revisionHash,
    originalPictureLockedParentHash: action.expectedParentRevisionHash,
    receiptHash: storedReceipt.hash,
    artifactHashes: {
      action: storedAction.hash,
      analysis: storedAnalysis.hash,
      impact: storedImpact.hash,
      plan: action.preservedPlanObjectHash,
      renderGraph: action.preservedRenderGraphHash,
      ...(action.preservedProjectionReceiptHash
        ? { projection: action.preservedProjectionReceiptHash } : {}),
      revision: child.revisionHash,
      receipt: storedReceipt.hash,
    },
    recordedAt: action.requestedAt,
  }, hooks);
}

function verifyRecord(
  producerDir: string,
  record: CutRepairTransitionRecord,
): void {
  if (record.transition !== "ripple-reopen") {
    throw new Error("ripple reopen recovery received another transition");
  }
  const paths = producerAuthorityPaths(producerDir);
  const action = parseCutRepairRippleReopenActionV1(assertObjectHashSync(
    paths.objects.cutRepairs, record.actionHash));
  const parent = parentRevision(producerDir, action);
  const plan = verifyPreservedArtifacts(producerDir, action);
  const analysis = assertObjectHashSync(
    paths.objects.cutRepairs, record.artifactHashes.analysis);
  const impact = assertObjectHashSync(
    paths.objects.cutRepairs, record.artifactHashes.impact);
  const child = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, record.childRevisionHash));
  const receipt = parseCutRepairRippleReopenReceiptV1(assertObjectHashSync(
    paths.objects.receipts, record.receiptHash));
  const expected = draftRevision(parent, action, record.actionHash);
  assertRevisionPlanObjectSync(paths, child);
  if (canonicalJsonSha256(analysis) !== action.analysisHash
      || canonicalJsonSha256(impact) !== action.impactHash
      || canonicalJsonSha256(child) !== canonicalJsonSha256(expected)
      || canonicalJsonSha256(plan) !== action.preservedPlanObjectHash
      || receipt.actionHash !== record.actionHash
      || receipt.childRevisionHash !== record.childRevisionHash
      || receipt.impactHash !== action.impactHash) {
    throw new Error("stored ripple reopen transition is inconsistent");
  }
}

export function recoverCutRepairRippleReopenSync(
  producerDir: string,
  idempotencyKey: string,
  expectedTargetHash: string,
  hooks: CutRepairTransitionHooks = {},
): CutRepairTransitionOutcome {
  const action = loadCutRepairRippleReopenActionSync(
    producerDir, idempotencyKey);
  if (!action || action.targetHash !== expectedTargetHash) {
    throw new Error("ripple reopen recovery target is absent or substituted");
  }
  return recoverCutRepairTransitionSync({
    producerDir,
    transition: "ripple-reopen",
    idempotencyKey,
    verify: (record) => verifyRecord(producerDir, record),
  }, hooks);
}

export function reopenCutRepairForRippleSync(
  input: CutRepairRippleReopenInput,
  hooks: CutRepairTransitionHooks = {},
): CutRepairTransitionOutcome {
  const action = parseCutRepairRippleReopenActionV1(input.action);
  const existing = storedRecord(input.producerDir, action.idempotencyKey);
  if (existing && existing.actionHash !== canonicalJsonSha256(action)) {
    throw new Error("ripple reopen idempotency key belongs to another action");
  }
  if (!existing) materialize(input, hooks);
  return recoverCutRepairRippleReopenSync(
    input.producerDir, action.idempotencyKey, action.targetHash, hooks);
}
