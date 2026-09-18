import {
  parseProjectRevision,
  type ProjectRevisionV2,
} from "@/lib/producer/contracts/project-revision";
import type { ProducerAdvanceRecordV1 } from
  "./producer-revision-store-model";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  writeAuthorityObjectSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";
import type {
  AutoEditGenesisExpectation,
  AutoEditGenesisFacts,
} from "./producer-auto-edit-genesis-facts";
import {
  assertRevisionPlanObjectSync,
  revisionV2WriteFrom,
  writeProjectRevisionV2Sync,
} from "./producer-plan-authority";
import {
  publishProducerAdvanceSync,
  resolveProducerAuthorityHeadSync,
} from "./producer-revision-head";
import { unresolvedProducerIntentsSync } from "./producer-revision-recovery";
import {
  renderedAdvanceRecord,
  renderedAdvanceSelected,
} from "./producer-auto-edit-rendered-advance";
import { prepareLegacyCompatibilityAdoptionSync } from
  "./producer-auto-edit-legacy-adoption";
export interface AutoEditRenderedTransitionHooks {
  after?: (boundary: "after-materialized" | "after-advance") => void;
}
export interface AutoEditRenderedTransitionOutcome {
  status: "advanced" | "reused";
  revisionHash: string;
}
function revisionAt(
  paths: ProducerAuthorityPaths,
  hash: string,
): ProjectRevisionV2 {
  const revision = parseProjectRevision(
    assertObjectHashSync(paths.objects.revisions, hash));
  if (revision.schemaVersion !== 2) {
    throw new Error("rendered Auto Edit authority requires ProjectRevisionV2");
  }
  assertRevisionPlanObjectSync(paths, revision);
  return revision;
}

function sameList(left: string[], right: string[]): boolean {
  return left.length === right.length
    && left.every((value, index) => value === right[index]);
}

function matchesRenderedFacts(
  paths: ProducerAuthorityPaths,
  revision: ProjectRevisionV2,
  facts: AutoEditGenesisFacts,
): boolean {
  const plan = assertRevisionPlanObjectSync(paths, revision);
  const checks = [
    canonicalJsonSha256(plan) === canonicalJsonSha256(facts.planObject),
    revision.planContentHash === facts.planContentHash,
    revision.manifestHash === facts.manifestHash,
    revision.sourceSnapshotSetHash === facts.sourceSnapshotSetHash,
    revision.transcriptTimingHash === facts.transcriptTimingHash,
    revision.timelineMapHash === facts.timelineMapHash,
    revision.canvasProfileHash === facts.canvasProfileHash,
    sameList(
      revision.destinationProfileHashes, facts.destinationProfileHashes),
    revision.pictureLockHash === facts.pictureLockHash,
    revision.projectionReceiptHash
      === canonicalJsonSha256(facts.projectionReceipt),
    revision.renderGraphHash === canonicalJsonSha256(facts.renderGraph),
    revision.workflowState === "READY_TO_FINALIZE",
    ...Object.entries(facts.authoritativeSidecars).map(
      ([key, value]) => revision.authoritativeSidecars[key] === value),
  ];
  return checks.every(Boolean);
}

function assertStoredRenderedFacts(
  paths: ProducerAuthorityPaths,
  revision: ProjectRevisionV2,
  facts: AutoEditGenesisFacts,
): void {
  const receiptHash =
    revision.authoritativeSidecars.stagedRenderGraphReceiptV1;
  const expected: Array<[string, unknown, unknown]> = [
    ["render graph",
      assertObjectHashSync(paths.objects.graphs, revision.renderGraphHash),
      facts.renderGraph],
    ["projection",
      assertObjectHashSync(
        paths.objects.projections,
        revision.authoritativeSidecars.compatibilityTimelineProjectionV1),
      facts.projection],
    ["projection receipt",
      assertObjectHashSync(
        paths.objects.projections, revision.projectionReceiptHash!),
      facts.projectionReceipt],
    ["render graph receipt",
      assertObjectHashSync(paths.objects.receipts, receiptHash),
      facts.renderGraphReceipt],
    ["render graph candidate pointer",
      assertObjectHashSync(
        paths.objects.receipts,
        revision.authoritativeSidecars.stagedRenderGraphCandidatePointerV1),
      facts.renderGraphCandidatePointer],
  ];
  assertObjectHashSync(paths.objects.requests, revision.requestLedgerHash);
  for (const [label, actual, intended] of expected) {
    if (canonicalJsonSha256(actual) !== canonicalJsonSha256(intended)) {
      throw new Error(`rendered revision stores a foreign ${label}`);
    }
  }
}

interface StoredTransition {
  childHash: string;
  record: ProducerAdvanceRecordV1;
}

interface StoredRenderedFacts {
  graphHash: string;
  projectionReceiptHash: string;
  evidenceHash: string;
}

interface RenderedTransitionContext {
  input: AutoEditGenesisExpectation;
  paths: ProducerAuthorityPaths;
  parentHash: string;
  parent: ProjectRevisionV2;
  facts: AutoEditGenesisFacts;
}

function storeRenderedFacts(
  context: RenderedTransitionContext,
): StoredRenderedFacts {
  const { input, paths, parentHash, parent, facts } = context;
  const graph = writeAuthorityObjectSync(paths.objects.graphs, facts.renderGraph);
  const projection = writeAuthorityObjectSync(
    paths.objects.projections, facts.projection);
  const projectionReceipt = writeAuthorityObjectSync(
    paths.objects.projections, facts.projectionReceipt);
  const receipt = writeAuthorityObjectSync(
    paths.objects.receipts, facts.renderGraphReceipt);
  const pointer = writeAuthorityObjectSync(
    paths.objects.receipts, facts.renderGraphCandidatePointer);
  if (graph.hash !== facts.authoritativeSidecars.stagedRenderGraphV1
      || receipt.hash
        !== facts.authoritativeSidecars.stagedRenderGraphReceiptV1
      || pointer.hash
        !== facts.authoritativeSidecars.stagedRenderGraphCandidatePointerV1
      || projection.hash
        !== facts.authoritativeSidecars.compatibilityTimelineProjectionV1) {
    throw new Error("staged graph changed during rendered revision materialization");
  }
  const evidence = writeAuthorityObjectSync(paths.objects.receipts, {
    schemaVersion: 1,
    kind: "producer-auto-edit-rendered-transition",
    parentRevisionHash: parentHash,
    parentPlanObjectHash: parent.planObjectHash,
    renderedPlanFileHash: facts.planFileHash,
    candidateMediaHash: input.expectedCandidateHash,
    graphHash: graph.hash,
    graphReceiptHash: receipt.hash,
    candidatePointerHash: pointer.hash,
    candidatePointer: facts.renderGraphCandidatePointer,
    projectionHash: projection.hash,
    projectionReceiptHash: projectionReceipt.hash,
  });
  return {
    graphHash: graph.hash,
    projectionReceiptHash: projectionReceipt.hash,
    evidenceHash: evidence.hash,
  };
}

function materializeTransition(
  context: RenderedTransitionContext,
): StoredTransition {
  const { input, paths, parentHash, parent, facts } = context;
  const stored = storeRenderedFacts(context);
  const child = writeProjectRevisionV2Sync({
    paths,
    planObject: facts.planObject,
    revision: {
      ...revisionV2WriteFrom(parent),
      parentRevisionHash: parentHash,
      planContentHash: facts.planContentHash,
      sourceSnapshotSetHash: facts.sourceSnapshotSetHash,
      workflowState: "READY_TO_FINALIZE",
      renderGraphHash: stored.graphHash,
      projectionReceiptHash: stored.projectionReceiptHash,
      authoritativeSidecars: {
        ...parent.authoritativeSidecars,
        ...facts.authoritativeSidecars,
        renderedCandidateMedia: input.expectedCandidateHash,
        autoEditRenderedTransitionV1: stored.evidenceHash,
      },
    },
  });
  return {
    childHash: child.revisionHash,
    record: renderedAdvanceRecord(
      parentHash, child.revisionHash, stored.evidenceHash),
  };
}

/** Append one exact rendered successor, or prove the current head already is it. */
export function advanceAutoEditRenderedRevisionSync(
  input: AutoEditGenesisExpectation,
  facts: AutoEditGenesisFacts,
  hooks: AutoEditRenderedTransitionHooks = {},
): AutoEditRenderedTransitionOutcome {
  const paths = producerAuthorityPaths(input.producerDir);
  const parentHash = resolveProducerAuthorityHeadSync(input.producerDir);
  const parent = revisionAt(paths, parentHash);
  if (unresolvedProducerIntentsSync(input.producerDir).length) {
    throw new Error("rendered successor is blocked by an unresolved edit intent");
  }
  if (matchesRenderedFacts(paths, parent, facts)) {
    assertStoredRenderedFacts(paths, parent, facts);
    return { status: "reused", revisionHash: parentHash };
  }
  const adoption = prepareLegacyCompatibilityAdoptionSync(
    paths, parentHash, parent, facts);
  const transitionFacts = adoption ? {
    ...facts,
    authoritativeSidecars: {
      ...facts.authoritativeSidecars,
      legacyCompatibilityShadowAdoptionV1: adoption,
    },
  } : facts;
  const staged = materializeTransition({
    input, paths, parentHash, parent, facts: transitionFacts,
  });
  hooks.after?.("after-materialized");
  try {
    publishProducerAdvanceSync(paths, staged.record);
  } catch (error) {
    if (!renderedAdvanceSelected(paths, staged.record)) throw error;
  }
  hooks.after?.("after-advance");
  if (resolveProducerAuthorityHeadSync(input.producerDir)
      !== staged.childHash) {
    throw new Error("rendered successor lost its parent compare-and-swap");
  }
  return { status: "advanced", revisionHash: staged.childHash };
}
