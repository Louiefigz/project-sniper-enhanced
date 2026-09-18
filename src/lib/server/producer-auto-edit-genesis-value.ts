import type { CompatibilityTimelineProjectionV1 } from
  "@/app/api/producer/auto-edit/compatibility-timeline-projection";
import type { ProjectionReceiptV1 } from
  "@/lib/producer/contracts/projection-receipt";
import type { RenderGraphV1 } from
  "@/lib/producer/contracts/render-graph";
import type { AutoEditGenesisFacts } from
  "./producer-auto-edit-genesis-facts";
import type { CompatibilityShadowLock } from
  "./producer-revision-shadow-lock";
import type { StagedRenderGraphAuthority } from
  "./staged-render-graph-authority";

interface AutoEditGenesisValueInput {
  planObject: Record<string, unknown>;
  planContentHash: string;
  planFileHash: string;
  manifestHash: string;
  sourceSnapshotSetHash: string;
  sourceSetAdmissionReceipt: string;
  canvasProfileHash: string;
  destinationProfileHashes: string[];
  lock: CompatibilityShadowLock;
  graph: RenderGraphV1;
  graphReceipt: Record<string, unknown>;
  candidatePointer: Record<string, unknown>;
  staged: StagedRenderGraphAuthority;
  projection: CompatibilityTimelineProjectionV1;
  projectionReceipt: ProjectionReceiptV1;
}

/** Assemble the closed fact value after every source has been reverified. */
export function autoEditGenesisValue(
  input: AutoEditGenesisValueInput,
): AutoEditGenesisFacts {
  return {
    planObject: input.planObject,
    planContentHash: input.planContentHash,
    planFileHash: input.planFileHash,
    manifestHash: input.manifestHash,
    sourceSnapshotSetHash: input.sourceSnapshotSetHash,
    transcriptTimingHash: input.lock.transcriptDigest,
    timelineMapHash: input.lock.timelineMapHash,
    canvasProfileHash: input.canvasProfileHash,
    destinationProfileHashes: input.destinationProfileHashes,
    pictureLockHash: input.lock.hash,
    renderGraph: input.graph,
    renderGraphReceipt: input.graphReceipt,
    renderGraphCandidatePointer: input.candidatePointer,
    projection: input.projection,
    projectionReceipt: input.projectionReceipt,
    authoritativeSidecars: {
      compatibilityLock: input.lock.hash,
      cutApprovalReceipt: input.lock.cutApprovalReceiptHash,
      cutReviewApprovalReceipt: input.lock.cutReviewApprovalReceiptHash,
      sourceSetAdmissionReceipt: input.sourceSetAdmissionReceipt,
      stagedRenderGraphV1: input.staged.graphHash,
      stagedRenderGraphReceiptV1: input.staged.receiptHash,
      stagedRenderGraphCandidatePointerV1: input.staged.candidatePointerHash,
      compatibilityTimelineProjectionV1:
        input.projectionReceipt.projectionHash,
      renderedPlanFile: input.planFileHash,
    },
  };
}
