import { canonicalJsonSha256 } from "./auto-edit-hash";
import { assertProposalClauseCoverage } from "@/lib/producer/contracts/treatment-proposal-v2";
import { objectValue } from "@/lib/producer/contracts/validation";
import type { TreatmentProposalV4 } from "@/lib/producer/contracts/treatment-proposal-v4";
import { proposalV5GraphicValidationView } from "@/lib/producer/contracts/treatment-proposal-v5";
import { proposalV6ValidationView } from "@/lib/producer/contracts/treatment-proposal-v6";
import { proposalV7ValidationView } from "@/lib/producer/contracts/treatment-proposal-v7";
import { parseCurrentTreatmentProposal as parseTreatmentProposal, proposalV8ValidationView,
  type CurrentTreatmentProposal as TreatmentProposal } from "@/lib/producer/contracts/treatment-proposal-v8";
import type { ProposalEvidence } from "./guided-proposal-evidence";
import type { AcceptedGuidedCut } from "./guided-raw-treatment-store";
import { proposalRelativeFrame } from "./guided-proposal-speech";
import { buildLongformPlan, type LongformPlan } from "./guided-proposal-longform";
import { buildGuidedFrameBindings, type GuidedFrameBindings } from "./guided-proposal-bindings";
import { applyGuidedCaptionOperations, guidedCaptionPolicy } from "./guided-proposal-captions";
import { applyGuidedReframeOperations } from "./guided-proposal-reframe";
import { applyGuidedMusicOperations, assertGuidedMusicIntent } from "./guided-proposal-music";
import { applyGuidedPresenterOperations, assertGuidedPresenterIntent } from "./guided-proposal-presenter";

export interface ProposalBlocker { clauseIndex: number | null; reason: string }
class UnavailableOpeningRange extends Error {}
export interface TreatmentCandidateResult {
  proposal: TreatmentProposal; blockers: ProposalBlocker[]; candidate: Record<string, unknown> | null;
  range: ReturnType<typeof proposalOpeningRange> | null; executionBindings?: GuidedFrameBindings;
}

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

function fullProgram(proposal: TreatmentProposal, evidence: ProposalEvidence): void {
  let next = 0;
  for (const [index, beat] of proposal.beats.entries()) {
    if (beat.startAnchor !== next || beat.endAnchorExclusive <= next || beat.endAnchorExclusive >= evidence.anchors.length
        || beat.supportsBeatIndices.some((id) => id === index || !proposal.beats[id])) throw new Error("Proposal story does not cover the exact complete program");
    next = beat.endAnchorExclusive;
  }
  if (next !== evidence.anchors.length - 1 || proposal.beats[0]?.purpose !== "opening") throw new Error("Proposal lacks a full-program story outline");
}

/** First-minute review window is independent of creative intro duration and existing cut/beat lengths. */
export function proposalOpeningRange(proposal: TreatmentProposal, evidence: ProposalEvidence) {
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

function graphicCandidate(operation: TreatmentProposal["operations"][number], proposal: TreatmentProposal, evidence: ProposalEvidence) {
  const catalog = evidence.catalog.find((item) => item.kind === operation.catalogKind), beat = proposal.beats[operation.beatIndex!];
  if (!catalog || !beat) throw new Error("Requested catalog kind or grounded story beat is unavailable");
  const entries = operation.variables!, names = entries.map((item) => item.name);
  if (new Set(names).size !== names.length || names.some((key) => !catalog.fields.includes(key))
      || Object.keys(catalog.defaults).some((key) => !names.includes(key))) throw new Error("Catalog variables are incomplete or outside the measured contract; no placeholder defaults are filled");
  const spec = Object.fromEntries(entries.map((item) => [item.name, item.value]));
  if (names.some((key) => /(?:src|file|icon|avatar|image|url|asset)/i.test(key)
      && !(proposal.schemaVersion >= 3 && catalog.defaults[key] === "" && spec[key] === ""))) {
    throw new Error("Asset-bearing catalog actions require a separately resolved asset contract");
  }
  if (entries.some((item) => typeof item.value !== typeof catalog.defaults[item.name])) throw new Error("Catalog variable type differs from its measured default type");
  const [num, den] = evidence.frameRate.split("/").map(Number);
  if (operation.startAnchor! < beat.startAnchor || operation.endAnchorExclusive! > beat.endAnchorExclusive
      || operation.startAnchor! >= operation.endAnchorExclusive!) throw new Error("Graphic range must fit within its grounded beat without inheriting the whole cut");
  const startFrame = evidence.anchors[operation.startAnchor!], endFrame = evidence.anchors[operation.endAnchorExclusive!];
  const presentation = "presentation" in operation ? operation.presentation : undefined;
  if (presentation?.anchor === "own-screen" && (catalog.canvas[0] !== evidence.target.width || catalog.canvas[1] !== evidence.target.height)) {
    throw new Error("Full-canvas presentation requires exact native destination dimensions; no implicit resize");
  }
  return { kind: catalog.kind, outStart: startFrame * den / num, outEnd: endFrame * den / num,
    spec, ...(presentation ? { anchor: presentation.anchor } : {}), proposalFrameRange: { startFrame, endFrameExclusive: endFrame } };
}

function operations(proposal: TreatmentProposal, evidence: ProposalEvidence) {
  const graphics: ReturnType<typeof graphicCandidate>[] = [], blockers: ProposalBlocker[] = [];
  let grade: "warm" | "none" | undefined;
  for (const item of proposal.operations) {
    try {
      if (item.type === "catalog-graphic") graphics.push(graphicCandidate(item, proposal, evidence));
      if (item.type === "grade" && grade !== undefined && grade !== item.grade) throw new Error("Requested grades conflict across clauses");
      if (item.type === "grade") {
        grade = item.grade!;
        throw new Error("Grade intent is blocked until source-aware color/profile authority is connected; no baselineLook, crop, zoom or resize may be inferred");
      }
    } catch (error) { blockers.push({ clauseIndex: item.clauseIndex, reason: String(error).slice(0, 1000) }); }
  }
  if (graphics.length > 30) blockers.push({ clauseIndex: null, reason: "Proposal exceeds the prototype30-graphic admission cap; workload qualification is required, not a final quality policy" });
  if (proposal.colorPolicy !== (grade ?? "preserve")) blockers.push({ clauseIndex: null, reason: "Global color policy is not explained by exact requested grade operations" });
  return { graphics, grade, blockers };
}

/** Produced/full long-form gate obligations the accepted cut plan must carry, authored exactly once. */
function longformCandidate(input: { candidate: Record<string, unknown>; proposal: TreatmentProposalV4; longform: LongformPlan; ids: unknown[]; inheritedCount: number }): void {
  const { candidate, proposal, longform, ids, inheritedCount } = input;
  candidate.target = { ...objectValue(candidate.target, "accepted target"),
    graphicsStyle: proposal.graphicsStyle, graphicsStyleRationale: proposal.graphicsStyleRationale };
  candidate.graphicsDecisions = longform.decisions.map(({ graphicIndex, ...row }) => ({ ...row, graphicId: ids[inheritedCount + graphicIndex] }));
  candidate.transitions = [];
  if (longform.transitionRationale) candidate.transitionRationale = longform.transitionRationale;
}

function captionCandidate(plan: Record<string, unknown>, proposal: TreatmentProposal, evidence: ProposalEvidence):
  { candidate: Record<string, unknown> | null; blockers: ProposalBlocker[] } {
  if (proposal.schemaVersion === 8) return captionCandidate(plan, proposalV8ValidationView(proposal), evidence);
  if (proposal.schemaVersion === 7) return captionCandidate(plan, proposalV7ValidationView(proposal), evidence);
  if (proposal.schemaVersion !== 5 && proposal.schemaVersion !== 6) return { candidate: plan, blockers: [] };
  if (!evidence.captionPolicy || canonicalJsonSha256(evidence.captionPolicy)
      !== canonicalJsonSha256(guidedCaptionPolicy(evidence.captionPolicy.configuration))) {
    throw new Error("Captioned candidate lacks the exact captured caption policy");
  }
  try {
    const reframed = proposal.schemaVersion === 6 ? applyGuidedReframeOperations(plan, proposal) : plan;
    const view = proposal.schemaVersion === 6 ? proposalV6ValidationView(proposal) : proposal;
    return { candidate: applyGuidedCaptionOperations(reframed, view), blockers: [] };
  }
  catch (error) {
    return { candidate: null, blockers: [{ clauseIndex: proposal.operations.find((item) => item.type === "reframe-manual-short"
        || item.type === "captions-full-program")?.clauseIndex ?? null,
      reason: String(error).slice(0, 1000) }] };
  }
}

/** Music is projected from exact held metadata before visual authoring; it cannot change the accepted cut or intent. */
function musicCandidate(input: { cut: AcceptedGuidedCut; proposal: TreatmentProposal; evidence: ProposalEvidence }) {
  if (input.proposal.schemaVersion === 8) return musicCandidate({ ...input, proposal: proposalV8ValidationView(input.proposal) });
  if (input.proposal.schemaVersion !== 7) return { candidate: structuredClone(input.cut.plan.value), blockers: [] };
  if (!input.evidence.musicPolicy) throw new Error("V7 candidate lacks its exact admitted-project music policy");
  try {
    assertGuidedMusicIntent(input.cut.plan.value, input.cut.job.ctx.intent);
    return { candidate: applyGuidedMusicOperations({ plan: input.cut.plan.value, manifest: input.cut.manifest.value,
      proposal: input.proposal, policy: input.evidence.musicPolicy }), blockers: [] };
  } catch (error) {
    return { candidate: null, blockers: [{ clauseIndex: input.proposal.operations.find((item) => item.type === "music-bed-full-program")?.clauseIndex ?? null,
      reason: String(error).slice(0, 1000) }] };
  }
}

/** Only the actual V8 request can add timed layouts; this creates no media execution or framing approval. */
function presenterCandidate(input: { cut: AcceptedGuidedCut; plan: Record<string, unknown>;
  proposal: TreatmentProposal; evidence: ProposalEvidence }): { candidate: Record<string, unknown> | null; blockers: ProposalBlocker[] } {
  if (input.proposal.schemaVersion !== 8) return { candidate: input.plan, blockers: [] };
  if (!input.evidence.presenterPolicy) throw new Error("V8 candidate lacks its exact admitted-project presenter policy");
  try {
    assertGuidedPresenterIntent(input.cut.plan.value, input.cut.job.ctx.intent);
    return { candidate: applyGuidedPresenterOperations({ plan: input.plan, manifest: input.cut.manifest.value,
      proposal: input.proposal, policy: input.evidence.presenterPolicy, evidence: input.evidence }), blockers: [] };
  } catch (error) {
    return { candidate: null, blockers: [{ clauseIndex: input.proposal.operations.find((item) => item.type === "presenter-layout-window")?.clauseIndex ?? null,
      reason: String(error).slice(0, 1000) }] };
  }
}

/** Candidate materialization only; no render readiness, fulfilled clause, or active plan is minted. */
export function buildTreatmentCandidate(input: { cut: AcceptedGuidedCut; rawIntent: string; evidence: ProposalEvidence; output: unknown }): TreatmentCandidateResult {
  const proposal = parseTreatmentProposal(input.output); assertProposalClauseCoverage(proposal, input.rawIntent);
  const required = input.evidence.schemaVersion;
  if (proposal.schemaVersion !== required) throw new Error("Proposal schema must match its exact versioned evidence; no presentation upgrade");
  assertProposalAnchors(input.evidence);
  const blockers: ProposalBlocker[] = proposal.clauses.flatMap((clause, clauseIndex) => clause.disposition === "supported"
    ? [] : [{ clauseIndex, reason: `${clause.disposition}: ${clause.rationale}` }]);
  if (blockers.length && !proposal.beats.length) return { proposal, blockers, candidate: null, range: null };
  fullProgram(proposal, input.evidence);
  let range: ReturnType<typeof proposalOpeningRange>;
  try { range = proposalOpeningRange(proposal, input.evidence); }
  catch (error) {
    if (!(error instanceof UnavailableOpeningRange)) throw error;
    return { proposal, blockers: [...blockers, { clauseIndex: null, reason: error.message }], candidate: null, range: null };
  }
  const compiled = operations(proposal, input.evidence); blockers.push(...compiled.blockers);
  const musicView = proposal.schemaVersion === 8 ? proposalV8ValidationView(proposal) : proposal;
  const manualView = musicView.schemaVersion === 7 ? proposalV7ValidationView(musicView) : musicView;
  const captionView = manualView.schemaVersion === 6 ? proposalV6ValidationView(manualView) : manualView;
  const graphicProposal = captionView.schemaVersion === 5 ? proposalV5GraphicValidationView(captionView) : captionView;
  const longform = graphicProposal.schemaVersion === 4
    ? buildLongformPlan({ proposal: graphicProposal, evidence: input.evidence, graphics: compiled.graphics, plan: input.cut.plan.value }) : null;
  if (longform) blockers.push(...longform.blockers);
  if (blockers.length) return { proposal, blockers, candidate: null, range };
  const music = musicCandidate({ cut: input.cut, proposal, evidence: input.evidence });
  if (!music.candidate) return { proposal, blockers: music.blockers, candidate: null, range };
  const captioned = captionCandidate(music.candidate, proposal, input.evidence);
  if (!captioned.candidate) return { proposal, blockers: captioned.blockers, candidate: null, range };
  const presented = presenterCandidate({ cut: input.cut, plan: captioned.candidate, proposal, evidence: input.evidence });
  if (!presented.candidate) return { proposal, blockers: presented.blockers, candidate: null, range };
  const candidate = presented.candidate, before = canonicalJsonSha256({ cutTrack: candidate.cutTrack, cutDecisions: candidate.cutDecisions });
  const inheritedCount = Array.isArray(candidate.graphicsTrack) ? candidate.graphicsTrack.length : 0;
  candidate.graphicsTrack = [...(Array.isArray(candidate.graphicsTrack) ? candidate.graphicsTrack : []),
    ...compiled.graphics.map((graphic, index) => ({ ...graphic, ...(longform ? longform.annotations[index] : {}) }))
      .map(({ proposalFrameRange: _range, ...entry }, index) => { void _range;
        return { ...entry, id: `g-${canonicalJsonSha256({ entry, index, request: input.rawIntent }).slice(0, 8)}` }; })];
  const ids = (candidate.graphicsTrack as Array<{ id: unknown }>).map((graphic) => graphic.id);
  if (new Set(ids).size !== ids.length) return { proposal, blockers: [{ clauseIndex: null, reason: "Graphic identity collision requires explicit resolution" }], candidate: null, range };
  if (longform && graphicProposal.schemaVersion === 4) longformCandidate({ candidate, proposal: graphicProposal, longform, ids, inheritedCount });
  if (before !== canonicalJsonSha256({ cutTrack: candidate.cutTrack, cutDecisions: candidate.cutDecisions })) throw new Error("Proposal attempted to mutate the accepted cut");
  return { proposal, blockers, candidate, range, ...(proposal.schemaVersion === 2 ? {} : {
    executionBindings: buildGuidedFrameBindings({ proposal, evidence: input.evidence, candidate, inheritedCount }),
  }) };
}
