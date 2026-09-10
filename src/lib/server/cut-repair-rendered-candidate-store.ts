import path from "node:path";
import type { CutRepairPreparationPackageV1 } from
  "@/lib/producer/contracts/cut-repair-preparation";
import type { CutRepairReviewActionV1 } from
  "@/lib/producer/contracts/cut-repair-review-transition";
import {
  parseCutRepairRenderedCandidateV1,
  type CutRepairRenderedCandidateV1,
} from "@/lib/producer/contracts/cut-repair-rendered-candidate";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import type { CutRepairPreparedRender } from
  "./cut-repair-prepared-render-authority";
import { preparedStagingPath } from "./cut-repair-preparation-media";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  publishImmutableAuthorityJsonSync,
  readAuthorityJsonSync,
  writeAuthorityObjectSync,
} from "./producer-authority-files";

interface StageCandidateInput {
  producerDir: string;
  action: CutRepairReviewActionV1;
  render: CutRepairPreparedRender;
}

export interface StagedCutRepairRenderedCandidate {
  descriptor: CutRepairRenderedCandidateV1;
  descriptorHash: string;
  descriptorPath: string;
}

function descriptorValue(
  action: CutRepairReviewActionV1,
  render: CutRepairPreparedRender,
): CutRepairRenderedCandidateV1 {
  return parseCutRepairRenderedCandidateV1({
    schemaVersion: 1,
    kind: "cut-repair-rendered-plan-candidate",
    status: "candidate-proved",
    operationHash: action.operationHash,
    reviewPlanObjectHash: action.reviewPlanObjectHash,
    reviewPlanContentHash: action.reviewPlanContentHash,
    reviewTimelineMapHash: action.reviewTimelineMapHash,
    reviewRenderGraphHash: action.reviewRenderGraphHash,
    reviewRenderGraphReceiptHash: render.graphReceiptHash,
    reviewRenderGraphCandidatePointerHash: render.candidatePointerHash,
    candidatePath: render.candidatePath,
    candidateSha256: render.candidateSha256,
  });
}

function assertPackageBinding(
  descriptor: CutRepairRenderedCandidateV1,
  value: CutRepairPreparationPackageV1,
): void {
  const action = value.proposedReviewAction;
  if (descriptor.operationHash !== action.operationHash
      || descriptor.reviewPlanObjectHash !== action.reviewPlanObjectHash
      || descriptor.reviewPlanContentHash !== action.reviewPlanContentHash
      || descriptor.reviewTimelineMapHash !== action.reviewTimelineMapHash
      || descriptor.reviewRenderGraphHash !== action.reviewRenderGraphHash
      || descriptor.reviewRenderGraphReceiptHash
        !== value.reviewRenderGraphReceiptHash
      || descriptor.reviewRenderGraphCandidatePointerHash
        !== value.reviewRenderGraphCandidatePointerHash
      || descriptor.candidatePath !== value.reviewCandidatePath
      || descriptor.candidateSha256 !== value.reviewCandidateMediaSha256) {
    throw new Error("cut repair rendered candidate descriptor is stale");
  }
}

/** Publish the immutable full-plan identity consumed by automated/operator QC. */
export function stageCutRepairRenderedCandidateSync(
  input: StageCandidateInput,
): StagedCutRepairRenderedCandidate {
  const descriptor = descriptorValue(input.action, input.render);
  const descriptorPath = preparedStagingPath(
    input.producerDir,
    path.join(
      path.dirname(input.render.candidatePath),
      "cut-repair-rendered-candidate.json",
    ),
    "cut repair candidate descriptor",
  );
  publishImmutableAuthorityJsonSync(descriptorPath, descriptor);
  const observed = readAuthorityJsonSync(descriptorPath);
  const descriptorHash = canonicalJsonSha256(observed);
  const paths = producerAuthorityPaths(input.producerDir);
  const stored = writeAuthorityObjectSync(
    paths.objects.cutRepairs, observed);
  if (descriptorHash !== stored.hash
      || descriptorHash !== canonicalJsonSha256(descriptor)) {
    throw new Error("cut repair candidate descriptor changed identity");
  }
  return { descriptor, descriptorHash, descriptorPath };
}

/** Restore and rebind the exact descriptor before any QC producer consumes it. */
export function verifyCutRepairRenderedCandidateSync(
  producerDir: string,
  value: CutRepairPreparationPackageV1,
): void {
  const descriptorPath = preparedStagingPath(
    producerDir,
    value.reviewCandidateDescriptorPath,
    "cut repair candidate descriptor",
  );
  const paths = producerAuthorityPaths(producerDir);
  const descriptor = parseCutRepairRenderedCandidateV1(
    assertObjectHashSync(
      paths.objects.cutRepairs, value.reviewCandidateDescriptorHash));
  if (canonicalJsonSha256(descriptor)
      !== value.reviewCandidateDescriptorHash) {
    throw new Error("cut repair candidate descriptor changed identity");
  }
  assertPackageBinding(descriptor, value);
  publishImmutableAuthorityJsonSync(descriptorPath, descriptor);
  if (canonicalJsonSha256(readAuthorityJsonSync(descriptorPath))
      !== value.reviewCandidateDescriptorHash) {
    throw new Error("cut repair staged candidate descriptor was substituted");
  }
}
