/** Source-bound editorial pacing and declared viewing-budget checks. */
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { measureNativeShortPacing, nativePacingBindings, nativePacingVisualWindows } from "./native-short-pacing-observations";
import type { NativeShortProjectInput } from "./native-short-project";

export interface NativeShortPacing {
  schemaVersion: 1; timingHash: string; visualHash: string;
  overallRhythm: "brisk" | "measured" | "varied"; rationale: string;
  deliveryReview: { method: "source-listening" | "timing-and-transcript-only"; notes: string };
  lanes: { cuts: string; captions: string; title: string; supportingVisuals: string; motion: string; audio: string };
  beats: Array<{ startFrame: number; endFrame: number; occurrenceIds: number[];
    rhythm: "brisk" | "measured" | "pause"; reason: string; attentionTarget: string; changeReason: string }>;
  holds: Array<{ targetId: string; startFrame: number; endFrame: number; minimumFrames: number; reason: string }>;
}

function explanation(value: unknown): void {
  if (typeof value !== "string" || value.trim().length < 3 || value.length > 2400 || value.includes("\0")) {
    throw new Error("Pacing requires bounded editorial reasons, not an empty speed preset");
  }
}

function context(input: NativeShortProjectInput): NativeShortPacing {
  const plan = input.strategy.pacing;
  if (!plan || plan.schemaVersion !== 1 || !["brisk", "measured", "varied"].includes(plan.overallRhythm)) {
    throw new Error("New native strategies require a script-bound pacing plan");
  }
  const bindings = nativePacingBindings(input);
  if (plan.timingHash !== bindings.timingHash || plan.visualHash !== bindings.visualHash) {
    throw new Error("Pacing plan is stale after a speech, caption, visual or source revision");
  }
  explanation(plan.rationale);
  if (!plan.deliveryReview || !["source-listening", "timing-and-transcript-only"].includes(plan.deliveryReview.method)) {
    throw new Error("Pacing must identify the delivery review actually performed");
  }
  explanation(plan.deliveryReview.notes);
  for (const lane of ["cuts", "captions", "title", "supportingVisuals", "motion", "audio"] as const) explanation(plan.lanes?.[lane]);
  return plan;
}

function beatBindings(input: NativeShortProjectInput, plan: NativeShortPacing): void {
  if (!Array.isArray(plan.beats) || !plan.beats.length || plan.beats.length > 128) throw new Error("Pacing needs bounded complete beats");
  let next = 0;
  for (const beat of plan.beats) {
    if (beat.startFrame !== next || !Number.isSafeInteger(beat.endFrame) || beat.endFrame <= next
        || beat.endFrame > input.canvas.totalFrames || !["brisk", "measured", "pause"].includes(beat.rhythm)) {
      throw new Error("Pacing beats must partition the complete Short in output frames");
    }
    const expected = input.canvas.occurrences.filter(word => word[3] < beat.endFrame && word[4] > beat.startFrame).map(word => word[0]);
    if (canonicalJsonSha256(expected) !== canonicalJsonSha256(beat.occurrenceIds)) {
      throw new Error("Pacing beat lost its actual retained speech occurrences");
    }
    if (!expected.length && beat.rhythm !== "pause") throw new Error("A silent pacing beat needs an explicit pause decision");
    [beat.reason, beat.attentionTarget, beat.changeReason].forEach(explanation);
    next = beat.endFrame;
  }
  if (next !== input.canvas.totalFrames) throw new Error("Pacing omits part of the Short");
  const rhythms = new Set(plan.beats.map(beat => beat.rhythm));
  if (plan.overallRhythm === "varied" ? rhythms.size < 2 : !rhythms.has(plan.overallRhythm)) {
    throw new Error("Pacing overall rhythm contradicts its declared local beats");
  }
}

function holdBindings(input: NativeShortProjectInput, plan: NativeShortPacing, html: string): void {
  if (!Array.isArray(plan.holds) || plan.holds.length > 512) throw new Error("Pacing viewing budgets are invalid");
  const windows = nativePacingVisualWindows(input, html);
  for (const hold of plan.holds) {
    const target = windows.find(row => row.id === hold.targetId);
    if (!target || ![hold.startFrame, hold.endFrame, hold.minimumFrames].every(Number.isSafeInteger)
        || hold.minimumFrames < 1 || hold.startFrame < target.startFrame || hold.endFrame > target.endFrame
        || hold.endFrame - hold.startFrame < hold.minimumFrames) {
      throw new Error(`Pacing viewing budget for ${hold.targetId} exceeds its executable hold`);
    }
    if (input.canvas.motion.some(row => row.id === hold.targetId && row.startFrame < hold.endFrame
        && row.startFrame + row.durationFrames > hold.startFrame)) {
      throw new Error(`Pacing readable hold for ${hold.targetId} overlaps its known motion`);
    }
    explanation(hold.reason);
  }
  for (const target of windows.filter(row => row.requiredHold)) {
    if (!plan.holds.some(hold => hold.targetId === target.id)) throw new Error(`Pacing has no viewing budget for ${target.id}`);
  }
}

/** Legacy projects remain readable; new writers explicitly require strategy version 2. */
export function assertNativeShortPacing(input: NativeShortProjectInput, html: string): void {
  if (input.strategy.schemaVersion === 1 && input.strategy.pacing === undefined) return;
  if (![2, 3].includes(input.strategy.schemaVersion)) throw new Error("Pacing requires native strategy version 2 or 3");
  measureNativeShortPacing(input.canvas);
  const plan = context(input);
  beatBindings(input, plan); holdBindings(input, plan, html);
}

/** Auditable observations and declared budgets, with explicit limits on automated checks. */
export function nativeShortPacingReport(input: NativeShortProjectInput, html: string) {
  assertNativeShortPacing(input, html);
  const observations = measureNativeShortPacing(input.canvas), plan = input.strategy.pacing;
  return { schemaVersion: 1, scope: "native-short-pacing-observations-and-declared-budgets",
    ...nativePacingBindings(input), observations,
    strategyStatus: plan ? "source-bound-declared-budgets-checked" : "legacy-unplanned",
    visualWindows: nativePacingVisualWindows(input, html),
    plan: plan ?? null,
    beatMeasurements: plan?.beats.map(beat => ({ startFrame: beat.startFrame, endFrame: beat.endFrame,
      wordsPerMinute: beat.occurrenceIds.length * 60 * observations.fps / (beat.endFrame - beat.startFrame),
      rhythm: beat.rhythm })) ?? [],
    reviewRequired: ["Whole-Short delivery and rhythm with sound at normal speed",
      "Phone-size comprehension, attention competition and the adequacy of authored minimum holds",
      ...(input.canvas.captionMode === "source-burned"
        ? ["Source-burned caption text, visibility and timing in actual pixels; transcript groups do not measure them"] : []),
      ...(input.extension ? ["Custom CSS/GSAP visibility and internal developments throughout each selected hold"] : [])],
    audienceComprehension: "not-established", finishedPlaybackReview: "not-performed-by-this-command" };
}
