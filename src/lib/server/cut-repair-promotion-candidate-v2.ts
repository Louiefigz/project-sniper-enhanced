import type { CutRepairPreparationPackageV1 } from
  "@/lib/producer/contracts/cut-repair-preparation";
import { parseCutRepairRenderedCandidateV1 } from
  "@/lib/producer/contracts/cut-repair-rendered-candidate";
import type { CutRepairRenderedCandidateV1 } from
  "@/lib/producer/contracts/cut-repair-rendered-candidate";
import type { ProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import { objectValue } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { validateCutRepairCandidateV1 } from
  "./producer-cut-repair-candidate-v1";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "./producer-authority-files";

interface CandidateUpgradeInput {
  producerDir: string;
  preparation: CutRepairPreparationPackageV1;
  reviewRevision: ProjectRevision;
  diagnosticCandidate: unknown;
}

function hashes(candidate: Record<string, unknown>) {
  return {
    fragment: canonicalJsonSha256(
      objectValue(candidate.fragmentReceipt, "fragment receipt")),
    composite: canonicalJsonSha256(
      objectValue(candidate.compositeReceipt, "composite receipt")),
    pictureLock: canonicalJsonSha256(
      objectValue(candidate.childPictureLock, "child picture lock")),
    supersession: canonicalJsonSha256(
      objectValue(candidate.supersessionReceipt, "supersession receipt")),
    caption: canonicalJsonSha256(
      objectValue(candidate.captionRevalidation, "caption revalidation")),
    palmier: canonicalJsonSha256(
      objectValue(candidate.palmierDisposition, "Palmier disposition")),
    invariant: canonicalJsonSha256(
      objectValue(candidate.invariantProof, "invariant proof")),
    candidate: canonicalJsonSha256(candidate),
  };
}

function validationRevision(
  revision: ProjectRevision,
  values: ReturnType<typeof hashes>,
): ProjectRevision {
  return {
    ...revision,
    authoritativeSidecars: {
      ...revision.authoritativeSidecars,
      pictureLock: values.pictureLock,
      pictureLockSupersession: values.supersession,
      cutRepairFragmentReceipt: values.fragment,
      cutRepairCompositeReceipt: values.composite,
      cutRepairInvariantProof: values.invariant,
      cutRepairCandidate: values.candidate,
      captionRepairRevalidation: values.caption,
      palmierCutRepairDisposition: values.palmier,
    },
  };
}

function assertPreparation(
  preparation: CutRepairPreparationPackageV1,
  candidate: Record<string, unknown>,
  rendered: CutRepairRenderedCandidateV1,
): void {
  const action = preparation.proposedReviewAction;
  if (canonicalJsonSha256(candidate.fragmentReceipt)
        !== canonicalJsonSha256(preparation.fragmentReceipt)
      || canonicalJsonSha256(candidate.compositeReceipt)
        !== canonicalJsonSha256(preparation.compositeReceipt)
      || canonicalJsonSha256(rendered)
        !== preparation.reviewCandidateDescriptorHash
      || rendered.operationHash !== action.operationHash
      || rendered.reviewPlanObjectHash !== action.reviewPlanObjectHash
      || rendered.reviewPlanContentHash !== action.reviewPlanContentHash
      || rendered.reviewTimelineMapHash !== action.reviewTimelineMapHash
      || rendered.reviewRenderGraphHash !== action.reviewRenderGraphHash
      || rendered.candidateSha256
        !== preparation.reviewCandidateMediaSha256) {
    throw new Error(
      "promotion candidate does not reuse the exact prepared evidence");
  }
}

function invariant(
  candidate: Record<string, unknown>,
  renderedHash: string,
  terminalSha256: string,
) {
  const values = hashes(candidate);
  const caption = objectValue(
    candidate.captionRevalidation, "caption revalidation");
  return {
    schemaVersion: 2,
    kind: "cut-repair-invariant-proof",
    operationHash: candidate.operationHash,
    fragmentReceiptHash: values.fragment,
    childPictureLockHash: values.pictureLock,
    supersessionHash: values.supersession,
    palmierDispositionHash: values.palmier,
    captionRevalidationHash: caption.revalidationHash,
    diagnosticCompositeReceiptHash: values.composite,
    renderedCandidateHash: renderedHash,
    terminalRenderedPlanProved: true,
    terminalCandidateSha256: terminalSha256,
    totalOutputFramesPreserved: true,
  };
}

/** Replace the diagnostic terminal with the exact rendered-plan descriptor. */
export function buildCutRepairPromotionCandidateV2Sync(
  input: CandidateUpgradeInput,
): Record<string, unknown> {
  const candidate = objectValue(
    input.diagnosticCandidate, "diagnostic cut repair candidate");
  const values = hashes(candidate);
  validateCutRepairCandidateV1(
    candidate,
    input.preparation.proposedReviewAction.operationHash,
    validationRevision(input.reviewRevision, values),
    values.invariant,
  );
  const paths = producerAuthorityPaths(input.producerDir);
  const rendered = parseCutRepairRenderedCandidateV1(assertObjectHashSync(
    paths.objects.cutRepairs,
    input.preparation.reviewCandidateDescriptorHash,
  ));
  const renderedHash = canonicalJsonSha256(rendered);
  assertPreparation(input.preparation, candidate, rendered);
  const proof = invariant(
    candidate, renderedHash, rendered.candidateSha256);
  return {
    ...candidate,
    schemaVersion: 2,
    renderedCandidate: rendered,
    renderedCandidateHash: renderedHash,
    invariantProof: proof,
    invariantProofHash: canonicalJsonSha256(proof),
  };
}
