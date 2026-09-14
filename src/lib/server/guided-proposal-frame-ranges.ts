/** Shared long-form/native proposal clock and complete-program coverage checks. */
import type { TreatmentProposalV2 as TreatmentProposal } from "@/lib/producer/contracts/treatment-proposal-v2";
import type { ProposalEvidence } from "./guided-proposal-evidence";
import { proposalRelativeFrame } from "./guided-proposal-speech";

export class UnavailableOpeningRange extends Error {}

/** Controller anchor table must be collision-free, complete and ordered before any provider reference is used. */
export function assertProposalAnchors(evidence: ProposalEvidence): void {
  const anchors = new Set(evidence.anchors);
  if (!Array.isArray(evidence.anchors) || evidence.anchors.length < 2 || evidence.anchors.length > 60_002
      || evidence.anchors[0] !== 0 || evidence.anchors.at(-1) !== evidence.totalFrames
      || evidence.anchors.some((frame, index) => !Number.isSafeInteger(frame) || frame < 0
        || index > 0 && frame <= evidence.anchors[index - 1]) || !Array.isArray(evidence.cleanEnds)
      || evidence.cleanEnds.some((frame, index) => !anchors.has(frame) || index > 0 && frame <= evidence.cleanEnds[index - 1])) {
    throw new Error("Proposal frame anchors are incomplete, duplicate, unsorted or ungrounded");
  }
}

export function fullProposalProgram(proposal: Pick<TreatmentProposal, "beats">, evidence: ProposalEvidence): void {
  let next = 0;
  for (const [index, beat] of proposal.beats.entries()) {
    if (beat.startAnchor !== next || beat.endAnchorExclusive <= next || beat.endAnchorExclusive >= evidence.anchors.length
        || beat.supportsBeatIndices.some((id) => id === index || !proposal.beats[id])) throw new Error("Proposal story does not cover the exact complete program");
    next = beat.endAnchorExclusive;
  }
  if (next !== evidence.anchors.length - 1 || proposal.beats[0]?.purpose !== "opening") throw new Error("Proposal lacks a full-program story outline");
}

/** First-minute review window is independent of creative intro duration and existing cut/beat lengths. */
export function proposalOpeningRange(proposal: Pick<TreatmentProposal, "openingEndAnchor" | "continuityEndAnchor">, evidence: ProposalEvidence) {
  const end = proposal.openingEndAnchor, context = proposal.continuityEndAnchor;
  if (end === null || context === null || end > context || context >= evidence.anchors.length) throw new Error("Proposal lacks a real opening/body continuity range");
  const endFrame = evidence.anchors[end], contextEnd = evidence.anchors[context];
  const frame = (time: number, edge: "start" | "end") => proposalRelativeFrame({ time, origin: 0, frameRate: evidence.frameRate, edge });
  const firstMinute = Math.min(evidence.totalFrames, frame(60, "end")), maximum = Math.min(evidence.totalFrames, frame(75, "start"));
  if (endFrame < firstMinute || endFrame > maximum || endFrame !== evidence.totalFrames && !evidence.cleanEnds.includes(endFrame)) {
    throw new UnavailableOpeningRange("Opening review needs a transcript-grounded clean endpoint within60–75 seconds (or the entire shorter program); no whole-video expansion");
  }
  if (contextEnd < Math.min(evidence.totalFrames, endFrame + frame(5, "end")) || contextEnd > Math.min(evidence.totalFrames, endFrame + frame(15, "start"))) {
    throw new UnavailableOpeningRange("Opening review continuity must cover5–15 seconds beyond the core or the remaining tail, independent of body beat length");
  }
  return { schemaVersion: 1, frameRate: evidence.frameRate, totalFrames: evidence.totalFrames,
    approval: { startFrame: 0, endFrameExclusive: endFrame }, review: { startFrame: 0, endFrameExclusive: contextEnd },
    timelineMapHash: evidence.timelineMapHash, audioScope: "requires-shared-full-program-master" as const,
    executable: false as const };
}
