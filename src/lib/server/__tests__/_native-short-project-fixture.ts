import { refreshVisualSourceFixture } from "./_visual-source-fixture";
/** Synthetic contract data only; no visual/source-quality claim. */
import { refreshNativeAssetUseFixture } from "./_native-short-origin-fixture";
import { readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import path from "node:path";
import { canonicalJson, fileSha256 } from "../auto-edit-hash";
import { NATIVE_PREBUILD_COVERAGE, nativeShortPrebuildPlanHash, type NativePrebuildReview } from "../native-short-prebuild-review";
import { loadDirectorCatalog } from "../native-director-library";
import { fillLocalHookTemplate } from "../native-hook-template";
import { buildNativeCanvas, centeredNativeCaptionView } from "../native-short-composition";
import { nativePacingBindings, nativePacingVisualWindows } from "../native-short-pacing-observations";
import type { NativeShortProjectInput } from "../native-short-project";
import type { NativeAssetBinding } from "../native-short-strategy";
import { pythonInterpreter } from "../../../app/api/_lib/spawn-python";
import { typedRecordParts } from "./_native-review-fixture";
import { resolveVisualPlanBinding } from "../visual-plan-binding";

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
  bindNativeVisualPlanFixture(input, directory);
  refreshNativeRequestPacketFixture(input);
  refreshNativePacingFixture(input);
  return input;
}

/** Keep synthetic packet inventory current after a test intentionally edits its fixture. */
export function refreshNativeRequestPacketFixture(input: NativeShortProjectInput): void {
  const directory = path.dirname(input.assets[0].path);
  const packetPath = input.requestPacket?.path ?? path.join(directory, "TEST-SHORT-REQUEST.json");
  const source = input.assets.find(asset => asset.role === "source")!;
  const supporting = input.assets.filter(asset => ["supporting-video", "image", "reference"].includes(asset.role));
  const packet = { schemaVersion: 1,
    intent: { mode: "short", scope: "produced", lanes: {}, shortDirection: input.request },
    sources: [{ path: source.path, sha256: source.sha256, transcript: null }],
    availableSupportingAssets: supporting.map(({ path, sha256 }) => ({ path, sha256 })),
    selectedReferences: supporting.filter(asset => asset.role === "reference")
      .map(({ path, sha256 }) => ({ path, sha256 })), relatedStyleContext: null };
  writeFileSync(packetPath, canonicalJson(packet));
  input.requestPacket = { path: packetPath, sha256: fileSha256(packetPath)! };
}

/** Explicitly re-author synthetic fixture budgets after a test's intended revision. */
export function refreshNativePacingFixture(input: NativeShortProjectInput): void {
  if (input.requestPacket?.path.includes("TEST-SHORT-REQUEST.json")) refreshNativeRequestPacketFixture(input);
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

/** TEST-only synthetic schema-2 pass for structural admission tests; never a real creative approval. Its role packet
 * binds no batch (the TEST given check in _native-review-fixture answers for it) and nobody inspected anything. */
export function refreshNativePrebuildReviewFixture(input: NativeShortProjectInput): void {
  const directory = path.dirname(input.assets[0].path), planHash = nativeShortPrebuildPlanHash(input);
  const reviewer = { identity: "TEST synthetic reviewer", sessionId: "TEST-review-session", plannerSessionId: "TEST-plan-session",
    independent: true as const };
  const reviewed = path.join(directory, `TEST-reviewed-plan-${planHash}.json`);
  writeFileSync(reviewed, canonicalJson({ ...input, prebuildReview: undefined }));
  const parts = typedRecordParts(directory, "plan-critic", { reviewer, verdict: "pass", inspection: { entries: [], approves: [] } },
    { plan: { path: reviewed, sha256: fileSha256(reviewed)!, planHash } }, [reviewed]);
  const receipt: NativePrebuildReview = { schemaVersion: 2, scope: "native-short-full-plan", planHash, reviewer,
    coverage: Object.fromEntries(NATIVE_PREBUILD_COVERAGE.map(key => [key,
      "TEST synthetic assessment only; not a production review"])) as NativePrebuildReview["coverage"],
    evidence: parts.evidence,
    review: { schemaVersion: 1, stage: "plan", verdict: "pass", summary: "TEST structural fixture only; no creative approval",
      materialIssues: [], findings: [] },
    inspection: { schemaVersion: 1, entries: [], approves: [] },
    submission: parts.submission as NativePrebuildReview["submission"], approvedContent: parts.approvedContent };
  const file = path.join(directory, `TEST-prebuild-${planHash}.json`);
  writeFileSync(file, canonicalJson(receipt));
  input.prebuildReview = { path: file, sha256: fileSha256(file)! };
}

/** Apply a TEST change to the fixture's plan review; a typed record's bound observations are re-written to mirror its
 * reviewer, verdict, findings and inspection, as the typed submission would have. Structural tests only. */
export function reviseNativePrebuildReviewFixture(input: NativeShortProjectInput,
  change: (review: NativePrebuildReview) => void): void {
  const file = input.prebuildReview!.path, review = JSON.parse(readFileSync(file, "utf8")) as NativePrebuildReview;
  change(review);
  if (review.schemaVersion === 2 && review.inspection) {
    const binding = review.evidence[0], observations = JSON.parse(readFileSync(binding.path, "utf8")) as Record<string, unknown>;
    Object.assign(observations, { reviewer: review.reviewer, verdict: review.review.verdict,
      materialIssues: review.review.materialIssues, findings: review.review.findings,
      inspection: review.inspection.entries, approves: review.inspection.approves });
    writeFileSync(binding.path, JSON.stringify(observations));
    binding.sha256 = fileSha256(binding.path)!;
  }
  writeFileSync(file, canonicalJson(review));
  input.prebuildReview!.sha256 = fileSha256(file)!;
}

/** Attach one fully admitted TEST visual plan and its exact executable mapping. */
export function bindNativeVisualPlanFixture(input: NativeShortProjectInput,
  directory: string): void {
  const file = path.join(directory, "TEST-VISUAL-PLAN.json");
  const source = input.assets.find(row => row.role === "source")!;
  const code = [
    "import json,os,sys",
    "from _visual_plan_fixture import candidate,materialize_plan_pins,opportunity,reseal_controller_authorities,visual_plan",
    "from planner.visual_plan_allocator import allocate_visual_plan",
    "row=candidate('candidate:one',modality='source-footage',routeClass='native')",
    "row['source']={'recordId':'asset:source','path':sys.argv[2],'sha256':sys.argv[3],'sourceSha256':sys.argv[3],'range':{'startFrame':0,'endFrameExclusive':50}}",
    "opp=opportunity('opp:one',0,[row],timing={'startFrame':0,'endFrameExclusive':50})",
    "value=visual_plan(opp)",
    "value['project']['fps']={'numerator':25,'denominator':1}",
    "value=reseal_controller_authorities(value)",
    "value=materialize_plan_pins(value,os.path.join(os.path.dirname(sys.argv[1]),'TEST-visual-plan-pins'))",
    "open(sys.argv[1],'w').write(json.dumps(allocate_visual_plan(value)))",
  ].join("\n");
  execFileSync(pythonInterpreter(), ["-B", "-c", code, file,
    source.path, source.sha256], {
    cwd: path.join(process.cwd(), "scripts/producer"),
    env: { ...process.env, PYTHONPATH: ".:tests", PYTHONDONTWRITEBYTECODE: "1" },
  });
  const binding = resolveVisualPlanBinding(file);
  if (!binding) throw new Error("TEST visual-plan fixture was not written");
  const html = buildNativeCanvas(input.canvas);
  const markup = html.match(/<video\b[^>]*id="source-0-0"[^>]*>[\s\S]*?<\/video>/u)?.[0];
  if (!markup) throw new Error("TEST source execution markup is missing");
  input.visualPlan = binding;
  input.strategy.visualPlanApplication = { schemaVersion: 1, route: "native-short",
    visualPlanSha256: binding.visualPlanSha256, decisions: [{
      opportunityId: "opp:one", candidateId: "candidate:one",
      anatomy: "split-card", development: "label-then-proof",
      startFrame: 0, endFrameExclusive: 50, sceneIndexes: [0],
      visibleIds: [input.strategy.scenes[0].visibleIds[0]], catalogBindings: [],
      binding: { kind: "media", elementId: "source-0-0",
        sourceRecordId: "asset:source", assetFile: source.file, sourceSha256: source.sha256,
        sourceRange: { startFrame: 0, endFrameExclusive: 50 },
        outputRange: { startFrame: 0, endFrameExclusive: 50 },
        elementSha256: createHash("sha256").update(markup).digest("hex") },
    }] };
}
