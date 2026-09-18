import {
  parseProjectRevision,
  type ProjectRevisionV2,
} from "@/lib/producer/contracts/project-revision";
import { sha256 } from "@/lib/producer/contracts/validation";
import {
  parseApprovalRecord,
  type ApprovalRecord,
} from "./auto-edit-approval";
import { approvalPath } from "./auto-edit-quality-artifacts";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  readAuthorityJsonSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";
import {
  assertRevisionPlanObjectSync,
  revisionV2WriteFrom,
  writeProjectRevisionV2Sync,
} from "./producer-plan-authority";
import {
  publishProducerAdvanceSync,
  resolveProducerApprovedHeadSync,
  resolveProducerAuthorityHeadSync,
  stageProducerApprovedHeadSync,
} from "./producer-revision-head";
import type { CurrentRenderGraphAuthority } from
  "./current-render-graph-authority";
import { storeQcPromotionObjectsSync } from
  "./producer-qc-promotion-objects";
import {
  bindProducerQcPromotionChildSync,
  prepareProducerQcPromotionIntentSync,
  type QcPromotionIntentExpectation,
} from "./producer-qc-promotion-intent";
import {
  qcPromotionAdvanceRecord,
  qcPromotionAdvanceSelectedSync,
} from "./producer-qc-promotion-advance";

export interface ProducerQcPromotionPreparation {
  producerDir: string;
  parentRevisionHash: string;
  expectedApprovedHead: string | null;
  mutablePaths: string[];
  intentId?: string;
}

export interface ProducerQcPromotionInput {
  preparation: ProducerQcPromotionPreparation;
  graph: CurrentRenderGraphAuthority;
  approval: ApprovalRecord;
}

export interface ProducerQcPromotionOutcome {
  status: "committed" | "replayed";
  childRevisionHash: string;
}
export interface ProducerQcPromotionHooks {
  after?: (
    boundary: "after-child-materialized" | "after-approved-head"
    | "after-advance",
  ) => void;
}

interface ApprovalAuthority {
  approval: ApprovalRecord;
  hash: string;
}

function revisionAt(
  paths: ProducerAuthorityPaths,
  hash: string,
): ProjectRevisionV2 {
  const revision = parseProjectRevision(
    assertObjectHashSync(paths.objects.revisions, hash));
  if (revision.schemaVersion !== 2) {
    throw new Error("QC promotion requires exact-plan ProjectRevisionV2");
  }
  if (!assertRevisionPlanObjectSync(paths, revision)) {
    throw new Error("QC promotion parent has no exact plan");
  }
  return revision;
}

/** Capture both working and retained-approved heads before moving live media. */
export function prepareProducerQcPromotionSync(
  producerDir: string,
  expectation: QcPromotionIntentExpectation,
): ProducerQcPromotionPreparation {
  const paths = producerAuthorityPaths(producerDir);
  const parentRevisionHash = resolveProducerAuthorityHeadSync(producerDir);
  const parent = revisionAt(paths, parentRevisionHash);
  const approval = parseApprovalRecord(expectation.approval);
  const renderedPlanHash =
    parent.authoritativeSidecars.renderedPlanFile ?? parent.planContentHash;
  if (!approval
      || approval.planHash !== renderedPlanHash
      || approval.manifestHash !== parent.manifestHash) {
    throw new Error("QC intent does not bind the working revision");
  }
  const staged = parent.authoritativeSidecars.stagedRenderGraphV1;
  if (staged && staged !== expectation.graphHash) {
    throw new Error("QC intent does not bind the staged render graph");
  }
  const expectedApprovedHead = resolveProducerApprovedHeadSync(producerDir);
  const intent = prepareProducerQcPromotionIntentSync(
    producerDir,
    parentRevisionHash,
    expectedApprovedHead,
    expectation,
  );
  return {
    producerDir,
    parentRevisionHash,
    expectedApprovedHead,
    mutablePaths: [paths.activeHead, paths.approvedHead],
    intentId: intent.intentId,
  };
}

function approvalAuthority(
  input: ProducerQcPromotionInput,
): ApprovalAuthority {
  const expected = parseApprovalRecord(input.approval);
  const value = readAuthorityJsonSync(
    approvalPath(input.preparation.producerDir));
  const observed = parseApprovalRecord(value);
  if (!expected || !observed) {
    throw new Error("published QC approval is malformed");
  }
  const hash = canonicalJsonSha256(value);
  if (hash !== canonicalJsonSha256(observed)
      || hash !== canonicalJsonSha256(expected)) {
    throw new Error("published QC approval differs from the approved record");
  }
  return { approval: observed, hash };
}

function graphAuthority(
  graph: CurrentRenderGraphAuthority,
): CurrentRenderGraphAuthority {
  return {
    graphHash: sha256(graph.graphHash, "approved current graph hash"),
    receiptHash: sha256(graph.receiptHash, "approved graph receipt hash"),
    activePointerHash: sha256(
      graph.activePointerHash, "approved graph pointer hash"),
    finalMediaHash: sha256(
      graph.finalMediaHash, "approved final media hash"),
  };
}

function approvedChild(
  paths: ProducerAuthorityPaths,
  input: ProducerQcPromotionInput,
  authority: ApprovalAuthority,
): { revision: ProjectRevisionV2; hash: string } {
  const parent = revisionAt(paths, input.preparation.parentRevisionHash);
  const graph = graphAuthority(input.graph);
  const renderedPlanHash =
    parent.authoritativeSidecars.renderedPlanFile ?? parent.planContentHash;
  if (renderedPlanHash !== authority.approval.planHash
      || parent.manifestHash !== authority.approval.manifestHash
      || graph.finalMediaHash !== authority.approval.finalHash) {
    throw new Error("QC approval does not bind the working revision and final");
  }
  const stagedGraph = parent.authoritativeSidecars.stagedRenderGraphV1;
  if (stagedGraph && stagedGraph !== graph.graphHash) {
    throw new Error("QC graph differs from the rendered working revision");
  }
  storeQcPromotionObjectsSync(paths, {
    producerDir: input.preparation.producerDir,
    graph,
    approval: authority.approval,
    approvalHash: authority.hash,
  });
  const plan = assertRevisionPlanObjectSync(paths, parent);
  if (!plan) throw new Error("QC promotion parent has no exact plan");
  const stored = writeProjectRevisionV2Sync({
    paths,
    planObject: plan,
    revision: {
      ...revisionV2WriteFrom(parent),
      parentRevisionHash: input.preparation.parentRevisionHash,
      workflowState: "QC_APPROVED",
      renderGraphHash: graph.graphHash,
      authoritativeSidecars: {
        ...parent.authoritativeSidecars,
        currentRenderGraphV1: graph.graphHash,
        currentRenderGraphReceiptV1: graph.receiptHash,
        currentRenderGraphActivePointerV1: graph.activePointerHash,
        approvedFinalMedia: graph.finalMediaHash,
        qcApprovalV2: authority.hash,
      },
    },
  });
  return { revision: stored.revision, hash: stored.revisionHash };
}

function advanceRecord(
  input: ProducerQcPromotionInput,
  childRevisionHash: string,
  approvalHash: string,
): ReturnType<typeof qcPromotionAdvanceRecord> {
  return qcPromotionAdvanceRecord({
    parentRevisionHash: input.preparation.parentRevisionHash,
    childRevisionHash,
    graphHash: input.graph.graphHash,
    graphReceiptHash: input.graph.receiptHash,
    approvalHash,
  });
}

function replayedPromotion(
  input: ProducerQcPromotionInput,
  childRevisionHash: string,
  activeRevisionHash: string,
): ProducerQcPromotionOutcome | null {
  if (activeRevisionHash !== childRevisionHash) return null;
  if (resolveProducerApprovedHeadSync(
    input.preparation.producerDir) !== childRevisionHash) {
    throw new Error("QC child is active without its approved-head binding");
  }
  return { status: "replayed", childRevisionHash };
}

/**
 * Stage APPROVED_HEAD, then publish the immutable parent advance as the final
 * fallible mutation. The enclosing promotion transaction restores the staged
 * pointer if publication definitively fails.
 */
export function commitProducerQcPromotionSync(
  input: ProducerQcPromotionInput,
  hooks: ProducerQcPromotionHooks = {},
): ProducerQcPromotionOutcome {
  const paths = producerAuthorityPaths(input.preparation.producerDir);
  const authority = approvalAuthority(input);
  const child = approvedChild(paths, input, authority);
  const record = advanceRecord(input, child.hash, authority.hash);
  const active = resolveProducerAuthorityHeadSync(
    input.preparation.producerDir);
  const replayed = replayedPromotion(input, child.hash, active);
  if (replayed) return replayed;
  if (input.preparation.intentId) {
    bindProducerQcPromotionChildSync(
      input.preparation.producerDir,
      input.preparation.intentId,
      child.hash,
      input.graph,
    );
  }
  hooks.after?.("after-child-materialized");
  if (active !== input.preparation.parentRevisionHash) {
    throw new Error("working head changed before QC promotion");
  }
  const approved = resolveProducerApprovedHeadSync(
    input.preparation.producerDir);
  if (approved !== input.preparation.expectedApprovedHead) {
    throw new Error("approved head changed before QC promotion");
  }
  stageProducerApprovedHeadSync(
    input.preparation.producerDir,
    input.preparation.expectedApprovedHead,
    child.hash,
  );
  hooks.after?.("after-approved-head");
  let reused = false;
  try {
    const published = publishProducerAdvanceSync(paths, record);
    reused = published.reused;
  } catch (error) {
    if (!qcPromotionAdvanceSelectedSync(paths, record)) throw error;
  }
  hooks.after?.("after-advance");
  return {
    status: reused ? "replayed" : "committed",
    childRevisionHash: child.hash,
  };
}
