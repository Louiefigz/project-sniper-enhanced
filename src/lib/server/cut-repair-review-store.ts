import { existsSync } from "node:fs";
import path from "node:path";
import {
  parseCutRepairReviewActionV1,
  parseCutRepairSelectionPolicyV1,
  type CutRepairReviewActionV1,
} from "@/lib/producer/contracts/cut-repair-review-transition";
import { parseCutRepairTransitionReceiptV1 } from
  "@/lib/producer/contracts/cut-repair-transition-receipt";
import {
  parseProjectRevision,
  parseProjectRevisionV1,
  parseProjectRevisionV2,
  type ProjectRevision,
  type ProjectRevisionV1,
  type ProjectRevisionV2,
} from
  "@/lib/producer/contracts/project-revision";
import { parseProjectionReceiptV1 } from
  "@/lib/producer/contracts/projection-receipt";
import { parseRenderGraphV1 } from "@/lib/producer/contracts/render-graph";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { planObjectContentHash } from "./auto-edit-authority";
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

export interface CutRepairReviewInput {
  producerDir: string;
  action: unknown;
}

function existingRecord(
  producerDir: string,
  action: CutRepairReviewActionV1,
): CutRepairTransitionRecord | null {
  const paths = producerAuthorityPaths(producerDir);
  const filePath = path.join(
    paths.sagas, "cut-repair-review", "records",
    `${authorityKey(action.idempotencyKey)}.json`);
  if (!existsSync(filePath)) return null;
  const record = parseCutRepairTransitionRecord(
    readAuthorityJsonSync(filePath));
  if (record.actionHash !== canonicalJsonSha256(action)) {
    throw new Error("review idempotency key is bound to another action");
  }
  return record;
}

function parentRevision(
  producerDir: string,
  action: CutRepairReviewActionV1,
): ProjectRevision {
  const paths = producerAuthorityPaths(producerDir);
  const parent = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, action.expectedParentRevisionHash));
  if (parent.workflowState !== "PICTURE_LOCKED" || !parent.pictureLockHash) {
    throw new Error("cut repair review parent is not PICTURE_LOCKED");
  }
  const operation = action.operation;
  if (operation.parentPictureLockHash !== parent.pictureLockHash
      || operation.parentTimelineMapHash !== parent.timelineMapHash
      || operation.target.transcriptTimingHash !== parent.transcriptTimingHash
      || action.reviewPlanContentHash === parent.planContentHash
      || action.reviewTimelineMapHash === parent.timelineMapHash) {
    throw new Error("cut repair review action is not bound to its original parent");
  }
  return parent;
}

function reviewRevision(
  parent: ProjectRevision,
  action: CutRepairReviewActionV1,
  actionHash: string,
  planObject: unknown,
): ProjectRevisionV2 {
  const planObjectHash = canonicalJsonSha256(planObject);
  const planContentHash = planObjectContentHash(planObject);
  if (planObjectHash !== action.reviewPlanObjectHash
      || planContentHash !== action.reviewPlanContentHash) {
    throw new Error("cut repair review plan identities disagree");
  }
  return parseProjectRevisionV2({
    ...revisionV2WriteFrom(parent),
    schemaVersion: 2,
    planObjectHash,
    parentRevisionHash: action.expectedParentRevisionHash,
    planContentHash,
    timelineMapHash: action.reviewTimelineMapHash,
    pictureLockHash: null,
    workflowState: "CUT_REVIEW",
    renderGraphHash: action.reviewRenderGraphHash,
    projectionReceiptHash: action.reviewProjectionReceiptHash,
    authoritativeSidecars: {
      ...parent.authoritativeSidecars,
      cutRepairReviewAction: actionHash,
      cutRepairSelectionPolicy: action.selectionPolicyHash,
    },
  });
}

function legacyReviewRevision(
  parent: ProjectRevision,
  action: CutRepairReviewActionV1,
  actionHash: string,
): ProjectRevisionV1 {
  return parseProjectRevisionV1({
    ...revisionV2WriteFrom(parent),
    schemaVersion: 1,
    parentRevisionHash: action.expectedParentRevisionHash,
    planContentHash: action.reviewPlanContentHash,
    timelineMapHash: action.reviewTimelineMapHash,
    pictureLockHash: null,
    workflowState: "CUT_REVIEW",
    renderGraphHash: action.reviewRenderGraphHash,
    projectionReceiptHash: action.reviewProjectionReceiptHash,
    authoritativeSidecars: {
      ...parent.authoritativeSidecars,
      cutRepairReviewAction: actionHash,
      cutRepairSelectionPolicy: action.selectionPolicyHash,
    },
  });
}

function reviewReceipt(
  action: CutRepairReviewActionV1,
  actionHash: string,
  revisionHash: string,
) {
  return parseCutRepairTransitionReceiptV1({
    schemaVersion: 1,
    kind: "cut-repair-transition-receipt",
    status: "CUT_REVIEW_COMMITTED",
    idempotencyKey: action.idempotencyKey,
    actionHash,
    expectedParentRevisionHash: action.expectedParentRevisionHash,
    childRevisionHash: revisionHash,
    originalPictureLockedParentHash: action.expectedParentRevisionHash,
    operationHash: action.operationHash,
    selectionPolicyHash: action.selectionPolicyHash,
    childPictureLockHash: null,
    recordedAt: action.requestedAt,
  });
}

function verifyDependencies(
  producerDir: string,
  action: CutRepairReviewActionV1,
): void {
  const paths = producerAuthorityPaths(producerDir);
  const plan = assertObjectHashSync(
    paths.objects.plans, action.reviewPlanObjectHash);
  if (planObjectContentHash(plan) !== action.reviewPlanContentHash) {
    throw new Error("cut repair review plan identities disagree");
  }
  parseRenderGraphV1(assertObjectHashSync(
    paths.objects.graphs, action.reviewRenderGraphHash));
  if (!action.reviewProjectionReceiptHash) return;
  const projection = parseProjectionReceiptV1(assertObjectHashSync(
    paths.objects.projections, action.reviewProjectionReceiptHash));
  if (projection.canonicalPlanHash !== action.reviewPlanContentHash
      || projection.timelineMapHash !== action.reviewTimelineMapHash) {
    throw new Error("cut repair review projection is stale");
  }
}

function materialize(
  input: CutRepairReviewInput,
  hooks: CutRepairTransitionHooks,
): CutRepairTransitionRecord {
  const action = parseCutRepairReviewActionV1(input.action);
  const parent = parentRevision(input.producerDir, action);
  verifyDependencies(input.producerDir, action);
  const paths = producerAuthorityPaths(input.producerDir);
  const storedAction = writeAuthorityObjectSync(paths.objects.cutRepairs, action);
  const storedPolicy = writeAuthorityObjectSync(
    paths.objects.cutRepairs, action.selectionPolicy);
  if (storedPolicy.hash !== action.selectionPolicyHash) {
    throw new Error("stored cut repair selection policy hash changed");
  }
  const planObject = assertObjectHashSync(paths.objects.plans, action.reviewPlanObjectHash);
  const storedRevision = writeProjectRevisionV2Sync({
    paths,
    planObject,
    revision: revisionV2WriteFrom(reviewRevision(
      parent, action, storedAction.hash, planObject)),
  });
  if (storedRevision.planObjectHash !== action.reviewPlanObjectHash) {
    throw new Error("cut repair review plan changed exact identity");
  }
  const receipt = reviewReceipt(action, storedAction.hash, storedRevision.revisionHash);
  const storedReceipt = writeAuthorityObjectSync(paths.objects.receipts, receipt);
  return materializeCutRepairTransitionSync(input.producerDir, {
    schemaVersion: 1,
    kind: "cut-repair-transition-record",
    transition: "review",
    idempotencyKey: action.idempotencyKey,
    actionHash: storedAction.hash,
    expectedParentRevisionHash: action.expectedParentRevisionHash,
    childRevisionHash: storedRevision.revisionHash,
    originalPictureLockedParentHash: action.expectedParentRevisionHash,
    receiptHash: storedReceipt.hash,
    artifactHashes: {
      action: storedAction.hash,
      selectionPolicy: storedPolicy.hash,
      plan: action.reviewPlanObjectHash,
      renderGraph: action.reviewRenderGraphHash,
      ...(action.reviewProjectionReceiptHash
        ? { projection: action.reviewProjectionReceiptHash } : {}),
      revision: storedRevision.revisionHash,
      receipt: storedReceipt.hash,
    },
    recordedAt: action.requestedAt,
  }, hooks);
}

function verifyReviewRecord(
  producerDir: string,
  record: CutRepairTransitionRecord,
): void {
  if (record.transition !== "review") {
    throw new Error("cut repair review recovery received another transition");
  }
  const paths = producerAuthorityPaths(producerDir);
  const hashes = record.artifactHashes;
  const action = parseCutRepairReviewActionV1(assertObjectHashSync(
    paths.objects.cutRepairs, hashes.action));
  const policy = parseCutRepairSelectionPolicyV1(assertObjectHashSync(
    paths.objects.cutRepairs, hashes.selectionPolicy));
  const revision = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, hashes.revision));
  const receipt = parseCutRepairTransitionReceiptV1(assertObjectHashSync(
    paths.objects.receipts, hashes.receipt));
  assertRevisionPlanObjectSync(paths, revision);
  const parent = parentRevision(producerDir, action);
  const expected = revision.schemaVersion === 1
    ? legacyReviewRevision(parent, action, hashes.action)
    : reviewRevision(parent, action, hashes.action,
      assertObjectHashSync(paths.objects.plans, hashes.plan));
  verifyDependencies(producerDir, action);
  if (record.actionHash !== hashes.action
      || record.childRevisionHash !== hashes.revision
      || record.receiptHash !== hashes.receipt
      || canonicalJsonSha256(policy) !== action.selectionPolicyHash
      || canonicalJsonSha256(revision) !== canonicalJsonSha256(expected)
      || receipt.actionHash !== hashes.action
      || receipt.childRevisionHash !== hashes.revision
      || receipt.expectedParentRevisionHash
        !== record.expectedParentRevisionHash) {
    throw new Error("stored cut repair review transition is inconsistent");
  }
}

/** Recover a previously materialized review action without caller evidence. */
export function recoverCutRepairReviewSync(
  producerDir: string,
  idempotencyKey: string,
  hooks: CutRepairTransitionHooks = {},
): CutRepairTransitionOutcome {
  return recoverCutRepairTransitionSync({
    producerDir,
    transition: "review",
    idempotencyKey,
    verify: (record) => verifyReviewRecord(producerDir, record),
  }, hooks);
}

/** Create/retry the exact PICTURE_LOCKED -> CUT_REVIEW transition. */
export function stageCutRepairReviewSync(
  input: CutRepairReviewInput,
  hooks: CutRepairTransitionHooks = {},
): CutRepairTransitionOutcome {
  const action = parseCutRepairReviewActionV1(input.action);
  if (existingRecord(input.producerDir, action)) {
    return recoverCutRepairReviewSync(
      input.producerDir, action.idempotencyKey, hooks);
  }
  const record = materialize(input, hooks);
  return recoverCutRepairReviewSync(
    input.producerDir, record.idempotencyKey, hooks);
}
