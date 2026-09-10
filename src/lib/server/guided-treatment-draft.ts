import path from "node:path";
import { parseRenderGraphV1 } from "@/lib/producer/contracts/render-graph";
import { parseProjectRevisionV2 } from "@/lib/producer/contracts/project-revision";
import { proposalReadinessChecks } from "@/lib/producer/contracts/proposal-readiness-v1";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { planObjectContentHash } from "./auto-edit-authority";
import { autoEditProjectionReceipt } from "./producer-auto-edit-projection-authority";
import { producerAuthorityPaths, writeAuthorityObjectSync } from "./producer-authority-files";
import type { ReviewedProposalInput } from "./guided-proposal-review-packet";

/** Pure actual draft closure; a null graph output is an unrendered dependency, never a fake media receipt. */
function draftObjects(proposal: ReviewedProposalInput, reviewBundleHash: string) {
  const plan = proposal.result.candidate;
  if (!plan || proposal.result.blockers.length || !proposal.result.range) throw new Error("Only an unblocked reviewed proposal can have a treatment draft");
  const content = planObjectContentHash(plan);
  if (!content) throw new Error("Treatment draft has no actual plan content");
  // A draft exists only after readiness ran the deterministic full-plan gate bundle and it passed,
  // so that check is reported as executed here instead of being promised as still pending.
  const ledger = { schemaVersion: 3, kind: "guided-treatment-draft-ledger", requestHash: canonicalJsonSha256(proposal.submission),
    rawIntent: proposal.submission.rawIntent, clauses: proposal.result.proposal.clauses,
    proposalHash: proposal.proposalHash, reviewBundleHash, treatmentExecuted: false, ...proposalReadinessChecks(true) };
  const projection = autoEditProjectionReceipt({ planContentHash: content, manifestHash: proposal.manifest.sha256,
    sourceSnapshotSetHash: proposal.revision.sourceSnapshotSetHash, projection: proposal.projection });
  const graph = parseRenderGraphV1({ schemaVersion: 1, graphId: `guided-draft-${proposal.proposalHash.slice(0, 16)}`,
    toolchainHash: canonicalJsonSha256(proposal.job.ctx.pipeline), rootNodeId: "opening-preview-pending", nodes: [
      { nodeId: "accepted-cut", kind: "timeline-map", dependencies: [], frameRange: null,
        inputDigests: { acceptedRevision: proposal.pointer.pictureLockedRevisionHash, timeline: proposal.request.timelineMapHash },
        outputArtifactHash: proposal.revision.authoritativeSidecars.compatibilityTimelineProjectionV1 },
      { nodeId: "full-program-audio-pending", kind: "dialogue-stem", dependencies: ["accepted-cut"], frameRange: null,
        inputDigests: { proposal: proposal.proposalHash, plan: content }, outputArtifactHash: null },
      { nodeId: "opening-preview-pending", kind: "preview", dependencies: ["accepted-cut", "full-program-audio-pending"],
        frameRange: proposal.result.range.review, inputDigests: { proposal: proposal.proposalHash, plan: content, reviewBundle: reviewBundleHash }, outputArtifactHash: null },
    ] });
  const revision = parseProjectRevisionV2({ ...proposal.revision, schemaVersion: 2,
    parentRevisionHash: proposal.pointer.pictureLockedRevisionHash, planObjectHash: canonicalJsonSha256(plan), planContentHash: content,
    workflowState: "TREATMENT_DRAFT", requestLedgerHash: canonicalJsonSha256(ledger), renderGraphHash: canonicalJsonSha256(graph),
    projectionReceiptHash: canonicalJsonSha256(projection), authoritativeSidecars: { ...proposal.revision.authoritativeSidecars,
      rawTreatmentAdmission: proposal.pointer.treatmentAdmissionHash, treatmentProposal: proposal.proposalHash, proposalReviewBundle: reviewBundleHash,
      originalGenerationClock: proposal.clock.hash } });
  return { plan, ledger, graph, projection, revision };
}

/** Persist an isolated child object only. Never advances ACTIVE_HEAD, GENESIS or APPROVED_HEAD. */
export function storeGuidedTreatmentDraft(proposal: ReviewedProposalInput, reviewBundleHash: string): string {
  const paths = producerAuthorityPaths(proposal.job.ctx.dir), objects = draftObjects(proposal, reviewBundleHash);
  const put = (kind: "plans" | "requests" | "graphs" | "projections" | "revisions", value: unknown) => writeAuthorityObjectSync(paths.objects[kind], value).hash;
  put("plans", objects.plan); put("requests", objects.ledger); put("graphs", objects.graph); put("projections", objects.projection);
  return put("revisions", objects.revision);
}

/** Non-creating bounded closure check for every required child object and its accepted parent. */
export function readGuidedTreatmentDraft(proposal: ReviewedProposalInput, input: { hash: string; reviewBundleHash: string }) {
  const objects = draftObjects(proposal, input.reviewBundleHash), root = path.join(proposal.job.ctx.dir, ".sniper-authority-v1", "objects");
  const expected = canonicalJsonSha256(objects.revision);
  if (input.hash !== expected) throw new Error("Treatment draft does not bind this exact accepted cut/proposal/review");
  const verify = (kind: string, value: unknown) => {
    const hash = canonicalJsonSha256(value), observed = readCutPreviewObject(path.join(root, kind, `${hash}.json`));
    if (observed.sha256 !== hash || canonicalJsonSha256(observed.value) !== hash) throw new Error(`Treatment draft ${kind} closure changed`);
  };
  verify("plans", objects.plan); verify("requests", objects.ledger); verify("graphs", objects.graph);
  verify("projections", objects.projection); verify("revisions", objects.revision);
  return objects.revision;
}
