import type { CutRepairPreparationPackageV1 } from
  "@/lib/producer/contracts/cut-repair-preparation";
import type { CutRepairPicturePlanAuthorityV1 } from
  "@/lib/producer/contracts/cut-repair-picture-plan-authority";
import type { ProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import { parseRenderGraphV1 } from
  "@/lib/producer/contracts/render-graph";
import { assertCutRepairSurgicalRenderGraph } from
  "@/lib/producer/contracts/cut-repair-surgical-render-graph";
import { surgicalParentRenderAuthorityHashSync } from
  "./cut-repair-surgical-parent-authority";

export interface SurgicalPreparationReopen {
  producerDir: string;
  parent: ProjectRevision;
  graph: unknown;
  plan: Record<string, unknown>;
  packageValue: CutRepairPreparationPackageV1;
  pictureAuthority: CutRepairPicturePlanAuthorityV1 | null;
}

/** Reopen either the legacy full graph or the exact picture terminal. */
export function verifyCutRepairPreparationReviewGraphSync(
  input: SurgicalPreparationReopen,
): void {
  if (!input.pictureAuthority) {
    parseRenderGraphV1(input.graph);
    return;
  }
  const action = input.packageValue.proposedReviewAction;
  assertCutRepairSurgicalRenderGraph({
    graph: input.graph,
    plan: input.plan,
    planContentHash: action.reviewPlanContentHash,
    operation: action.operation,
    operationHash: action.operationHash,
    pictureAuthority: input.pictureAuthority,
    childTimelineMapHash: action.reviewTimelineMapHash,
    fragmentReceipt: input.packageValue.fragmentReceipt,
    compositeReceipt: input.packageValue.compositeReceipt,
    candidateHash: input.packageValue.reviewCandidateMediaSha256,
    parentRenderAuthorityHash: surgicalParentRenderAuthorityHashSync(
      input.producerDir, input.parent, input.packageValue),
  });
}
