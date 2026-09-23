import { refreshVisualSourceFixture } from "./_visual-source-fixture";
/** Synthetic contract data only; no visual/source-quality claim. */
import { refreshNativeAssetUseFixture } from "./_native-short-origin-fixture";
import { writeFileSync } from "node:fs";
import path from "node:path";
import { canonicalJson, fileSha256 } from "../auto-edit-hash";
import { NATIVE_PREBUILD_COVERAGE, nativeShortPrebuildPlanHash, type NativePrebuildReview } from "../native-short-prebuild-review";
import { loadDirectorCatalog } from "../native-director-library";
import { fillLocalHookTemplate } from "../native-hook-template";
import { buildNativeCanvas, centeredNativeCaptionView } from "../native-short-composition";
import { nativePacingBindings, nativePacingVisualWindows } from "../native-short-pacing-observations";
import type { NativeShortProjectInput } from "../native-short-project";
import type { NativeAssetBinding } from "../native-short-strategy";

function assets(directory: string): NativeAssetBinding[] {
  const files = ["source.mp4", "gsap.min.js", "Inter-Bold.ttf", "selected.jpg", "alternate.jpg"];
  return files.map((name, index) => {
    const source = path.join(directory, name);
    writeFileSync(source, `TEST-only synthetic bytes ${name}`);
    const hash = fileSha256(source)!;
    return { path: source, sha256: hash, file: index === 0 ? `assets/${hash}.mp4`
      : `${index > 2 ? "references" : "assets"}/${name}`, role: index === 0 ? "source" : index > 2 ? "reference" : "runtime" };
  });
}

export function nativeShortFixture(directory: string): NativeShortProjectInput {
  const bindings = assets(directory), request = { selection: "auto", supportingVideo: "source-first" } as const;
  const copy = fillLocalHookTemplate(loadDirectorCatalog(), { anchor: "steps-toward-goal", slots: { count: "Two", goal: "test a saved plan" } });
  const input: NativeShortProjectInput = { schemaVersion: 1, request, assets: bindings,
    canvas: { title: "TEST native contract", frameRate: "25/1", totalFrames: 50, background: "#111111",
      sourceSize: { w: 1920, h: 1080 }, sourceFile: bindings[0].file,
      cuts: [{ start: 0, end: 2, speed: 1 }], segments: [{ startFrame: 0, endFrameExclusive: 50 }],
      occurrences: [[0, 0, 0, 0, 20, "Test", 0], [1, 0, 1, 20, 45, "words.", 0]], captionGroups: [[0], [1]],
      pictureViews: [{ startFrame: 0, endFrame: 50, crop: [500, 0, 607.5, 1080], box: [0, 0, 1080, 1920] }],
      captionViews: [centeredNativeCaptionView({ startFrame: 0, endFrame: 50, top: 1000 })],
      text: [], shapes: [], motion: [], titleCard: { copy, lines: [copy.text], palette: "paper-on-ink", endFrame: 25, top: 80, fontSize: 64 } },
    strategy: { schemaVersion: 1, request, selectedTreatment: "TEST presenter", selectionReason: "TEST source performs the explanation",
      rejectedTreatment: "TEST diagram has no distinct relationship to show", viewerBenefit: "TEST understand saved-plan consistency",
      hookReasonToWatch: "TEST concrete contract goal", payoff: "TEST source words only",
      references: [3, 4].map((index) => ({ assetFile: bindings[index].file, referenceId: `TEST-${index}`,
        observed: "TEST fixture observation, not actual visual review", adaptation: "TEST binding only" })),
      supportingSearch: { searchedSourceFiles: [bindings[0].file], candidates: [], conclusion: "TEST synthetic source has no supplemental evidence" },
      scenes: [{ startFrame: 0, endFrame: 50, viewingNeed: "TEST follow the speaker", format: "presenter", paneJobs: "TEST full portrait",
        before: "TEST opening state", action: "TEST spoken explanation", result: "TEST words retained", holdFrames: 5,
        visibleIds: ["source-0-0"], occurrenceIds: [0, 1], referenceIds: ["TEST-3"], exitReason: "TEST complete thought" }],
      review: { method: "local-editorial", findings: ["TEST binding-only fixture; no real creative review occurred"] } } };
  refreshNativePacingFixture(input);
  return input;
}

/** Explicitly re-author synthetic fixture budgets after a test's intended revision. */
export function refreshNativePacingFixture(input: NativeShortProjectInput): void {
  refreshVisualSourceFixture(input);
  input.strategy.schemaVersion = 3;
  const windows = nativePacingVisualWindows(input, buildNativeCanvas(input.canvas) + (input.extension?.markup ?? ""));
  refreshNativeAssetUseFixture(input);
  input.strategy.pacing = { schemaVersion: 1, ...nativePacingBindings(input), overallRhythm: "measured",
    rationale: "TEST synthetic timing, not a reviewed performance",
    deliveryReview: { method: "timing-and-transcript-only", notes: "TEST no listening occurred" },
    lanes: { cuts: "TEST retained clock", captions: "TEST existing phrase groups", title: "TEST opening orientation",
      supportingVisuals: "TEST explicit source windows", motion: "TEST wait for known motion", audio: "TEST source dialogue only" },
    beats: [{ startFrame: 0, endFrame: input.canvas.totalFrames, occurrenceIds: input.canvas.occurrences.map(word => word[0]),
      rhythm: "measured", reason: "TEST full retained sentence", attentionTarget: "TEST presenter",
      changeReason: "TEST stable delivery throughout" }],
    holds: windows.filter(row => row.requiredHold).map(row => {
      const startFrame = Math.max(row.startFrame, ...input.canvas.motion.filter(motion => motion.id === row.id)
        .map(motion => motion.startFrame + motion.durationFrames));
      return { targetId: row.id, startFrame, endFrame: row.endFrame,
        minimumFrames: Math.min(5, row.endFrame - startFrame), reason: "TEST budget, not a comprehension claim" };
    }) };
  refreshNativePrebuildReviewFixture(input);
}

/** TEST-only synthetic pass for structural admission tests; never a real creative approval. */
export function refreshNativePrebuildReviewFixture(input: NativeShortProjectInput): void {
  const directory = path.dirname(input.assets[0].path), evidence = path.join(directory, "TEST-prebuild-evidence.txt");
  writeFileSync(evidence, "TEST synthetic evidence; no footage inspection, playback, reviewer or creative approval.");
  const planHash = nativeShortPrebuildPlanHash(input);
  const receipt: NativePrebuildReview = { schemaVersion: 1, scope: "native-short-full-plan", planHash,
    reviewer: { identity: "TEST synthetic reviewer", sessionId: "TEST-review-session", plannerSessionId: "TEST-plan-session", independent: true },
    coverage: Object.fromEntries(NATIVE_PREBUILD_COVERAGE.map(key => [key,
      "TEST synthetic assessment only; not a production review"])) as NativePrebuildReview["coverage"],
    evidence: [{ path: evidence, sha256: fileSha256(evidence)! }],
    review: { schemaVersion: 1, stage: "plan", verdict: "pass", summary: "TEST structural fixture only; no creative approval",
      materialIssues: [], findings: [] } };
  const file = path.join(directory, `TEST-prebuild-${planHash}.json`);
  writeFileSync(file, canonicalJson(receipt));
  input.prebuildReview = { path: file, sha256: fileSha256(file)! };
}
