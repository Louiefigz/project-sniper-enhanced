/** Request-derived prior lanes only; V8 presenter execution remains explicitly fenced. */
import { objectValue } from "@/lib/producer/contracts/validation";
import { MANUAL_SHORT_PROFILE, isManualMediaProfile } from "@/lib/producer/contracts/guided-media-profile";
import { assertGuidedPresenterProfile, isPresenterOpeningProfile } from "@/lib/producer/contracts/guided-presenter-profile";
import { parseCurrentTreatmentProposal, proposalV8ValidationView, type CurrentTreatmentProposal } from "@/lib/producer/contracts/treatment-proposal-v8";
import { proposalV7ValidationView } from "@/lib/producer/contracts/treatment-proposal-v7";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { assertGuidedReframeCandidate } from "./guided-proposal-reframe";
import { assertGuidedMusicCandidate, guidedMusicPolicy } from "./guided-proposal-music";
import { assertGuidedPresenterCandidate, guidedPresenterPolicy } from "./guided-proposal-presenter";
import { assertGuidedFrameBindings, type GuidedFrameBindings } from "./guided-proposal-bindings";
import type { ProposalEvidence } from "./guided-proposal-evidence";

export const OPENING_REQUEST_LANES_SOURCE = "src/lib/server/guided-opening-request-lanes.ts";
export interface OpeningProposalContext { proposal: CurrentTreatmentProposal; evidence: ProposalEvidence }
interface NoPresenterInput {
  proposal: unknown; evidence: unknown; candidate: unknown; bindings: unknown;
}
interface LaneInput {
  accepted: Record<string, unknown>; candidate: Record<string, unknown>;
  manifest: Record<string, unknown>; packet: Record<string, unknown>; profile: string;
}

/** V8 without new work retains actual8/2 identity; blank layout properties are not no-ops. */
export function assertNoPresenterOpening(input: NoPresenterInput): void {
  if ([2, 3, 4, 5, 6, 7].includes(objectValue(input.proposal, "opening proposal").schemaVersion as number)) return;
  const proposal = parseCurrentTreatmentProposal(input.proposal);
  if (proposal.schemaVersion !== 8) return;
  if (proposal.operations.some(row => row.type === "presenter-layout-window")
      || Object.hasOwn(objectValue(input.candidate, "V8 candidate"), "presenterLayouts")) {
    throw new Error("V8 presenter windows require their own connected media profile; no readiness critic or legacy render fallback");
  }
  const evidence = objectValue(input.evidence, "V8 opening evidence"), bindings = objectValue(input.bindings, "V8 frame bindings");
  if (evidence.schemaVersion !== 8 || bindings.schemaVersion !== 2
      || !Array.isArray(bindings.presenterLayouts) || bindings.presenterLayouts.length !== 0) {
    throw new Error("V8 no-presenter opening requires actual evidence8 and bindings2 with an exact empty presenter list");
  }
}

/** V2 is identified by actual request/evidence, never accepted from a version flag alone. */
export function assertOpeningBindingContext(input: { plan: Record<string, unknown>; bindings: GuidedFrameBindings;
  proposal?: CurrentTreatmentProposal; evidence?: ProposalEvidence }): void {
  if (input.bindings.schemaVersion === 1 && input.proposal?.schemaVersion !== 8) return;
  if (input.proposal?.schemaVersion !== 8 || input.evidence?.schemaVersion !== 8) {
    throw new Error("Opening bindings2 require their actual V8 proposal and evidence context");
  }
  assertNoPresenterOpening({ proposal: input.proposal, evidence: input.evidence,
    candidate: input.plan, bindings: input.bindings });
  assertGuidedFrameBindings({ proposal: input.proposal, evidence: input.evidence,
    candidate: input.plan, inheritedCount: input.bindings.unboundInheritedGraphicIds.length }, input.bindings);
}

function assertManualInput(input: LaneInput, proposal: CurrentTreatmentProposal): void {
  const { accepted: plan, candidate, profile } = input;
  const cropView = proposal.schemaVersion === 7 ? proposalV7ValidationView(proposal) : proposal;
  const authoredCrop = cropView.schemaVersion === 6 && cropView.operations.some(item => item.type === "reframe-manual-short");
  if (authoredCrop) {
    if (!isManualMediaProfile(profile) || profile === MANUAL_SHORT_PROFILE) {
      throw new Error("V6 crop requires the explicit captioned manual media profile");
    }
    assertGuidedReframeCandidate(plan, candidate, cropView);
    return;
  }
  const keys = profile === MANUAL_SHORT_PROFILE ? ["reframe", "captions"] : ["reframe"];
  if (isManualMediaProfile(profile) && keys.some(key => canonicalJsonSha256(plan[key]) !== canonicalJsonSha256(candidate[key]))) {
    throw new Error("Opening manual crop/captions differ from the submitted accepted candidate");
  }
}

function assertMusicInput(input: LaneInput, proposal: CurrentTreatmentProposal, actualVersion: number): void {
  const { accepted, candidate, packet, manifest } = input;
  if (proposal.schemaVersion === 7) {
    const evidence = objectValue(packet.evidence, "music evidence");
    if (evidence.schemaVersion !== actualVersion || canonicalJsonSha256(evidence.musicPolicy) !== canonicalJsonSha256(guidedMusicPolicy(accepted, manifest))) {
      throw new Error(`Opening music evidence differs from its exact V${actualVersion} accepted target and manifest`);
    }
    assertGuidedMusicCandidate({ accepted, candidate, manifest, proposal });
    return;
  }
  if (Object.hasOwn(accepted, "music") !== Object.hasOwn(candidate, "music")
      || Object.hasOwn(accepted, "music") && canonicalJsonSha256(accepted.music) !== canonicalJsonSha256(candidate.music)) {
    throw new Error("Historical proposal cannot add, remove or change accepted music");
  }
}

/** Keep documents/candidate untouched; only local prior-lane arguments use an older validation view. */
export function assertOpeningRequestLanes(input: LaneInput): void {
  const proposal = parseCurrentTreatmentProposal(input.packet.proposal);
  if (isPresenterOpeningProfile(input.profile)) {
    const result = assertGuidedPresenterProfile({ accepted: input.accepted, candidate: input.candidate, manifest: input.manifest,
      proposal, evidence: objectValue(input.packet.evidence, "presenter evidence") as unknown as ProposalEvidence,
      bindings: input.packet.executionBindings });
    if (input.profile !== result.profile) throw new Error("Presenter request differs from the exact declared media profile");
    return;
  }
  if (proposal.schemaVersion === 8) {
    assertNoPresenterOpening({ proposal, candidate: input.candidate,
      evidence: input.packet.evidence, bindings: input.packet.executionBindings });
    const evidence = objectValue(input.packet.evidence, "V8 opening evidence") as unknown as ProposalEvidence;
    if (canonicalJsonSha256(evidence.presenterPolicy) !== canonicalJsonSha256(guidedPresenterPolicy(input.accepted, input.manifest))) {
      throw new Error("Opening presenter policy differs from original accepted target and manifest");
    }
    assertGuidedPresenterCandidate({ accepted: input.accepted, candidate: input.candidate,
      manifest: input.manifest, proposal, evidence });
  }
  const prior = proposal.schemaVersion === 8 ? proposalV8ValidationView(proposal) : proposal;
  assertManualInput(input, prior);
  assertMusicInput(input, prior, proposal.schemaVersion);
}
