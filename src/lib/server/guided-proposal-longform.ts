import { objectValue, stringValue } from "@/lib/producer/contracts/validation";
import type { ProposalBeatDecisionV4, TreatmentProposalV4 } from "@/lib/producer/contracts/treatment-proposal-v4";
import type { ProposalEvidence, ProposalIntroSeam } from "./guided-proposal-evidence";
import { proposalRelativeFrame } from "./guided-proposal-speech";

/** Deterministic planner obligation; the provider never invents a beat, its shape or its compatible kinds. */
export interface ProposalSemanticBeat {
  beatId: string; shape: string; outStart: number; evidence: string;
  compatibleKinds: string[]; minimumGraphicHoldS: number;
}
export interface ProposalGraphicCandidate {
  kind: string; proposalFrameRange: { startFrame: number; endFrameExclusive: number };
}
export interface LongformBlocker { clauseIndex: number | null; reason: string }
export interface LongformDecisionRow {
  beatId: string; decision: "graphic"; reason: string; kind: string;
  alternativesConsidered: string[]; selectionReason: string; graphicIndex: number;
}
export interface LongformCleanHookReceipt {
  decision: "clean-hook"; reason: string;
  seams: Array<{ outTime: number; evidence: string; seamIndex: number; reason: string }>;
}
export interface LongformPlan {
  blockers: LongformBlocker[]; annotations: Array<{ reason: string; semanticBeatId?: string }>;
  decisions: LongformDecisionRow[]; transitionRationale: LongformCleanHookReceipt | null;
}

function finiteNumber(value: unknown, label: string, maximum: number): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > maximum) throw new Error(`${label} must be a bounded nonnegative number`);
  return value;
}

/** graphics_planner.py introSemanticBeats rows carrying decisionRequired; nothing here is provider-supplied. */
export function requiredSemanticBeats(evidence: ProposalEvidence): ProposalSemanticBeat[] {
  const advice = objectValue(evidence.graphicsAdvice["graphics_planner.py"], "deterministic graphics planner advice");
  const rows = advice.introSemanticBeats;
  if (!Array.isArray(rows) || rows.length > 512) throw new Error("Proposal evidence lacks bounded deterministic intro semantic beats");
  return rows.map((value) => objectValue(value, "intro semantic beat")).filter((row) => row.decisionRequired === true).map((row) => ({
    beatId: stringValue(row.beatId, "semantic beat id", 128), shape: stringValue(row.shape, "semantic beat shape", 100),
    outStart: finiteNumber(row.outStart, "semantic beat outStart", 100_000), evidence: stringValue(row.evidence, "semantic beat evidence", 20_000),
    compatibleKinds: (Array.isArray(row.compatibleKinds) ? row.compatibleKinds : []).map((kind) => stringValue(kind, "compatible kind", 100)),
    minimumGraphicHoldS: finiteNumber(row.minimumGraphicHoldS, "semantic beat minimumGraphicHoldS", 3600) }));
}

/** graphics/intro_semantic_binding.covers plus _hold_error, compared on the exact controller frame clock. */
function coverageIssue(beat: ProposalSemanticBeat, graphic: ProposalGraphicCandidate, frameRate: string): string | null {
  const frame = (edge: "start" | "end") => proposalRelativeFrame({ time: beat.outStart, origin: 0, frameRate, edge });
  const { startFrame, endFrameExclusive } = graphic.proposalFrameRange;
  if (frame("start") < startFrame || frame("end") >= endFrameExclusive) {
    return `bound graphic frames [${startFrame}, ${endFrameExclusive}) are not on screen at the exact semantic beat ${beat.outStart}s`;
  }
  const [numerator, denominator] = frameRate.split("/").map(Number);
  const hold = (endFrameExclusive - startFrame) * denominator / numerator;
  if (hold + 1e-6 < beat.minimumGraphicHoldS) return `bound graphic hold ${hold.toFixed(2)}s is shorter than minimumGraphicHoldS ${beat.minimumGraphicHoldS}s`;
  return null;
}

/** graphics/intro_semantic_binding._selection_error/decision_error, with no informationForm profile lane. */
function beatIssue(input: { beat: ProposalSemanticBeat; decision: ProposalBeatDecisionV4;
  operation: TreatmentProposalV4["operations"][number] | undefined; graphic: ProposalGraphicCandidate | undefined; frameRate: string }): string | null {
  const { beat, decision, operation, graphic } = input;
  if (!operation || operation.type !== "catalog-graphic" || !graphic) return `operationIndex ${decision.operationIndex} is not a compiled catalog graphic`;
  if (decision.kind !== operation.catalogKind) return `kind ${JSON.stringify(decision.kind)} differs from the bound operation catalogKind ${JSON.stringify(operation.catalogKind)}`;
  if (!beat.compatibleKinds.includes(decision.kind)) return `kind ${JSON.stringify(decision.kind)} is outside compatible forms [${beat.compatibleKinds.join(", ")}]`;
  const outside = decision.alternativesConsidered.filter((kind) => !beat.compatibleKinds.includes(kind));
  if (outside.length) return `alternativesConsidered [${outside.join(", ")}] are outside compatible forms [${beat.compatibleKinds.join(", ")}]`;
  const needed = Math.min(2, Math.max(0, beat.compatibleKinds.length - 1));
  if (decision.alternativesConsidered.length < needed) return `graphic decision considered ${decision.alternativesConsidered.length} alternative(s); needs ${needed}`;
  return coverageIssue(beat, graphic, input.frameRate);
}

function beatBlockers(input: { proposal: TreatmentProposalV4; evidence: ProposalEvidence;
  graphics: ProposalGraphicCandidate[]; graphicIndexes: Map<number, number> }): LongformBlocker[] {
  const { proposal, evidence, graphics, graphicIndexes } = input;
  const beats = requiredSemanticBeats(evidence), byId = new Map(beats.map((beat) => [beat.beatId, beat]));
  const decisions = new Map(proposal.beatDecisions.map((row) => [row.beatId, row]));
  const missing = beats.filter((beat) => !decisions.has(beat.beatId)).map((beat) => ({ clauseIndex: null,
    reason: `Deterministic beat ${beat.beatId} (${beat.shape} at ${beat.outStart}s, ${JSON.stringify(beat.evidence.slice(0, 200))}) has no graphic decision; a required beat cannot be omitted` }));
  const issues = proposal.beatDecisions.flatMap((decision) => {
    const beat = byId.get(decision.beatId), operation = proposal.operations[decision.operationIndex];
    const clauseIndex = operation ? operation.clauseIndex : null;
    if (!beat) return [{ clauseIndex, reason: `Beat decision ${decision.beatId} names no deterministic decisionRequired beat in this evidence` }];
    const issue = beatIssue({ beat, decision, operation, graphic: graphics[graphicIndexes.get(decision.operationIndex) ?? -1], frameRate: evidence.frameRate });
    return issue ? [{ clauseIndex, reason: `Beat ${beat.beatId}: ${issue}` }] : [];
  });
  return [...missing, ...issues];
}

/** intro_transition_contract: every eligible seam owes a decision, and empty transitions alone prove nothing. */
function seamBlockers(proposal: TreatmentProposalV4, seams: ProposalIntroSeam[]): LongformBlocker[] {
  const decided = new Set(proposal.hookSeamDecisions.map((row) => row.seamIndex));
  return [...seams.filter((seam) => !decided.has(seam.seamIndex)).map((seam) => ({ clauseIndex: null,
    reason: `Intro seam ${seam.seamIndex} at ${seam.outTime}s has no clean-hook decision; an unresolved hook seam is not an editorial decision` })),
  ...proposal.hookSeamDecisions.filter((row) => row.seamIndex >= seams.length).map((row) => ({ clauseIndex: null,
    reason: `Hook seam decision ${row.seamIndex} names no seam in this evidence` }))];
}

/** The accepted cut owns these lanes; guided V4 authors them once and never overwrites existing work. */
function planBlockers(plan: Record<string, unknown>): LongformBlocker[] {
  return ["transitions", "transitionRationale", "graphicsDecisions"].filter((key) => {
    const value = plan[key];
    return Array.isArray(value) ? value.length > 0 : value !== undefined && value !== null;
  }).map((key) => ({ clauseIndex: null, reason: `Accepted cut already carries ${key}; guided V4 cannot replace an existing decision receipt` }));
}

/** One plan-level reason is required, so the lowest seam's reason leads and every seam keeps its own. */
function cleanHookReceipt(proposal: TreatmentProposalV4, seams: ProposalIntroSeam[]): LongformCleanHookReceipt | null {
  const rows = proposal.hookSeamDecisions.filter((row) => seams[row.seamIndex]).sort((left, right) => left.seamIndex - right.seamIndex);
  if (!rows.length) return null;
  return { decision: "clean-hook", reason: rows[0].reason, seams: rows.map((row) => ({ outTime: seams[row.seamIndex].outTime,
    evidence: row.evidence, seamIndex: row.seamIndex, reason: row.reason })) };
}

/** Deterministic gate conformance only; no rendered, legible, semantic or human approval is implied. */
export function buildLongformPlan(input: { proposal: TreatmentProposalV4; evidence: ProposalEvidence;
  graphics: ProposalGraphicCandidate[]; plan: Record<string, unknown> }): LongformPlan {
  const { proposal, evidence, graphics } = input, seams = evidence.introSeams;
  if (!Array.isArray(seams) || evidence.hookWindowS === undefined) throw new Error("V4 candidate requires exact intro seam evidence");
  const operationIndexes = proposal.operations.flatMap((operation, index) => operation.type === "catalog-graphic" ? [index] : []);
  const graphicIndexes = new Map(operationIndexes.map((operationIndex, graphicIndex) => [operationIndex, graphicIndex]));
  if (operationIndexes.length !== graphics.length) {
    return { blockers: [{ clauseIndex: null, reason: "Catalog graphics did not compile; longform beat obligations cannot be verified" }],
      annotations: [], decisions: [], transitionRationale: null };
  }
  const blockers = [...planBlockers(input.plan), ...beatBlockers({ proposal, evidence, graphics, graphicIndexes }), ...seamBlockers(proposal, seams)];
  if (proposal.graphicsStyle === "face-bridge") {
    blockers.push({ clauseIndex: null, reason: "face-bridge/visualProfile is not supported by guided V4; no profile-form, chassis or presenter-hole authority exists here" });
  }
  const beatByOperation = new Map(proposal.beatDecisions.map((row) => [row.operationIndex, row]));
  const annotations = operationIndexes.map((operationIndex) => {
    const decision = beatByOperation.get(operationIndex);
    return { reason: proposal.operations[operationIndex].reason!, ...(decision ? { semanticBeatId: decision.beatId } : {}) };
  });
  const decisions = proposal.beatDecisions.map(({ operationIndex, ...row }) => ({ ...row, graphicIndex: graphicIndexes.get(operationIndex)! }));
  return { blockers, annotations, decisions, transitionRationale: cleanHookReceipt(proposal, seams) };
}
