import path from "node:path";
import { parseProjectRevision, type ProjectRevisionV2 } from
  "@/lib/producer/contracts/project-revision";
import { parseProjectionReceiptV1 } from
  "@/lib/producer/contracts/projection-receipt";
import { parseRenderGraphV1 } from
  "@/lib/producer/contracts/render-graph";
import { parseApprovalRecord } from "./auto-edit-approval";
import { approvalPath } from "./auto-edit-quality-artifacts";
import { planObjectContentHash } from "./auto-edit-authority";
import { canonicalJsonSha256, fileSha256 } from "./auto-edit-hash";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  readApprovedHeadSync,
  readAuthorityJsonSync,
} from "./producer-authority-files";
import { observeCurrentRenderGraphAuthoritySync } from
  "./current-render-graph-authority";
import { assertRevisionPlanObjectSync } from
  "./producer-plan-authority";
import type { ProducerQcPromotionIntentV1 } from
  "./producer-qc-promotion-intent-model";
import { resolveProducerAuthorityHeadSync } from
  "./producer-revision-head";

function exactRevision(
  producerDir: string,
  intent: ProducerQcPromotionIntentV1,
): ProjectRevisionV2 {
  const paths = producerAuthorityPaths(producerDir);
  if (resolveProducerAuthorityHeadSync(producerDir)
      !== intent.childRevisionHash
      || readApprovedHeadSync(paths) !== intent.childRevisionHash) {
    throw new Error("QC child heads are not selected");
  }
  const revision = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, intent.childRevisionHash!));
  const plan = assertRevisionPlanObjectSync(paths, revision);
  if (revision.schemaVersion !== 2 || !plan
      || planObjectContentHash(plan) !== revision.planContentHash
      || revision.parentRevisionHash !== intent.parentRevisionHash
      || revision.workflowState !== "QC_APPROVED"
      || (revision.authoritativeSidecars.renderedPlanFile
        ?? revision.planContentHash) !== intent.intendedPlanHash
      || revision.manifestHash !== intent.intendedManifestHash
      || revision.renderGraphHash !== intent.intendedGraphHash
      || revision.authoritativeSidecars.currentRenderGraphV1
        !== intent.intendedGraphHash
      || revision.authoritativeSidecars.currentRenderGraphReceiptV1
        !== intent.graphReceiptHash
      || revision.authoritativeSidecars.currentRenderGraphActivePointerV1
        !== intent.graphPointerHash
      || revision.authoritativeSidecars.qcApprovalV2
        !== intent.intendedApprovalHash
      || revision.authoritativeSidecars.approvedFinalMedia
        !== intent.intendedFinalHash) {
    throw new Error("QC child revision differs from its durable intent");
  }
  return revision;
}

function exactStoredObjects(
  producerDir: string,
  intent: ProducerQcPromotionIntentV1,
  revision: ProjectRevisionV2,
): void {
  const paths = producerAuthorityPaths(producerDir);
  assertObjectHashSync(paths.objects.requests, revision.requestLedgerHash);
  const graph = parseRenderGraphV1(assertObjectHashSync(
    paths.objects.graphs, intent.intendedGraphHash));
  if (!revision.projectionReceiptHash) {
    throw new Error("QC child projection is missing");
  }
  const projection = parseProjectionReceiptV1(assertObjectHashSync(
    paths.objects.projections, revision.projectionReceiptHash));
  const root = graph.nodes.find((node) => node.nodeId === graph.rootNodeId);
  if (projection.canonicalPlanHash !== revision.planContentHash
      || projection.manifestHash !== revision.manifestHash
      || projection.sourceSnapshotSetHash !== revision.sourceSnapshotSetHash
      || root?.inputDigests["final.plan"] !== revision.planContentHash) {
    throw new Error("QC child immutable objects bind foreign inputs");
  }
  assertObjectHashSync(paths.objects.receipts, intent.graphReceiptHash!);
  assertObjectHashSync(paths.objects.receipts, intent.graphPointerHash!);
}

function exactLiveState(
  producerDir: string,
  intent: ProducerQcPromotionIntentV1,
): void {
  const paths = producerAuthorityPaths(producerDir);
  const approval = parseApprovalRecord(assertObjectHashSync(
    paths.objects.receipts, intent.intendedApprovalHash));
  const liveApproval = parseApprovalRecord(
    readAuthorityJsonSync(approvalPath(producerDir)));
  if (!approval || !liveApproval
      || canonicalJsonSha256(liveApproval) !== intent.intendedApprovalHash
      || fileSha256(path.join(producerDir, "final.mp4"))
        !== intent.intendedFinalHash) {
    throw new Error("QC child live approval or final differs");
  }
  const graph = observeCurrentRenderGraphAuthoritySync({
    producerDir,
    expectedGraphHash: intent.intendedGraphHash,
    expectedFinalHash: intent.intendedFinalHash,
  });
  if (graph.receiptHash !== intent.graphReceiptHash
      || graph.activePointerHash !== intent.graphPointerHash) {
    throw new Error("QC child live graph differs");
  }
}

/** True only for the fully selected, fully re-opened child named by intent. */
export function qcPromotionExactChildSelectedSync(
  producerDir: string,
  intent: ProducerQcPromotionIntentV1,
): boolean {
  if (intent.phase !== "child-materialized"
      || !intent.childRevisionHash
      || !intent.graphReceiptHash
      || !intent.graphPointerHash) return false;
  try {
    const revision = exactRevision(producerDir, intent);
    exactStoredObjects(producerDir, intent, revision);
    exactLiveState(producerDir, intent);
    return true;
  } catch {
    return false;
  }
}
