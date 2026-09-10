import { objectValue } from "@/lib/producer/contracts/validation";
import {
  CUT_REPAIR_PREPARATION_BLOCKERS,
  parseCutRepairPreparationPackageV1,
} from "@/lib/producer/contracts/cut-repair-preparation";
import { parseCutRepairReviewActionV1 } from
  "@/lib/producer/contracts/cut-repair-review-transition";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import { parseRenderGraphV1 } from
  "@/lib/producer/contracts/render-graph";
import {
  canonicalJsonSha256,
  fileSha256,
} from "@/lib/server/auto-edit-hash";
import { planObjectContentHash } from "@/lib/server/auto-edit-authority";
import {
  captureCutRepairPreparedRenderSync,
  type CutRepairPreparedRender,
} from "@/lib/server/cut-repair-prepared-render-authority";
import {
  storeCutRepairPreparationSync,
  type StoredCutRepairPreparation,
} from "@/lib/server/cut-repair-preparation-store";
import { stageCutRepairRenderedCandidateSync } from
  "@/lib/server/cut-repair-rendered-candidate-store";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "@/lib/server/producer-authority-files";
import {
  buildPreparedReviewGraph,
  type PreparedMediaResult,
} from "./cut-repair-preparation-plan";
import type { CutRepairDirectiveV1 } from "./cut-repair-route-policy";

interface PreparedPackageInput {
  producerDir: string;
  directive: CutRepairDirectiveV1;
  context: Record<string, unknown>;
  analysis: Record<string, unknown>;
  prepared: PreparedMediaResult;
  render: CutRepairPreparedRender;
  targetDirectiveHash: string;
}

function mediaHash(
  receipt: Record<string, unknown>,
  label: string,
): string {
  const output = objectValue(receipt.output, `${label}.output`);
  if (typeof output.path !== "string"
      || typeof output.sha256 !== "string"
      || fileSha256(output.path) !== output.sha256) {
    throw new Error(`${label} output bytes are stale`);
  }
  return output.sha256;
}

function proposedReviewAction(input: PreparedPackageInput) {
  const { directive, prepared, render } = input;
  if (!directive.idempotencyKey || !directive.requestedAt) {
    throw new Error("cut repair prepare identity is absent");
  }
  return parseCutRepairReviewActionV1({
    schemaVersion: 1,
    kind: "cut-repair-review-action",
    idempotencyKey: directive.idempotencyKey,
    expectedParentRevisionHash: prepared.parentRevisionHash,
    operation: prepared.operation,
    operationHash: prepared.operationHash,
    selectionPolicy: prepared.selectionPolicy,
    selectionPolicyHash: prepared.selectionPolicyHash,
    reviewPlanObjectHash: prepared.reviewPlanHash,
    reviewPlanContentHash: planObjectContentHash(prepared.reviewPlan),
    reviewTimelineMapHash: prepared.reviewTimelineMapHash,
    reviewRenderGraphHash: render.graphHash,
    reviewProjectionReceiptHash: null,
    workflowPolicy: "cut-first",
    requestedAt: directive.requestedAt,
  });
}

export function cutRepairPreparationResponse(
  stored: StoredCutRepairPreparation,
  replayed: boolean,
): Record<string, unknown> {
  const packageValue = stored.package;
  return {
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    routeStatus: "rendered-plan-preparation-blocked",
    status: packageValue.status,
    replayed,
    preparationHash: stored.packageHash,
    parentRevisionHash: packageValue.parentRevisionHash,
    proposedReviewActionHash:
      canonicalJsonSha256(packageValue.proposedReviewAction),
    candidatePath: packageValue.reviewCandidatePath,
    candidateSha256: packageValue.reviewCandidateMediaSha256,
    candidateDescriptorPath: packageValue.reviewCandidateDescriptorPath,
    candidateDescriptorHash: packageValue.reviewCandidateDescriptorHash,
    reviewRenderGraphHash:
      packageValue.proposedReviewAction.reviewRenderGraphHash,
    blockingRequirements: packageValue.blockingRequirements,
    cutReviewStaged: false,
    renderGraphCandidateStaged: true,
    durablePreparationStored: true,
    selectedAuthorityMutated: false,
    authorityMutated: false,
  };
}

function storeInputs(input: PreparedPackageInput) {
  const { producerDir, context, analysis, prepared } = input;
  const paths = producerAuthorityPaths(producerDir);
  const contextObject = writeAuthorityObjectSync(
    paths.objects.cutRepairs, context);
  const analysisObject = writeAuthorityObjectSync(
    paths.objects.cutRepairs, analysis);
  const planObject = writeAuthorityObjectSync(
    paths.objects.plans, prepared.reviewPlan);
  const projectionObject = writeAuthorityObjectSync(
    paths.objects.cutRepairs, prepared.reviewProjection);
  if (planObject.hash !== prepared.reviewPlanHash) {
    throw new Error("stored review plan changed identity");
  }
  return { contextObject, analysisObject, projectionObject };
}

function invalidationStrategy(input: PreparedPackageInput) {
  if (input.prepared.picturePlanAuthority) {
    return "picture-surgical-terminal" as const;
  }
  const paths = producerAuthorityPaths(input.producerDir);
  const parent = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, input.prepared.parentRevisionHash));
  const parentGraph = parseRenderGraphV1(assertObjectHashSync(
    paths.objects.graphs, parent.renderGraphHash));
  return buildPreparedReviewGraph(
    parentGraph, input.prepared.operationHash).strategy;
}

/** Persist the exact private full-plan render without advancing edit authority. */
export function storePreparedCutRepairPackageSync(
  input: PreparedPackageInput,
): Record<string, unknown> {
  captureCutRepairPreparedRenderSync(input.producerDir, input.render);
  const storedInputs = storeInputs(input);
  const action = proposedReviewAction(input);
  const candidate = stageCutRepairRenderedCandidateSync({
    producerDir: input.producerDir,
    action,
    render: input.render,
  });
  const packageValue = parseCutRepairPreparationPackageV1({
    schemaVersion: 1,
    kind: "cut-repair-preparation-package",
    status: "rendered-plan-candidate-prepared",
    idempotencyKey: input.directive.idempotencyKey,
    targetDirectiveHash: input.targetDirectiveHash,
    contextAuthorityHash: input.prepared.contextAuthorityHash,
    contextObjectHash: storedInputs.contextObject.hash,
    analysisObjectHash: storedInputs.analysisObject.hash,
    parentRevisionHash: input.prepared.parentRevisionHash,
    proposedReviewAction: action,
    reviewProjectionHash: storedInputs.projectionObject.hash,
    renderInvalidationStrategy: invalidationStrategy(input),
    fragmentReceipt: input.prepared.fragmentReceipt,
    compositeReceipt: input.prepared.compositeReceipt,
    fragmentMediaSha256: mediaHash(
      input.prepared.fragmentReceipt, "prepared fragment"),
    compositeMediaSha256: mediaHash(
      input.prepared.compositeReceipt, "prepared composite"),
    reviewRenderGraphReceiptHash: input.render.graphReceiptHash,
    reviewRenderGraphCandidatePointerHash:
      input.render.candidatePointerHash,
    reviewCandidateMediaSha256: input.render.candidateSha256,
    reviewCandidatePath: input.render.candidatePath,
    reviewCandidateDescriptorHash: candidate.descriptorHash,
    reviewCandidateDescriptorPath: candidate.descriptorPath,
    previousRenderGraphHash: input.render.previousGraphHash,
    previousRenderGraphReceiptHash:
      input.render.previousGraphReceiptHash,
    blockingRequirements: [...CUT_REPAIR_PREPARATION_BLOCKERS],
    preparedAt: input.directive.requestedAt,
  });
  return cutRepairPreparationResponse(
    storeCutRepairPreparationSync(input.producerDir, packageValue), false);
}
