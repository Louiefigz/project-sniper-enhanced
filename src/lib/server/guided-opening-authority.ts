import { GUIDED_OPENING_SCOPE, parseOpeningFrameRange, type OpeningBlockerCode, type PrepareGuidedOpeningV1 } from "@/lib/producer/contracts/guided-opening-v1";
import { PROPOSAL_PRESENTATION_POLICY } from "@/lib/producer/contracts/treatment-proposal-v3";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { objectValue } from "@/lib/producer/contracts/validation";
import { assertGuidedFrameBindings, proposalOccurrenceEvidence } from "./guided-proposal-bindings";
import { pinnedProposalFile } from "./guided-proposal-evidence";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { OPENING_REQUEST_LANES_SOURCE } from "./guided-opening-request-lanes";
import { hasPresenterMediaRequest, PRESENTER_OPENING_PROFILE_FILES } from "./guided-opening-profile";

export type OpeningReadiness = ReturnType<typeof readGuidedProposalReadiness>;
const REQUIRED = ["src/lib/producer/contracts/guided-opening-v1.ts", "src/lib/server/guided-opening-authority.ts",
  "src/lib/server/guided-opening.ts", "src/lib/server/guided-opening-store.ts", "src/lib/server/guided-proposal-bindings.ts", OPENING_REQUEST_LANES_SOURCE];

/** TS intake boundary only. No Python renderer/master-selection event is fabricated by this descriptor. */
export const OPENING_ADAPTER_BOUNDARY = Object.freeze({
  schemaVersion: 1, state: "unavailable", scope: "private-opening-renderer-not-implemented",
  requiredPicture: "same-qualified-full-program-base-and-global-timed-compositor",
  requiredAudio: "separately-held-source-float-v2-full-program-master-no-excerpt-normalization",
  sampleClockPolicy: "absolute-frame-ties-even-48000-v1", requiredMedia: "strict-decode-and-exact-picture-sample-clocks",
  requiredSelection: "actual-execution-return-event-plus-receipt-not-pointer-or-directory-scan",
  noApproval: true,
});

export function assertOpeningSubmission(proposal: OpeningReadiness, submission: Pick<PrepareGuidedOpeningV1,
  "expectedJournalHash" | "expectedToken" | "proposalReadinessHash" | "treatmentDraftRevisionHash">): void {
  if (proposal.sha256 !== submission.expectedJournalHash || proposal.job.token !== submission.expectedToken
      || proposal.readinessHash !== submission.proposalReadinessHash || !proposal.draftRevision
      || proposal.pointer.treatmentDraftRevisionHash !== submission.treatmentDraftRevisionHash || proposal.readiness.verdict !== "clean") {
    throw new Error("Opening preparation request names a stale or blocked treatment draft");
  }
}

export function openingImplementation(proposal: OpeningReadiness) {
  const cut = { ...proposal, receipt: proposal.cutReceipt };
  const required = hasPresenterMediaRequest(proposal.result?.proposal, proposal.result?.candidate ?? {})
    ? [...REQUIRED, ...PRESENTER_OPENING_PROFILE_FILES] : REQUIRED;
  return { schemaVersion: 1, scope: "current-pinned-ts-opening-admission-not-render-implementation",
    files: required.map((name) => ({ name, sha256: pinnedProposalFile(cut, name, true).sha256 })), adapter: OPENING_ADAPTER_BOUNDARY };
}

function repeatedSources(plan: Record<string, unknown>): boolean {
  const cuts = plan.cutTrack;
  if (!Array.isArray(cuts)) throw new Error("Opening lost its actual accepted cut track");
  return cuts.some((row, index) => cuts.slice(0, index).some((prior) => prior.sourceId === row.sourceId
    && Number(prior.start) < Number(row.end) && Number(row.start) < Number(prior.end)));
}

function unsupported(proposal: OpeningReadiness, bindings: ReturnType<typeof assertGuidedFrameBindings> | null) {
  const plan = proposal.result.candidate!, codes: OpeningBlockerCode[] = ["opening-renderer-unavailable"];
  if (!bindings) codes.push("legacy-presentation-unbound");
  if (bindings?.unboundInheritedGraphicIds.length) codes.push("inherited-graphics-unbound");
  if (Array.isArray(plan.captionsTrack) && plan.captionsTrack.length || objectValue(plan.captions ?? {}, "captions").burn === true) codes.push("caption-rendering-unqualified");
  if (plan.audioEnhance || plan.audioGain || Array.isArray(plan.transitions) && plan.transitions.some((row) => row.sfx)) codes.push("audio-treatment-unqualified");
  if (repeatedSources(plan)) codes.push("repeated-source-execution-unqualified");
  return codes;
}

/** Derive exact input from observed objects; caller cannot supply paths, timing, target or a media approval. */
export function buildOpeningAuthority(proposal: OpeningReadiness) {
  const result = proposal.result;
  if (result.proposal.schemaVersion === 9 || result.proposal.schemaVersion === 10) throw new Error("Native Shorts have no legacy opening authority");
  if (!proposal.draftRevision || proposal.readiness.verdict !== "clean" || !result.candidate || !result.range || result.blockers.length) throw new Error("Opening needs an actual clean isolated TREATMENT_DRAFT");
  let bindings: ReturnType<typeof assertGuidedFrameBindings> | null = null;
  if (result.proposal.schemaVersion !== 2) {
    if (canonicalJsonSha256(proposal.evidence.presentationPolicy) !== canonicalJsonSha256(PROPOSAL_PRESENTATION_POLICY)) throw new Error("Opening presentation policy changed");
    const inheritedCount = Array.isArray(proposal.plan.value.graphicsTrack) ? proposal.plan.value.graphicsTrack.length : 0;
    bindings = assertGuidedFrameBindings({ proposal: result.proposal, evidence: proposal.evidence, candidate: result.candidate, inheritedCount }, result.executionBindings);
  }
  const core = parseOpeningFrameRange(result.range.approval, proposal.evidence.totalFrames), review = parseOpeningFrameRange(result.range.review, proposal.evidence.totalFrames);
  if (core.startFrame !== 0 || review.startFrame !== 0 || core.endFrameExclusive > review.endFrameExclusive) throw new Error("Opening core/context no longer share the program origin");
  const input = { schemaVersion: 1, kind: "guided-opening-preparation-input", scope: GUIDED_OPENING_SCOPE,
    runId: proposal.fact.runId, previewAttempt: proposal.fact.previewAttempt, contextHash: proposal.fact.contextHash,
    cutDecisionHash: proposal.pointer.cutDecisionHash, acceptedRevisionHash: proposal.pointer.pictureLockedRevisionHash,
    requestHash: proposal.request.requestHash, pictureLockHash: proposal.request.pictureLockHash, projectionHash: proposal.request.projectionReceiptHash,
    sourceSetDigest: proposal.cutReceipt.sourceSetDigest, manifestHash: proposal.manifest.sha256, timelineMapHash: proposal.request.timelineMapHash,
    rawAdmissionHash: proposal.pointer.treatmentAdmissionHash, proposalHash: proposal.proposalHash, readinessHash: proposal.readinessHash,
    draftRevisionHash: proposal.pointer.treatmentDraftRevisionHash, candidatePlanHash: canonicalJsonSha256(result.candidate),
    frameBindingsHash: bindings ? canonicalJsonSha256(bindings) : null,
    occurrenceEvidenceHash: canonicalJsonSha256(proposalOccurrenceEvidence(proposal.evidence)),
    clockHash: proposal.clock.hash, generationStartedAt: proposal.generationStartedAt, frameRate: proposal.evidence.frameRate,
    totalFrames: proposal.evidence.totalFrames, target: proposal.evidence.target, core, review, adapter: OPENING_ADAPTER_BOUNDARY };
  return { input, bindings, blockerCodes: unsupported(proposal, bindings), implementation: openingImplementation(proposal) };
}
