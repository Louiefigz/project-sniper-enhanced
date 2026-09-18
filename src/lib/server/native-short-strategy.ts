/** Bind creative decisions to a request, inspected references and executable visuals. */
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { parseShortDirection, type ShortDirectionRequest } from "@/lib/producer/short-direction";
import type { NativeCanvasInput } from "./native-short-composition";
import { assertNativeWebCaptureRange, type NativeWebCaptureBinding } from "./native-web-capture";
import type { NativeShortPacing } from "./native-short-pacing";
import type { NativeAssetOriginBinding, NativeShortAssetUsePlan } from "./native-short-asset-use-types";
import type { NativeShortStory } from "./native-short-story";

export interface NativeAssetBinding {
  file: string; path: string; sha256: string;
  role: "source" | "supporting-video" | "image" | "runtime" | "reference";
  webCapture?: NativeWebCaptureBinding;
  origin?: NativeAssetOriginBinding;
}
export interface SupportingShot {
  assetFile: string; sourceStart: number; sourceEnd: number;
  observed: string; role: "explanation" | "context" | "evidence";
  claimLimit: string; selected: boolean; reason: string;
  visibleId?: string; startFrame?: number; endFrame?: number;
}
export interface NativeShortStrategy {
  schemaVersion: 1 | 2 | 3; request: ShortDirectionRequest;
  /** Required for version 2; legacy version 1 projects remain readable. */
  pacing?: NativeShortPacing;
  /** Required for version 3; source policy and selected media share one contract. */
  assetUse?: NativeShortAssetUsePlan;
  /** Optional authored whole-story obligations; absence never implies story qualification. */
  story?: NativeShortStory;
  selectedTreatment: string; selectionReason: string; rejectedTreatment: string;
  viewerBenefit: string; hookReasonToWatch: string; payoff: string;
  references: Array<{ assetFile: string; referenceId: string; observed: string; adaptation: string }>;
  supportingSearch: { searchedSourceFiles: string[]; candidates: SupportingShot[]; conclusion: string };
  scenes: Array<{ startFrame: number; endFrame: number; viewingNeed: string;
    format: "presenter" | "demonstration" | "comparison" | "diagram";
    paneJobs: string; before: string; action: string; result: string; holdFrames: number;
    visibleIds: string[]; occurrenceIds: number[]; referenceIds: string[]; exitReason: string }>;
  review: { method: "local-editorial" | "independent-critic"; findings: string[] };
}

function text(value: unknown): void {
  if (typeof value !== "string" || value.trim().length < 3 || value.length > 2400 || value.includes("\0")) {
    throw new Error("Native strategy needs concrete bounded editorial explanations");
  }
}
function referenceBindings(strategy: NativeShortStrategy, assets: NativeAssetBinding[]): void {
  if (!Array.isArray(strategy.references) || strategy.references.length < 2 || strategy.references.length > 24) {
    throw new Error("Native strategy needs inspected selected and contrasting references");
  }
  for (const reference of strategy.references) {
    if (!assets.some((asset) => asset.file === reference.assetFile && asset.role === "reference")) {
      throw new Error("Native reference must bind an actual inspected local file");
    }
    [reference.referenceId, reference.observed, reference.adaptation].forEach(text);
  }
}
function supportingBindings(strategy: NativeShortStrategy, assets: NativeAssetBinding[], canvas: NativeCanvasInput): void {
  const search = strategy.supportingSearch;
  text(search.conclusion);
  if (!Array.isArray(search.candidates) || search.candidates.length > 64
      || !Array.isArray(search.searchedSourceFiles)) throw new Error("Invalid supporting-footage search record");
  if (strategy.request.supportingVideo === "source-first" && !search.searchedSourceFiles.includes(canvas.sourceFile)) {
    throw new Error("Supporting-footage strategy must inspect the supplied source before concluding the pool is empty");
  }
  if (search.searchedSourceFiles.some((file) => !assets.some((asset) => asset.file === file && asset.role === "source"))) {
    throw new Error("Supporting search cites an unbound source");
  }
  for (const shot of search.candidates) {
    if (!assets.some((asset) => asset.file === shot.assetFile && ["source", "supporting-video"].includes(asset.role))
        || ![shot.sourceStart, shot.sourceEnd].every(Number.isFinite) || shot.sourceStart < 0 || shot.sourceEnd <= shot.sourceStart
        || !["explanation", "context", "evidence"].includes(shot.role) || typeof shot.selected !== "boolean") {
      throw new Error("Supporting shot lacks an admitted source/range and explicit role");
    }
    [shot.observed, shot.claimLimit, shot.reason].forEach(text);
    assertNativeWebCaptureRange(assets.find((asset) => asset.file === shot.assetFile)!, shot.sourceEnd);
    if (shot.selected && (strategy.request.supportingVideo === "off" || !shot.visibleId
        || !Number.isSafeInteger(shot.startFrame) || !Number.isSafeInteger(shot.endFrame)
        || shot.startFrame! < 0 || shot.endFrame! <= shot.startFrame! || shot.endFrame! > canvas.totalFrames)) {
      throw new Error("Selected supporting shot needs an executable output window and enabled policy");
    }
  }
}
function sceneBindings(strategy: NativeShortStrategy, canvas: NativeCanvasInput, html: string): void {
  if (!Array.isArray(strategy.scenes) || !strategy.scenes.length || strategy.scenes.length > 64) throw new Error("Missing native strategy scenes");
  let next = 0;
  for (const scene of strategy.scenes) {
    if (scene.startFrame !== next || !Number.isSafeInteger(scene.endFrame) || scene.endFrame <= next
        || scene.endFrame > canvas.totalFrames || !Number.isSafeInteger(scene.holdFrames)
        || scene.holdFrames < 1 || scene.holdFrames > scene.endFrame - next) throw new Error("Strategy scenes must partition the actual output clock with readable holds");
    next = scene.endFrame;
    [scene.viewingNeed, scene.paneJobs, scene.before, scene.action, scene.result, scene.exitReason].forEach(text);
    if (!["presenter", "demonstration", "comparison", "diagram"].includes(scene.format)
        || !scene.referenceIds.length || scene.referenceIds.some((id) => !strategy.references.some((ref) => ref.referenceId === id))
        || !scene.occurrenceIds.length || scene.occurrenceIds.some((id) => !canvas.occurrences[id]
          || canvas.occurrences[id][3] >= scene.endFrame || canvas.occurrences[id][4] <= scene.startFrame)) {
      throw new Error("Strategy scene is missing its retained speech/reference bindings");
    }
    if (!scene.visibleIds.length || scene.visibleIds.some((id) => !html.includes(`id="${id}"`))) {
      throw new Error("Strategy describes a visual the native project does not execute");
    }
  }
  if (next !== canvas.totalFrames) throw new Error("Strategy omits part of the Short");
}

/** Structural grounding only; measurements and editorial judgment keep their own evidence. */
export function assertNativeShortStrategy(input: {
  strategy: NativeShortStrategy; request: ShortDirectionRequest;
  canvas: NativeCanvasInput; assets: NativeAssetBinding[]; html: string;
}): void {
  const { strategy, request, canvas, assets, html } = input;
  if (![1, 2, 3].includes(strategy.schemaVersion) || canonicalJsonSha256(parseShortDirection(strategy.request, "short"))
      !== canonicalJsonSha256(parseShortDirection(request, "short"))) throw new Error("Strategy changed the requested Short direction");
  [strategy.selectedTreatment, strategy.selectionReason, strategy.rejectedTreatment,
    strategy.viewerBenefit, strategy.hookReasonToWatch, strategy.payoff].forEach(text);
  referenceBindings(strategy, assets); supportingBindings(strategy, assets, canvas); sceneBindings(strategy, canvas, html);
  if (!strategy.review || !["local-editorial", "independent-critic"].includes(strategy.review.method)
      || !Array.isArray(strategy.review.findings) || !strategy.review.findings.length) throw new Error("Native strategy lacks its explicit review record");
  strategy.review.findings.forEach(text);
  for (const shot of strategy.supportingSearch.candidates.filter((row) => row.selected)) {
    if (!/^[a-z][a-z0-9-]{0,95}$/u.test(shot.visibleId!)) throw new Error("Supporting video identity is invalid");
    const element = [...html.matchAll(/<video\b[^>]*>/gu)].map((match) => match[0])
      .find((tag) => tag.includes(`id="${shot.visibleId}"`));
    const attribute = (name: string) => Number(new RegExp(`\\s${name}="([^"]+)"`, "u").exec(element ?? "")?.[1]);
    const [num, den] = canvas.frameRate.split("/").map(Number), fps = num / den;
    if (!element || !element.includes(`src="${shot.assetFile}"`) || !/\smuted(?:\s|>)/u.test(element)
        || !["data-start", "data-duration", "data-media-start"].map(attribute).every(Number.isFinite)
        || Math.abs(attribute("data-start") * fps - shot.startFrame!) > .00001
        || Math.abs(attribute("data-duration") * fps - (shot.endFrame! - shot.startFrame!)) > .00001
        || attribute("data-media-start") !== shot.sourceStart
        || Math.abs((shot.sourceEnd - shot.sourceStart) * fps - (shot.endFrame! - shot.startFrame!)) > .00001) {
      throw new Error("Selected supporting footage differs from its executable source/window or is not muted");
    }
  }
}
