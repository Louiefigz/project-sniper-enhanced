import { nativeCatalogFiles, type NativeCatalogFile } from "./native-catalog-files";
import { assertNativeVisualSources, type VisualSourceReceipt } from "./visual-source-admission";
/** Local native project assembly shared by CLI and stored-proposal adapters. */
import { constants, copyFileSync, lstatSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import path from "node:path";
import { canonicalJson, canonicalJsonSha256, fileSha256 } from "./auto-edit-hash";
import { buildNativeCanvas, nativeExtensionMount, type NativeCanvasInput } from "./native-short-composition";
import { assertUserTitleCopy, fillLocalHookTemplate } from "./native-hook-template";
import { catalogFromSources, loadDirectorCatalog, type DirectorCatalog } from "./native-director-library";
import { assertNativeShortStrategy, type NativeAssetBinding, type NativeShortStrategy } from "./native-short-strategy";
import { parseShortDirection, shortDirectionInstructions, type ShortDirectionRequest } from "@/lib/producer/short-direction";
import { assertNativeWebCapture } from "./native-web-capture";
import { assertNativeShortPacing, nativeShortPacingReport } from "./native-short-pacing";
import { assertNativeShortAssetUse, nativeShortAssetUseReport } from "./native-short-asset-use";
import { assertNativeShortStory, nativeShortStoryReport } from "./native-short-story";
import { assertNativeShortAudio, type NativeShortAudio } from "./native-short-audio";
import { assertGuidedNativeBinding, assertGuidedNativeLocation, type GuidedNativeProjectBinding, type NativeGuidedDependencies } from "./guided-native-binding";
import { preparedProjectMedia, type PreparedSourcesBinding } from "./native-selected-sources";
import type { NativePrebuildReviewBinding } from "./native-short-prebuild-review";
import { assertNativeReviewMode, assertNativeReviewPublication, nativeProjectReviewAuthority, nativeReviewFiles,
  nativeReviewManifest, type NativeReviewMode, type NativeShortDraftAuthority } from "./native-short-draft";
import { nativeVisualPlanSource, type VisualPlanBinding } from "./visual-plan-binding";
import { assertNativeVisualPlanApplication } from "./native-visual-plan-application";
import { assertCurrentNativeShortAuthority, assertNativeShortReadAuthority, nativeAssetUseOptions,
  verifyNativeShortRequest, type LegacyNativeShortReadAuthority } from "./native-short-request-binding";
import { deriveNativeReviewRegions, NATIVE_REVIEW_REGIONS_FILE, type NativeReviewRegionMap } from "./native-review-regions";
import { assertNativeShortLineage, nativeShortLineage } from "./native-short-lineage";
import { assertStudioHostIds } from "./native-studio-host-ids";
import { assertNativeRevealDeclarations } from "./native-reveal-declarations";
export { assertNativeShortIntent } from "./native-short-request-binding";
export interface NativeSceneExtension { markup: string; css: string; motion: string }
export interface NativeShortProjectInput {
  visualSources?: VisualSourceReceipt;
  catalogFiles?: NativeCatalogFile[];
  catalogTitle?: { file: string; copy: import("./native-hook-template").NativeTitleCopy };
  schemaVersion: 1; request: ShortDirectionRequest; strategy: NativeShortStrategy;
  canvas: NativeCanvasInput; assets: NativeAssetBinding[];
  requestPacket?: { path: string; sha256: string };
  visualPlan?: VisualPlanBinding;
  /** Separate independent full-plan judgment, mandatory for new materialization. */
  prebuildReview?: NativePrebuildReviewBinding;
  /** Review-draft authority written only by build-draft; final readers and exports refuse it. */
  draft?: NativeShortDraftAuthority;
  /** Verified small working media; canvas and transcripts retain original source time. */
  preparedSources?: PreparedSourcesBinding;
  guidedBinding?: GuidedNativeProjectBinding;
  /** Source-specific cleanup and gain, before shared float mastering. */
  audioFinishing?: NativeShortAudio;
  /** Reviewed project-owned native mechanisms, never a replacement caption/audio stack. */
  extension?: NativeSceneExtension;
  /** Authored checkpoints for a developing object; checked on real native frames. */
  expectations?: Array<{ frame: number; id: string; property: "opacity" | "clipPath" | "textContent"; equals: string }>;
}
/** Mount editable scene mechanisms while keeping timing, source, title and captions shared. */
export function assembleNativeShortHtml(input: NativeShortProjectInput): string {
  if (input.schemaVersion !== 1) throw new Error("Unsupported native Short project");
  parseShortDirection(input.request, "short");
  const [rateNum, rateDen] = input.canvas.frameRate.split("/").map(Number);
  assertNativeShortAudio(input.audioFinishing, input.canvas.totalFrames * rateDen / rateNum);
  const extension = input.extension ?? { markup: "", css: "", motion: "" };
  if (Object.values(extension).some((value) => typeof value !== "string" || value.length > 128 * 1024)
      || /<\/?(?:script|iframe|audio)\b/iu.test(extension.markup)
      || /<\/?script\b/iu.test(extension.motion)) throw new Error("Native scene extension contains an unsupported script, audio or frame element");
  let html = buildNativeCanvas(input.canvas);
  // Never assume caption-0-0 exists: a suppressed opening has no first caption element.
  const caption = nativeExtensionMount(input.canvas);
  if (extension.markup && !html.includes(caption)) throw new Error("Native extension needs the shared caption mounting point");
  html = html.replace("</head>", `${extension.css}</head>`)
    .replace(caption, extension.markup + caption)
    .replace("const tl=gsap.timeline({paused:true});", "const tl=gsap.timeline({paused:true});" + extension.motion);
  const ids = [...html.matchAll(/\sid="([^"]+)"/gu)].map((match) => match[1]);
  if (new Set(ids).size !== ids.length) throw new Error("Native extension duplicates a shared element identity");
  if (/(?:src|href)=["'](?:https?:|\/\/|references\/)|url\(["']?(?:https?:|\/\/|references\/)/iu.test(html)) {
    throw new Error("Native project must use staged local assets; reference pixels cannot become production footage");
  }
  if ((input.expectations?.length ?? 0) > 128 || input.expectations?.some((row) => !Number.isSafeInteger(row.frame)
      || row.frame < 0 || row.frame >= input.canvas.totalFrames || !ids.includes(row.id)
      || !["opacity", "clipPath", "textContent"].includes(row.property) || typeof row.equals !== "string")) {
    throw new Error("Native checkpoints need an actual element, property and output frame");
  }
  assertNativeShortStrategy({ ...input, html });
  assertNativeShortPacing(input, html);
  assertNativeShortAssetUse(input, html, nativeAssetUseOptions(input));
  assertNativeShortStory(input, html);
  assertNativeVisualSources(input);
  const catalogFiles = nativeCatalogFiles(input.catalogFiles);
  for (const file of Object.keys(catalogFiles)) {
    if (!html.includes(`data-composition-src="${file}"`)) throw new Error("Catalog file must be mounted in the authored scene");
  }
  assertNativeRevealDeclarations(input, catalogFiles);
  assertNativeVisualPlanApplication({ binding: input.visualPlan,
    application: input.strategy.visualPlanApplication, scenes: input.strategy.scenes,
    html, catalogFiles: input.catalogFiles, assets: input.assets,
    styleApplication: input.strategy.styleApplication });
  return html;
}
function verifyAssets(input: NativeShortProjectInput): void {
  if (!Array.isArray(input.assets) || input.assets.length < 3 || input.assets.length > 128
      || new Set(input.assets.map((row) => row.file)).size !== input.assets.length) throw new Error("Native asset inventory is missing or duplicates a path");
  for (const asset of input.assets) {
    if (input.strategy.schemaVersion === 3 && asset.role === "runtime"
        && !["assets/gsap.min.js", "assets/Inter-Bold.ttf"].includes(asset.file)) {
      throw new Error("Native runtime assets are limited to the shared script and font");
    }
    if (!/^(assets|references)\/[a-zA-Z0-9][a-zA-Z0-9._-]{0,140}$/u.test(asset.file)
        || !["source", "supporting-video", "image", "runtime", "reference"].includes(asset.role)
        || !path.isAbsolute(asset.path) || realpathSync(asset.path) !== asset.path
        || !lstatSync(asset.path).isFile() || !/^[a-f0-9]{64}$/u.test(asset.sha256)
        || fileSha256(asset.path) !== asset.sha256) throw new Error(`Native asset is missing, changed or not canonical: ${asset.file}`);
    assertNativeWebCapture(asset);
  }
  const source = input.assets.find((row) => row.file === input.canvas.sourceFile && row.role === "source");
  if (!source || source.file !== `assets/${source.sha256}.mp4`
      || !["assets/gsap.min.js", "assets/Inter-Bold.ttf"].every((file) => input.assets.some((row) => row.file === file && row.role === "runtime"))) {
    throw new Error("Native project requires its exact source, pinned GSAP and loaded font");
  }
}
function verifyTitle(input: NativeShortProjectInput, catalog: DirectorCatalog): void {
  const title = input.canvas.titleCard ?? input.catalogTitle;
  if (!title) throw new Error("Native Short needs a selected catalog title before assembly");
  if (input.catalogTitle && (input.canvas.titleCard || !input.catalogFiles?.some(row => row.file === input.catalogTitle?.file))) {
    throw new Error("Catalog title must select one mounted catalog file without a duplicate built-in title");
  }
  if (title.copy?.scope === "user-supplied-title") {
    assertUserTitleCopy(title.copy);
    return;
  }
  const actual = fillLocalHookTemplate(catalog, title.copy);
  if (canonicalJsonSha256(actual) !== canonicalJsonSha256(title.copy)) throw new Error("Native title differs from the canonical selected template or library");
}
/** Generated from the staged executable mounts; never authored and never part of the plan hash. */
function reviewRegionMap(input: NativeShortProjectInput, media: ReturnType<typeof preparedProjectMedia>): NativeReviewRegionMap | undefined {
  return deriveNativeReviewRegions(media.html, nativeCatalogFiles(input.catalogFiles), input.canvas);
}
function projectFiles(input: NativeShortProjectInput, html: string, catalog: DirectorCatalog,
  media: ReturnType<typeof preparedProjectMedia>): Record<string, string> {
  const visualPlan = nativeVisualPlanSource(input.visualPlan, "short"), regions = reviewRegionMap(input, media);
  return {
    "index.html": media.html,
    ...nativeCatalogFiles(input.catalogFiles),
    ...(media.report ? { "PREPARED-SOURCES.json": canonicalJson(media.report) } : {}),
    "hyperframes.json": canonicalJson({ paths: { blocks: "compositions", components: "compositions/components", assets: "assets" } }),
    "SHORT-PROJECT.json": canonicalJson(input),
    ...(regions ? { [NATIVE_REVIEW_REGIONS_FILE]: canonicalJson(regions) } : {}),
    ...(input.guidedBinding ? { "GUIDED-PROPOSAL.json": canonicalJson(input.guidedBinding) } : {}),
    "DIRECTOR-LIBRARY.json": canonicalJson(catalog),
    ...(input.strategy.schemaVersion >= 2 ? { "PACING-REPORT.json": canonicalJson(nativeShortPacingReport(input, html)) } : {}),
    ...(input.strategy.schemaVersion === 3 ? { "ASSET-USE-REPORT.json": canonicalJson(nativeShortAssetUseReport(input, html, nativeAssetUseOptions(input))) } : {}),
    ...(input.strategy.story ? { "STORY-REPORT.json": canonicalJson(nativeShortStoryReport(input, html)) } : {}),
    ...(input.strategy.styleApplication ? { "STYLE-APPLICATION.json": canonicalJson(input.strategy.styleApplication) } : {}),
    ...(input.strategy.visualPlanApplication
      ? { "VISUAL-PLAN-APPLICATION.json": canonicalJson(input.strategy.visualPlanApplication) } : {}),
    ...(visualPlan ? { "VISUAL-PLAN.json": visualPlan } : {}),
    "BRIEF.md": `# ${input.canvas.title}\n\n${shortDirectionInstructions(input.request)}\n\n`
      + `Selected treatment: ${input.strategy.selectedTreatment}\n\n${input.strategy.selectionReason}\n\n`
      + `Viewer benefit: ${input.strategy.viewerBenefit}\n\nReason to watch: ${input.strategy.hookReasonToWatch}\n\n`
      + `Hook: ${(input.canvas.titleCard ?? input.catalogTitle)!.copy.text}\n\nPayoff: ${input.strategy.payoff}\n`,
    "STORYBOARD.md": input.strategy.scenes.map((scene) => `## Frames ${scene.startFrame}–${scene.endFrame}\n\n`
      + `${scene.viewingNeed}\n\n${scene.before} → ${scene.action} → ${scene.result}\n\n`
      + `View: ${scene.paneJobs}\n\nHold: ${scene.holdFrames} frames. Exit: ${scene.exitReason}\n\n`
      + `References: ${scene.referenceIds.join(", ")}\n`).join("\n"),
  };
}
/** New isolated project only; asset copies cannot mutate the original recording. A rebuilt
 * revision names its verified parent so its logical clip identity survives the new folder. */
export function writeNativeShortProject(input: NativeShortProjectInput, destination: string,
  dependencies: NativeGuidedDependencies = {}, options: { parent?: string } = {}) {
  if (input.strategy.schemaVersion !== 3) throw new Error("New native builds require strategy version 3 with pacing and asset-use decisions; legacy projects remain readable");
  if ("reviewRegions" in input) throw new Error("REVIEW-REGIONS.json is derived from the executable mounts; omit reviewRegions");
  assertCurrentNativeShortAuthority(input);
  const lineage = nativeShortLineage(options.parent, parent => readNativeShortProject(parent, {}, undefined, "draft"));
  const started = performance.now(), review = nativeProjectReviewAuthority(input);
  const directory = path.resolve(destination), catalog = loadDirectorCatalog();
  if (realpathSync(path.dirname(directory)) !== path.dirname(directory)) throw new Error("Native project parent must be canonical");
  verifyAssets(input); verifyNativeShortRequest(input); verifyTitle(input, catalog);
  assertGuidedNativeLocation(input, { directory }, dependencies);
  assertGuidedNativeBinding(input, dependencies);
  const html = assembleNativeShortHtml(input); verifyNativeShortRequest(input, html);
  const media = preparedProjectMedia(input, html);
  const files = { ...projectFiles(input, html, catalog, media), ...nativeReviewFiles(review) };
  assertStudioHostIds(files);
  mkdirSync(directory, { mode: 0o700 });
  for (const name of ["assets", "references", "compositions"]) mkdirSync(path.join(directory, name), { mode: 0o700 });
  for (const asset of media.assets) {
    copyFileSync(asset.path, path.join(directory, asset.file), constants.COPYFILE_EXCL | constants.COPYFILE_FICLONE);
    if (fileSha256(path.join(directory, asset.file)) !== asset.sha256) throw new Error("Native asset changed while staging");
  }
  for (const [name, content] of Object.entries(files)) writeFileSync(path.join(directory, name), content, { flag: "wx", mode: 0o600 });
  verifyAssets(input); verifyNativeShortRequest(input, html);
  assertGuidedNativeLocation(input, { directory }, dependencies);
  assertGuidedNativeBinding(input, dependencies);
  assertNativeReviewPublication(input, directory, nativeReviewManifest(review));
  const manifest = { schemaVersion: 1, scope: "native-short-review-project", projectHash: canonicalJsonSha256(input),
    files: [...Object.keys(files), ...media.assets.map((asset) => asset.file)].map((file) => ({ file, sha256: fileSha256(path.join(directory, file)) })),
    elapsedMs: performance.now() - started, sourceVerified: true, structuralStrategyChecks: "passed",
    reviewMethod: input.strategy.review.method, ...nativeReviewManifest(review),
    pixelChecks: "not-run", audioChecks: "not-run", humanApproved: false, lineage };
  writeFileSync(path.join(directory, "PROJECT-MANIFEST.json"), canonicalJson(manifest), { flag: "wx", mode: 0o600 });
  return { directory, manifest };
}
function expectedProjectFiles(input: NativeShortProjectInput,
  media: ReturnType<typeof preparedProjectMedia>, regions: NativeReviewRegionMap | undefined): string[] {
  return ["index.html", "hyperframes.json", "SHORT-PROJECT.json", "DIRECTOR-LIBRARY.json", "BRIEF.md", "STORYBOARD.md",
    ...(regions ? [NATIVE_REVIEW_REGIONS_FILE] : []),
    ...(input.strategy.schemaVersion >= 2 ? ["PACING-REPORT.json"] : []), ...(input.strategy.schemaVersion === 3 ? ["ASSET-USE-REPORT.json"] : []),
    ...(input.strategy.story ? ["STORY-REPORT.json"] : []), ...(input.strategy.styleApplication ? ["STYLE-APPLICATION.json"] : []),
    ...(input.strategy.visualPlanApplication ? ["VISUAL-PLAN-APPLICATION.json"] : []),
    ...(input.visualPlan ? ["VISUAL-PLAN.json"] : []), ...(input.guidedBinding ? ["GUIDED-PROPOSAL.json"] : []),
    ...(input.prebuildReview ? ["PREBUILD-REVIEW.json"] : []), ...(media.report ? ["PREPARED-SOURCES.json"] : []),
    ...Object.keys(nativeCatalogFiles(input.catalogFiles)), ...media.assets.map((asset) => asset.file)].sort();
}
/** Reopen the exact executable project; edited/stale projects need a new build. */
export function readNativeShortProject(directory: string, dependencies: NativeGuidedDependencies = {},
  legacyAuthority?: LegacyNativeShortReadAuthority, mode: NativeReviewMode = "final"): NativeShortProjectInput {
  const manifest = JSON.parse(readFileSync(path.join(directory, "PROJECT-MANIFEST.json"), "utf8"));
  const input: NativeShortProjectInput = JSON.parse(readFileSync(path.join(directory, "SHORT-PROJECT.json"), "utf8"));
  assertNativeReviewMode(input, manifest, mode);
  assertNativeShortReadAuthority(input, directory, legacyAuthority);
  const visualPlan = nativeVisualPlanSource(input.visualPlan, "short");
  const html = assembleNativeShortHtml(input), media = preparedProjectMedia(input, html);
  const regions = reviewRegionMap(input, media), expected = expectedProjectFiles(input, media, regions);
  if (manifest.schemaVersion !== 1 || manifest.scope !== "native-short-review-project" || !Array.isArray(manifest.files)
      || canonicalJsonSha256(manifest.files.map((row: { file: string }) => row.file).sort()) !== canonicalJsonSha256(expected)) {
    throw new Error("Native project manifest omits or duplicates required files");
  }
  for (const file of manifest.files) {
    if (!/^(?:[A-Z-]+\.json|index\.html|hyperframes\.json|BRIEF\.md|STORYBOARD\.md|(?:assets|references|compositions)\/[\w.-]+)$/u.test(file.file)
        || fileSha256(path.join(directory, file.file)) !== file.sha256) throw new Error("Native project changed since assembly");
  }
  if (canonicalJsonSha256(input) !== manifest.projectHash) throw new Error("Native project request/strategy changed");
  if (manifest.lineage !== undefined) assertNativeShortLineage(manifest.lineage);
  if (regions && readFileSync(path.join(directory, NATIVE_REVIEW_REGIONS_FILE), "utf8") !== canonicalJson(regions)) {
    throw new Error("Native review region map differs from its executable mounts");
  }
  const frozenCatalog = JSON.parse(readFileSync(path.join(directory, "DIRECTOR-LIBRARY.json"), "utf8"));
  verifyTitle(input, catalogFromSources(frozenCatalog.sources));
  verifyAssets(input); verifyNativeShortRequest(input, html);
  assertGuidedNativeLocation(input, { directory, legacyV9Read: true }, dependencies);
  assertGuidedNativeBinding(input, dependencies);
  assertNativeReviewPublication(input, directory, manifest);
  if (input.guidedBinding && readFileSync(path.join(directory, "GUIDED-PROPOSAL.json"), "utf8") !== canonicalJson(input.guidedBinding)) {
    throw new Error("Guided proposal sidecar differs from its persistent native project binding");
  }
  for (const asset of media.assets) {
    if (fileSha256(path.join(directory, asset.file)) !== asset.sha256) throw new Error("Staged native asset changed");
  }
  if (readFileSync(path.join(directory, "index.html"), "utf8") !== media.html) throw new Error("Native executable differs from its strategy/canvas");
  if (media.report && readFileSync(path.join(directory, "PREPARED-SOURCES.json"), "utf8") !== canonicalJson(media.report)) {
    throw new Error("Native prepared-source mapping differs from its executable media");
  }
  if (input.strategy.schemaVersion >= 2 && readFileSync(path.join(directory, "PACING-REPORT.json"), "utf8")
      !== canonicalJson(nativeShortPacingReport(input, html))) throw new Error("Native pacing report differs from its actual source and plan");
  if (input.strategy.schemaVersion === 3 && readFileSync(path.join(directory, "ASSET-USE-REPORT.json"), "utf8")
      !== canonicalJson(nativeShortAssetUseReport(input, html, nativeAssetUseOptions(input)))) throw new Error("Native asset-use report differs from its source and decisions");
  if (input.strategy.story && readFileSync(path.join(directory, "STORY-REPORT.json"), "utf8")
      !== canonicalJson(nativeShortStoryReport(input, html))) throw new Error("Native story report differs from its authored obligations");
  if (input.strategy.styleApplication && readFileSync(path.join(directory, "STYLE-APPLICATION.json"), "utf8")
      !== canonicalJson(input.strategy.styleApplication)) throw new Error("Native style application differs from its authored choices");
  if (input.strategy.visualPlanApplication
      && readFileSync(path.join(directory, "VISUAL-PLAN-APPLICATION.json"), "utf8")
      !== canonicalJson(input.strategy.visualPlanApplication)) {
    throw new Error("Native visual-plan application differs from its executable choices");
  }
  if (visualPlan && readFileSync(path.join(directory, "VISUAL-PLAN.json"), "utf8") !== visualPlan) throw new Error("Native visual plan differs from its frozen planning authority");
  return input;
}
