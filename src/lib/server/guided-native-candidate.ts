/** Deterministic native compilation: speech cues, persistent objects, holds and stable edit identities. */
import { parseTreatmentProposalV9, type TreatmentProposalV9 } from "@/lib/producer/contracts/treatment-proposal-v9";
import { parseTreatmentProposalV10, type NativeShortSceneV10, type TreatmentProposalV10 } from "@/lib/producer/contracts/treatment-proposal-v10";
import { assertProposalClauseCoverage } from "@/lib/producer/contracts/treatment-proposal-v2";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { assertProposalAnchors, fullProposalProgram, proposalOpeningRange } from "./guided-proposal-frame-ranges";
import type { ProposalBlocker } from "./guided-proposal-candidate";
import type { ProposalEvidence } from "./guided-proposal-evidence";
import { assertDirectorSource, type NativeDirectorRecord } from "./native-director-store";
import type { NativeAssetRequirement } from "./guided-native-supporting";

export interface CompiledNativeScene {
  direction: NativeShortSceneV10; startFrame: number; endFrameExclusive: number;
  steps: Array<{ startFrame: number; settledFrame: number; elementId: string; text: string; occurrenceId: number }>;
  elementIds: string[]; referenceHashes: string[]; speechHash: string;
}
export interface NativeShortDirection {
  schemaVersion: 1; route: "native-short-v1"; sourceCutHash: string; timelineMapHash: string;
  frameRate: string; totalFrames: number; target: Record<string, unknown>;
  segments: ProposalEvidence["segments"]; occurrences: ProposalEvidence["occurrences"];
  scenes: CompiledNativeScene[];
  proposalVersion?: 10;
  assetRequirements?: NativeAssetRequirement[];
  director?: NativeDirectorRecord;
  captions: "all-kept-words"; sourceFit: "contain"; audio: "source-dialogue-only";
  scope: "development-native-project-not-quality-or-delivery-approval";
}
export interface NativeTreatmentCandidateResult {
  proposal: TreatmentProposalV9 | TreatmentProposalV10; blockers: ProposalBlocker[];
  candidate: Record<string, unknown> | null; range: ReturnType<typeof proposalOpeningRange> | null;
  pendingRequirements?: NativeAssetRequirement[];
}

function sceneSpeech(scene: NativeShortSceneV10, evidence: ProposalEvidence) {
  const start = evidence.anchors[scene.startAnchor], end = evidence.anchors[scene.endAnchorExclusive];
  const words = scene.occurrenceIds.map((id) => {
    const word = evidence.occurrences[id];
    if (!word || word[0] !== id || word[3] < start || word[4] > end || word[6] !== 0) {
      throw new Error("Native scene cites absent, clipped or out-of-window speech");
    }
    return word;
  });
  if (words.some((word, index) => index > 0 && word[0] !== words[index - 1][0] + 1)
      || words.map((word) => word[5]).join(" ") !== scene.quote) throw new Error("Native source quote must reproduce contiguous retained occurrences exactly");
  return words;
}

function compiledSteps(scene: NativeShortSceneV10, evidence: ProposalEvidence) {
  let settled = evidence.anchors[scene.startAnchor];
  return scene.steps.map((step, index) => {
    const word = evidence.occurrences[step.occurrenceId], frame = evidence.anchors[step.anchor];
    if (!scene.occurrenceIds.includes(step.occurrenceId) || !word || frame !== word[3] || frame < settled
        || step.anchor < scene.startAnchor || step.anchor >= scene.endAnchorExclusive) {
      throw new Error("Native action must start on its exact retained word and after the preceding action settles");
    }
    settled = frame + step.transitionFrames;
    return { startFrame: frame, settledFrame: settled, elementId: `${scene.id}-message-${scene.before.length + index}`,
      text: step.text, occurrenceId: step.occurrenceId };
  });
}

function compileScene(scene: NativeShortSceneV10, evidence: ProposalEvidence): CompiledNativeScene {
  const speech = sceneSpeech(scene, evidence), steps = compiledSteps(scene, evidence);
  const startFrame = evidence.anchors[scene.startAnchor], endFrameExclusive = evidence.anchors[scene.endAnchorExclusive];
  const settled = steps.at(-1)?.settledFrame ?? startFrame;
  if (endFrameExclusive - settled < scene.readingHoldFrames) throw new Error("Native result lacks the authored reading hold after its final action settles");
  if (scene.requiredAssetIds.length && evidence.schemaVersion === 9) throw new Error(`Required story assets need an implemented native asset executor: ${scene.requiredAssetIds.join(", ")}`);
  if (scene.requiredAssetIds.length) assertSupportingScene(scene, evidence);
  const referenceHashes = scene.referenceIds.map((id) => {
    const reference = evidence.nativeReferences?.find((row) => row.id === id);
    if (!reference?.images.length) throw new Error("Native scene requires its selected visual reference snapshot");
    return canonicalJsonSha256(reference);
  });
  return { direction: scene, startFrame, endFrameExclusive, steps, referenceHashes, speechHash: canonicalJsonSha256(speech),
    elementIds: [scene.id, `${scene.id}-slot`, ...(scene.mechanism === "message-reveal"
      ? [`${scene.id}-illustration`, `${scene.id}-label`, ...scene.result.map((_, index) => `${scene.id}-message-${index}`)] : [])] };
}

function assertSupportingScene(scene: NativeShortSceneV10, evidence: ProposalEvidence): void {
  const policy = evidence.nativeSupportingPolicy;
  if (evidence.schemaVersion !== 10 || !policy || policy.schemaVersion !== 1 || policy.brollEnabled !== true
      || policy.policy.placement !== "auto") throw new Error("Supporting assets require accepted automatic B-roll ownership and placement");
  if (scene.mechanism !== "supporting-asset") throw new Error("Supporting requirement lacks its explicit mechanism");
  for (const id of scene.requiredAssetIds) {
    const matches = policy.assets.filter(row => row.assetId === id);
    if (matches.length !== 1) throw new Error(`Required supplied asset is absent or ambiguous: ${id}`);
    if (matches[0].eligible !== true || matches[0].kind !== "image" || !["image/png", "image/jpeg", "image/webp"].includes(matches[0].mime ?? "")) {
      throw new Error(`Required supplied asset is not an implemented raster image: ${id}`);
    }
  }
}

function compileScenes(proposal: TreatmentProposalV9 | TreatmentProposalV10, evidence: ProposalEvidence) {
  let next = 0;
  const scenes = proposal.operations.map((operation) => {
    const scene = operation.scene, beat = proposal.beats[operation.beatIndex];
    if (!beat || scene.startAnchor !== next || scene.startAnchor < beat.startAnchor || scene.endAnchorExclusive > beat.endAnchorExclusive) {
      throw new Error("Native scenes must partition the entire program inside their referenced story beats");
    }
    next = scene.endAnchorExclusive;
    return compileScene(scene, evidence);
  });
  if (next !== evidence.anchors.length - 1 || new Set(scenes.map((row) => row.direction.id)).size !== scenes.length) {
    throw new Error("Native scene coverage is incomplete or identities collide");
  }
  const ids = scenes.flatMap((row) => row.elementIds);
  if (new Set(ids).size !== ids.length) throw new Error("Native element identities collide");
  return scenes;
}

function assertNativePlan(plan: Record<string, unknown>, evidence: ProposalEvidence): void {
  if (canonicalJsonSha256(plan.target) !== canonicalJsonSha256(evidence.target)) {
    throw new Error("Native destination evidence differs from the accepted target");
  }
  if (![9, 10].includes(evidence.schemaVersion) || evidence.target.mode !== "short" || evidence.target.width !== 1080 || evidence.target.height !== 1920) {
    throw new Error("Native V9/V10 requires the exact accepted short1080x1920 target");
  }
  if (Object.keys(plan).some((key) => !["planVersion", "target", "cutTrack", "cutDecisions"].includes(key))) {
    throw new Error("Native development route requires an untreated accepted cut; inherited treatments need explicit migration");
  }
  if (evidence.target.music === true) throw new Error("Native dialogue-only executor cannot fulfill a music-enabled target");
  const lanes = evidence.target.lanes as Record<string, unknown> | undefined;
  if (!lanes || ["captions", "graphics", "motion"].some((lane) => lanes[lane] !== "auto")) {
    throw new Error("Native development executor requires automatic captions, graphics and motion ownership");
  }
}

/** No source mutation or implicit capability downgrade. Invalid direction is retained as an explicit blocker. */
export function buildNativeTreatmentCandidate(input: { plan: Record<string, unknown>; rawIntent: string; evidence: ProposalEvidence; output: unknown }): NativeTreatmentCandidateResult {
  const proposal = input.evidence.schemaVersion === 10 ? parseTreatmentProposalV10(input.output) : parseTreatmentProposalV9(input.output);
  assertProposalClauseCoverage(proposal, input.rawIntent); assertProposalAnchors(input.evidence);
  assertNativePlan(input.plan, input.evidence);
  if (input.evidence.graphicsAdvice?.nativeDirectorVersion === 1) {
    if (!input.evidence.nativeDirector) throw new Error("Native planning requires its reviewed Director decision");
    assertDirectorSource(input.evidence.nativeDirector, input.rawIntent, input.evidence);
  }
  const blockers: ProposalBlocker[] = proposal.clauses.flatMap((row, clauseIndex) => row.disposition === "supported"
    ? [] : [{ clauseIndex, reason: `${row.disposition}: ${row.rationale}` }]);
  if (blockers.length) return { proposal, blockers, candidate: null, range: null };
  fullProposalProgram(proposal, input.evidence);
  const range = proposalOpeningRange(proposal, input.evidence);
  try {
    const scenes = compileScenes(proposal, input.evidence);
    const pendingRequirements = scenes.flatMap(scene => scene.direction.requiredAssetIds.map(assetId => ({
      sceneId: scene.direction.id, assetId, startFrame: scene.startFrame, endFrameExclusive: scene.endFrameExclusive,
      occurrenceIds: scene.direction.occurrenceIds, quote: scene.direction.quote,
    })));
    const nativeDirection: NativeShortDirection = { schemaVersion: 1, route: "native-short-v1",
      sourceCutHash: canonicalJsonSha256(input.plan), timelineMapHash: input.evidence.timelineMapHash,
      frameRate: input.evidence.frameRate, totalFrames: input.evidence.totalFrames, target: input.evidence.target,
      segments: input.evidence.segments, occurrences: input.evidence.occurrences, scenes,
      ...(proposal.schemaVersion === 10 ? { proposalVersion: 10 as const, assetRequirements: pendingRequirements } : {}),
      ...(input.evidence.nativeDirector ? { director: input.evidence.nativeDirector } : {}),
      captions: "all-kept-words", sourceFit: "contain", audio: "source-dialogue-only",
      scope: "development-native-project-not-quality-or-delivery-approval" };
    return { proposal, blockers, range, ...(proposal.schemaVersion === 10 ? { pendingRequirements } : {}), candidate: { ...structuredClone(input.plan),
      executionRoute: "native-short-v1", nativeDirection } as Record<string, unknown> };
  } catch (error) {
    return { proposal, blockers: [{ clauseIndex: null, reason: String(error).slice(0, 1000) }], candidate: null, range };
  }
}
