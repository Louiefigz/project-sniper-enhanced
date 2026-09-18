import { canonicalJsonSha256 } from "./auto-edit-hash";
import { objectValue, stringValue } from "@/lib/producer/contracts/validation";
import type { TreatmentProposalV3, GraphicPresentationV1 } from "@/lib/producer/contracts/treatment-proposal-v3";
import type { TreatmentProposalV4 } from "@/lib/producer/contracts/treatment-proposal-v4";
import type { TreatmentProposalV5 } from "@/lib/producer/contracts/treatment-proposal-v5";
import type { TreatmentProposalV6 } from "@/lib/producer/contracts/treatment-proposal-v6";
import type { TreatmentProposalV7 } from "@/lib/producer/contracts/treatment-proposal-v7";
import type { TreatmentProposalV8 } from "@/lib/producer/contracts/treatment-proposal-v8";
import { guidedPresenterWindows, type GuidedPresenterWindow } from "./guided-proposal-presenter";
import type { ProposalEvidence } from "./guided-proposal-evidence";

export interface GuidedGraphicFrameBinding {
  graphicId: string; operationIndex: number; order: number;
  startFrame: number; endFrameExclusive: number;
  presentation: GraphicPresentationV1; entryHash: string;
}
export interface GuidedFrameBindingsV1 {
  schemaVersion: 1; kind: "guided-frame-presentation-bindings";
  scope: "controller-frames-and-declared-presentation-not-rendered-proof";
  frameRate: string; totalFrames: number; targetHash: string; candidatePlanHash: string;
  occurrenceEvidenceHash: string; graphics: GuidedGraphicFrameBinding[]; unboundInheritedGraphicIds: string[];
}
/** V8 keeps presenter windows distinct from catalog graphics and historical V1 receipts. */
export interface GuidedFrameBindingsV2 extends Omit<GuidedFrameBindingsV1, "schemaVersion"> {
  schemaVersion: 2; presenterLayouts: GuidedPresenterWindow[];
}
export type GuidedFrameBindings = GuidedFrameBindingsV1 | GuidedFrameBindingsV2;

/** One cross-language occurrence projection: anchors and segment occurrence identity are inseparable. */
export function proposalOccurrenceEvidence(evidence: ProposalEvidence) {
  return { anchors: evidence.anchors, occurrences: evidence.occurrences, segments: evidence.segments };
}

/** Preserve integer controller ranges outside the legacy seconds-only render plan. No new plan fields. */
export function buildGuidedFrameBindings(input: {
  proposal: TreatmentProposalV3 | TreatmentProposalV4 | TreatmentProposalV5 | TreatmentProposalV6 | TreatmentProposalV7 | TreatmentProposalV8;
  evidence: ProposalEvidence; candidate: Record<string, unknown>; inheritedCount: number;
}): GuidedFrameBindings {
  const { proposal, evidence, candidate, inheritedCount } = input;
  if (!Array.isArray(candidate.graphicsTrack) || candidate.graphicsTrack.length > 128) throw new Error("Unbounded candidate graphics cannot receive exact frame bindings");
  const track = candidate.graphicsTrack;
  let index = inheritedCount;
  const graphics = proposal.operations.flatMap((operation, operationIndex) => {
    if (operation.type !== "catalog-graphic") return [];
    if (!operation.presentation) throw new Error("Graphic presentation is missing");
    const order = index++, entry = objectValue(track[index - 1], "candidate graphic");
    const graphicId = stringValue(entry.id, "graphic id", 200);
    if (entry.anchor !== operation.presentation.anchor) throw new Error("Candidate graphic differs from explicit presentation");
    return [{ graphicId, operationIndex, order, startFrame: evidence.anchors[operation.startAnchor!],
      endFrameExclusive: evidence.anchors[operation.endAnchorExclusive!], presentation: operation.presentation, entryHash: canonicalJsonSha256(entry) }];
  });
  if (index !== track.length) throw new Error("Candidate graphics lack exact operation coverage");
  const unboundInheritedGraphicIds = track.slice(0, inheritedCount).map((value) =>
    stringValue(objectValue(value, "inherited graphic").id, "inherited graphic id", 200));
  const common = { kind: "guided-frame-presentation-bindings" as const,
    scope: "controller-frames-and-declared-presentation-not-rendered-proof" as const, frameRate: evidence.frameRate,
    totalFrames: evidence.totalFrames, targetHash: canonicalJsonSha256(evidence.target), candidatePlanHash: canonicalJsonSha256(candidate),
    occurrenceEvidenceHash: canonicalJsonSha256(proposalOccurrenceEvidence(evidence)),
    graphics, unboundInheritedGraphicIds };
  if (proposal.schemaVersion !== 8) return { schemaVersion: 1, ...common };
  const presenterLayouts = guidedPresenterWindows(proposal, evidence);
  if (presenterLayouts.length && canonicalJsonSha256(candidate.presenterLayouts) !== canonicalJsonSha256(presenterLayouts)) {
    throw new Error("V8 presenter bindings differ from actual requested frame/source/layout windows");
  }
  if (!presenterLayouts.length && Object.hasOwn(candidate, "presenterLayouts")) {
    throw new Error("Inherited presenter layouts have no fresh V8 execution bindings; explicit revision is required");
  }
  return { schemaVersion: 2, ...common, presenterLayouts };
}

/** No float-to-frame reconstruction, entry omission or forged presentation may enter opening preparation. */
export function assertGuidedFrameBindings(input: Parameters<typeof buildGuidedFrameBindings>[0], value: unknown): GuidedFrameBindings {
  const expected = buildGuidedFrameBindings(input);
  if (canonicalJsonSha256(value) !== canonicalJsonSha256(expected)) throw new Error("Stored exact-frame/presentation bindings changed");
  return expected;
}
