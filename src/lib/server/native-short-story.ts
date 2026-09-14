/** Authored story obligations bind existing decisions; they do not judge narrative quality. */
import { exactKeys, objectValue } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { nativeAssetUseRevisionHash } from "./native-short-asset-use";
import { assetUseText } from "./native-short-asset-use-origins";
import { nativePacingVisualWindows, type PacingVisualWindow } from "./native-short-pacing-observations";
import type { NativeAssetUseDecision } from "./native-short-asset-use-types";
import type { NativeShortProjectInput } from "./native-short-project";

export interface NativeStoryVisualJob {
  kind: "presenter-performance" | "explanatory-comparison" | "real-artifact" | "real-operation";
  targetId: string; assetDecisionId: string | null; holdIndex: number | null;
  /** Authored observations on the output clock; actual frame review remains separate. */
  operation?: { actionFrame: number; resultFrame: number; actionObserved: string; resultObserved: string };
}
export interface NativeStoryBeat {
  pacingBeatIndex: number; sceneIndex: number;
  phase: "setup" | "development" | "payoff"; continuityId: string;
  visualJobs: NativeStoryVisualJob[];
}
export interface NativeShortStory {
  schemaVersion: 1; revisionHash: string; viewerQuestion: string; payoff: string;
  continuity: { id: string; subject: string }; beats: NativeStoryBeat[];
}

/** Reuses the source/visual revision plus authored pacing and decisions; never hashes itself. */
export function nativeStoryRevisionHash(input: NativeShortProjectInput): string {
  return canonicalJsonSha256({ assetRevisionHash: nativeAssetUseRevisionHash(input),
    assetUse: input.strategy.assetUse ?? null, pacing: input.strategy.pacing ?? null,
    viewerBenefit: input.strategy.viewerBenefit, hookReasonToWatch: input.strategy.hookReasonToWatch,
    payoff: input.strategy.payoff, expectations: input.expectations ?? null });
}

function shape(value: unknown, label: string, keys: string[], required = keys): void {
  exactKeys(objectValue(value, label), keys, required, label);
}

function stableId(value: unknown): void {
  if (typeof value !== "string" || !/^[a-z][a-z0-9-]{0,95}$/u.test(value)) {
    throw new Error("Story needs a stable target, decision and continuity identity");
  }
}

function storyContext(input: NativeShortProjectInput): NativeShortStory {
  const story = input.strategy.story!;
  shape(story, "native story", ["schemaVersion", "revisionHash", "viewerQuestion", "payoff", "continuity", "beats"]);
  shape(story.continuity, "story continuity", ["id", "subject"]);
  if (input.strategy.schemaVersion !== 3 || story.schemaVersion !== 1 || !input.strategy.assetUse || !input.strategy.pacing) {
    throw new Error("Native story requires version 3 with existing asset-use and pacing decisions");
  }
  if (story.revisionHash !== nativeStoryRevisionHash(input)) throw new Error("Story is stale after a source, scene, beat, hold or decision revision");
  [story.viewerQuestion, story.payoff, story.continuity.subject].forEach(assetUseText);
  stableId(story.continuity.id);
  if (story.payoff !== input.strategy.payoff) throw new Error("Story payoff differs from the selected strategy payoff");
  if (!Array.isArray(story.beats) || story.beats.length < 2 || story.beats.length > 128
      || story.beats.length !== input.strategy.pacing.beats.length) {
    throw new Error("Story must bind every pacing beat, including its setup and payoff");
  }
  return story;
}

function beatContext(input: NativeShortProjectInput, row: NativeStoryBeat, index: number) {
  shape(row, "story beat", ["pacingBeatIndex", "sceneIndex", "phase", "continuityId", "visualJobs"]);
  const beat = input.strategy.pacing!.beats[index], scene = input.strategy.scenes[row.sceneIndex];
  if (row.pacingBeatIndex !== index || !Number.isSafeInteger(row.sceneIndex) || !scene
      || beat.startFrame < scene.startFrame || beat.endFrame > scene.endFrame) {
    throw new Error("Story lost its ordered pacing beat and containing scene binding");
  }
  if (!["setup", "development", "payoff"].includes(row.phase)
      || row.continuityId !== input.strategy.story!.continuity.id
      || !Array.isArray(row.visualJobs) || !row.visualJobs.length || row.visualJobs.length > 8
      || new Set(row.visualJobs.map(job => job.targetId)).size !== row.visualJobs.length) {
    throw new Error("Story beat needs a closed narrative phase, continuous subject and distinct visual jobs");
  }
  return { beat, scene };
}

function jobDecision(input: NativeShortProjectInput, job: NativeStoryVisualJob): NativeAssetUseDecision | undefined {
  const keys = ["kind", "targetId", "assetDecisionId", "holdIndex", "operation"];
  shape(job, "story visual job", keys, keys.filter(key => key !== "operation"));
  stableId(job.targetId);
  if (!["presenter-performance", "explanatory-comparison", "real-artifact", "real-operation"].includes(job.kind)) {
    throw new Error("Story visual job has an unsupported purpose");
  }
  if (job.assetDecisionId === null) return undefined;
  stableId(job.assetDecisionId);
  const decision = input.strategy.assetUse!.decisions.find(item => item.id === job.assetDecisionId);
  if (!decision) throw new Error("Story visual job cites a missing asset-use decision");
  return decision;
}

function primaryTarget(input: NativeShortProjectInput, targetId: string): boolean {
  return input.canvas.segments.some((segment, i) => input.canvas.pictureViews.some((view, j) =>
    targetId === `source-${i}-${j}` && Math.max(segment.startFrame, view.startFrame)
      < Math.min(segment.endFrameExclusive, view.endFrame)));
}

function jobHold(input: NativeShortProjectInput, job: NativeStoryVisualJob, row: NativeStoryBeat) {
  const beat = input.strategy.pacing!.beats[row.pacingBeatIndex], hold = input.strategy.pacing!.holds[job.holdIndex ?? -1];
  if (job.holdIndex === null && job.kind === "presenter-performance") return undefined;
  if (!Number.isSafeInteger(job.holdIndex) || !hold || hold.targetId !== job.targetId
      || hold.startFrame < beat.startFrame || hold.endFrame > beat.endFrame) {
    throw new Error("Story visual job needs an existing readable hold inside its pacing beat");
  }
  return hold;
}

function visualPurpose(input: NativeShortProjectInput, job: NativeStoryVisualJob, decision?: NativeAssetUseDecision): void {
  if (job.kind === "presenter-performance") {
    if (!primaryTarget(input, job.targetId) || (decision && decision.decision !== "no-insert")) {
      throw new Error("Presenter story jobs must retain an actual primary source view");
    }
    return;
  }
  if (job.kind === "explanatory-comparison" && !decision) {
    const graphic = [...input.canvas.text, ...input.canvas.shapes].some(item => item.id === job.targetId)
      || (input.extension?.markup ?? "").includes(`id="${job.targetId}"`);
    if (!graphic || primaryTarget(input, job.targetId)
        || input.strategy.assetUse!.decisions.some(item => item.selection?.targetId === job.targetId)) {
      throw new Error("Comparison job must reference its actual graphic or selected media decision");
    }
    return;
  }
  const selection = decision?.selection;
  if (!decision || decision.decision !== "insert" || !selection || selection.targetId !== job.targetId
      || selection.kind === "logo") throw new Error("Story artifact requires selected real media; a logo or no-insert cannot satisfy it");
  if (job.kind === "real-operation" && (decision.purpose !== "demonstrate" || !["video", "web"].includes(selection.kind))) {
    throw new Error("Real operation requires a demonstration decision and actual video or web recording");
  }
}

function operationBinding(input: NativeShortProjectInput, job: NativeStoryVisualJob, row: NativeStoryBeat): void {
  if (job.kind !== "real-operation") {
    if (job.operation !== undefined) throw new Error("Only a real-operation job may carry operation checkpoints");
    return;
  }
  const operation = job.operation;
  shape(operation, "story operation", ["actionFrame", "resultFrame", "actionObserved", "resultObserved"]);
  const beat = input.strategy.pacing!.beats[row.pacingBeatIndex], hold = input.strategy.pacing!.holds[job.holdIndex!];
  if (!operation || ![operation.actionFrame, operation.resultFrame].every(Number.isSafeInteger)
      || operation.actionFrame < beat.startFrame || operation.actionFrame >= operation.resultFrame
      || operation.resultFrame < hold.startFrame || operation.resultFrame + hold.minimumFrames > hold.endFrame) {
    throw new Error("Real operation needs ordered action/result checkpoints with a readable result hold");
  }
  [operation.actionObserved, operation.resultObserved].forEach(assetUseText);
}

function beatJobs(input: NativeShortProjectInput, row: NativeStoryBeat, windows: PacingVisualWindow[]): void {
  const beat = input.strategy.pacing!.beats[row.pacingBeatIndex], scene = input.strategy.scenes[row.sceneIndex];
  for (const job of row.visualJobs) {
    const decision = jobDecision(input, job), target = windows.find(item => item.id === job.targetId);
    if (!scene.visibleIds.includes(job.targetId) || !target || target.startFrame > beat.startFrame || target.endFrame < beat.endFrame
        || (decision && (decision.speech.startFrame >= beat.endFrame || decision.speech.endFrame <= beat.startFrame))) {
      throw new Error("Story visual job lost its executable target or retained speech interval");
    }
    if (job.kind === "explanatory-comparison" && scene.format === "presenter") {
      throw new Error("Comparison story job requires its explanatory comparison, diagram or demonstration scene");
    }
    jobHold(input, job, row); visualPurpose(input, job, decision); operationBinding(input, job, row);
  }
}

/** Called after shared strategy, asset/origin and pacing validators; no duplicate admission path. */
export function assertNativeShortStory(input: NativeShortProjectInput, html: string): void {
  if (input.strategy.story === undefined) return;
  const story = storyContext(input), phases = ["setup", "development", "payoff"];
  const windows = nativePacingVisualWindows(input, html);
  let phaseIndex = 0;
  story.beats.forEach((row, index) => {
    beatContext(input, row, index);
    const next = phases.indexOf(row.phase);
    if (next < phaseIndex) throw new Error("Story phases must develop from setup toward payoff");
    phaseIndex = next;
    beatJobs(input, row, windows);
  });
  if (story.beats[0].phase !== "setup" || story.beats.at(-1)!.phase !== "payoff") {
    throw new Error("Story needs an opening setup and final payoff bound to retained speech");
  }
}

/** Structural obligations are not source identity, semantic truth or finished playback approval. */
export function nativeShortStoryReport(input: NativeShortProjectInput, html: string) {
  assertNativeShortStory(input, html);
  const story = input.strategy.story;
  return { schemaVersion: 1, scope: "native-short-authored-story-obligations",
    status: story ? "authored-obligations-structurally-checked" : "unplanned",
    revisionHash: nativeStoryRevisionHash(input), plan: story ?? null,
    beats: story?.beats.map(row => ({ ...row, ...input.strategy.pacing!.beats[row.pacingBeatIndex],
      speech: input.strategy.pacing!.beats[row.pacingBeatIndex].occurrenceIds.map(id => input.canvas.occurrences[id][5]).join(" ") })) ?? [],
    narrativeQuality: "not-established-by-structural-checks", sourceTruth: "not-established-by-structural-checks",
    finishedPlaybackReview: "not-performed-by-this-command",
    reviewRequired: ["Review the complete question, visual development and payoff with original speech",
      "Inspect real-source identity and each claimed action/result in the actual recorded frames",
      "Check continuity, readable holds, crop, captions and attention competition at phone size",
      "Watch the complete encoded Short with sound at normal speed"] };
}
