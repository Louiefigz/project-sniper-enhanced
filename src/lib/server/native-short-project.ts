/** Local native project assembly shared by CLI and stored-proposal adapters. */
import { constants, copyFileSync, lstatSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import path from "node:path";
import { canonicalJson, canonicalJsonSha256, fileSha256 } from "./auto-edit-hash";
import { buildNativeCanvas, type NativeCanvasInput } from "./native-short-composition";
import { fillLocalHookTemplate } from "./native-hook-template";
import { loadDirectorCatalog, type DirectorCatalog } from "./native-director-library";
import { assertNativeShortStrategy, type NativeAssetBinding, type NativeShortStrategy } from "./native-short-strategy";
import { parseShortDirection, shortDirectionInstructions, shortMediaPolicy, AUTOMATIC_SHORT_DIRECTION, type ShortDirectionRequest } from "@/lib/producer/short-direction";
import { resolveLanes, validateIntent } from "@/lib/producer/intent-presets";
import { assertNativeWebCapture } from "./native-web-capture";
import { assertNativeShortPacing, nativeShortPacingReport } from "./native-short-pacing";
import { assertNativeShortAssetUse, nativeShortAssetUseReport, type NativeAssetUseOptions } from "./native-short-asset-use";
import { assertNativeShortStory, nativeShortStoryReport } from "./native-short-story";
import { assertNativeShortAudio, type NativeShortAudio } from "./native-short-audio";
import { assertGuidedNativeBinding, assertGuidedNativeLocation, type GuidedNativeProjectBinding, type NativeGuidedDependencies } from "./guided-native-binding";

export interface NativeSceneExtension { markup: string; css: string; motion: string }
export interface NativeShortProjectInput {
  schemaVersion: 1; request: ShortDirectionRequest; strategy: NativeShortStrategy;
  canvas: NativeCanvasInput; assets: NativeAssetBinding[];
  requestPacket?: { path: string; sha256: string };
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
  const caption = input.canvas.captionMode === "source-burned" ? "<!--native-source-caption-mount-->" : '<div id="caption-0-0"';
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
  assertNativeShortAssetUse(input, html, assetUseOptions(input));
  assertNativeShortStory(input, html);
  return html;
}

/** Prepared supplied-file identity cannot be broadened by an origin label in the plan. */
function assetUseOptions(input: NativeShortProjectInput): NativeAssetUseOptions {
  const options: NativeAssetUseOptions = { required: input.strategy.schemaVersion === 3,
    expectedPolicy: shortMediaPolicy(input.request) };
  if (input.strategy.assetUse && input.strategy.schemaVersion !== 3) throw new Error("Asset-use plans require native strategy version 3");
  if (!input.requestPacket) return options;
  const ref = input.requestPacket;
  if (!path.isAbsolute(ref.path) || realpathSync(ref.path) !== ref.path || fileSha256(ref.path) !== ref.sha256) {
    throw new Error("Native request packet changed before asset-use validation");
  }
  const packet = JSON.parse(readFileSync(ref.path, "utf8"));
  const supplied = [...packet.sources, ...(packet.availableSupportingAssets ?? [])];
  options.providedAssets = input.assets.filter(asset => supplied.some(row => row.path === asset.path
    && row.sha256 === asset.sha256)).map(({ file, sha256 }) => ({ file, sha256 }));
  return options;
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

/** Same authoritative request, audio and lane checks for prepared and guided entry points. */
export function assertNativeShortIntent(input: NativeShortProjectInput, authority: unknown): void {
  const intent = validateIntent(authority), lanes = resolveLanes(intent.scope, intent.lanes);
  if (intent.music) throw new Error("Native dialogue export cannot silently omit requested music");
  if (intent.audioEnhance?.preset !== input.audioFinishing?.audioEnhance?.preset) {
    throw new Error("Native audio enhancement must match the prepared request; requested cleanup cannot be omitted or substituted");
  }
  const generated = { captions: input.canvas.captionGroups.length > 0,
    graphics: input.canvas.text.length + input.canvas.shapes.length > 0 || !!input.extension?.markup,
    motion: input.canvas.motion.length > 0 || !!input.extension?.motion,
    broll: input.strategy.supportingSearch.candidates.some(row => row.selected)
      || !!input.strategy.assetUse?.decisions.some(row => row.decision === "insert") };
  for (const [lane, used] of Object.entries(generated)) {
    if (used && lanes[lane as keyof typeof generated] !== "auto") throw new Error(`Native project cannot override ${lane} lane ownership`);
  }
  if (intent.mode !== "short" || canonicalJsonSha256(intent.shortDirection ?? AUTOMATIC_SHORT_DIRECTION)
      !== canonicalJsonSha256(input.request)) throw new Error("Native plan changed the prepared style request or media policy");
}

function verifyRequest(input: NativeShortProjectInput): void {
  if (!input.requestPacket) return;
  const ref = input.requestPacket;
  if (!path.isAbsolute(ref.path) || realpathSync(ref.path) !== ref.path || fileSha256(ref.path) !== ref.sha256) {
    throw new Error("Native request packet changed before strategy execution");
  }
  const packet = JSON.parse(readFileSync(ref.path, "utf8"));
  assertNativeShortIntent(input, packet.intent);
  if (packet.schemaVersion !== 1 || canonicalJsonSha256(packet.intent.shortDirection) !== canonicalJsonSha256(input.request)) {
    throw new Error("Native plan changed the prepared style request");
  }
  for (const asset of input.assets.filter((row) => row.role === "source")) {
    if (!packet.sources.some((row: { sha256: string; path: string }) => row.sha256 === asset.sha256 && row.path === asset.path)) {
      throw new Error("Native plan substituted the prepared source inventory");
    }
  }
  for (const source of packet.sources) {
    if (source.transcript && fileSha256(source.transcript.path) !== source.transcript.sha256) throw new Error("Prepared transcript changed");
  }
  for (const asset of packet.availableSupportingAssets ?? []) {
    if (asset.sha256 && fileSha256(asset.path) !== asset.sha256) throw new Error("Prepared supplied B-roll changed");
  }
}

function verifyTitle(input: NativeShortProjectInput, catalog: DirectorCatalog): void {
  const title = input.canvas.titleCard;
  if (!title) throw new Error("Native Short needs its selected canonical backed title before assembly");
  const actual = fillLocalHookTemplate(catalog, title.copy);
  if (canonicalJsonSha256(actual) !== canonicalJsonSha256(title.copy)) throw new Error("Native title differs from the canonical selected template or library");
}

function projectFiles(input: NativeShortProjectInput, html: string, catalog: DirectorCatalog): Record<string, string> {
  return {
    "index.html": html,
    "hyperframes.json": canonicalJson({ paths: { blocks: "compositions", components: "compositions/components", assets: "assets" } }),
    "SHORT-PROJECT.json": canonicalJson(input),
    ...(input.guidedBinding ? { "GUIDED-PROPOSAL.json": canonicalJson(input.guidedBinding) } : {}),
    "DIRECTOR-LIBRARY.json": canonicalJson(catalog),
    ...(input.strategy.schemaVersion >= 2 ? { "PACING-REPORT.json": canonicalJson(nativeShortPacingReport(input, html)) } : {}),
    ...(input.strategy.schemaVersion === 3 ? { "ASSET-USE-REPORT.json": canonicalJson(nativeShortAssetUseReport(input, html, assetUseOptions(input))) } : {}),
    ...(input.strategy.story ? { "STORY-REPORT.json": canonicalJson(nativeShortStoryReport(input, html)) } : {}),
    "BRIEF.md": `# ${input.canvas.title}\n\n${shortDirectionInstructions(input.request)}\n\n`
      + `Selected treatment: ${input.strategy.selectedTreatment}\n\n${input.strategy.selectionReason}\n\n`
      + `Viewer benefit: ${input.strategy.viewerBenefit}\n\nReason to watch: ${input.strategy.hookReasonToWatch}\n\n`
      + `Hook: ${input.canvas.titleCard!.copy.text}\n\nPayoff: ${input.strategy.payoff}\n`,
    "STORYBOARD.md": input.strategy.scenes.map((scene) => `## Frames ${scene.startFrame}–${scene.endFrame}\n\n`
      + `${scene.viewingNeed}\n\n${scene.before} → ${scene.action} → ${scene.result}\n\n`
      + `View: ${scene.paneJobs}\n\nHold: ${scene.holdFrames} frames. Exit: ${scene.exitReason}\n\n`
      + `References: ${scene.referenceIds.join(", ")}\n`).join("\n"),
  };
}

/** New isolated project only; asset copies cannot mutate the original recording. */
export function writeNativeShortProject(input: NativeShortProjectInput, destination: string, dependencies: NativeGuidedDependencies = {}) {
  if (input.strategy.schemaVersion !== 3) throw new Error("New native builds require strategy version 3 with pacing and asset-use decisions; legacy projects remain readable");
  const started = performance.now(), directory = path.resolve(destination), catalog = loadDirectorCatalog();
  if (realpathSync(path.dirname(directory)) !== path.dirname(directory)) throw new Error("Native project parent must be canonical");
  verifyAssets(input); verifyRequest(input); verifyTitle(input, catalog);
  assertGuidedNativeLocation(input, { directory }, dependencies);
  assertGuidedNativeBinding(input, dependencies);
  const files = projectFiles(input, assembleNativeShortHtml(input), catalog);
  mkdirSync(directory, { mode: 0o700 });
  for (const name of ["assets", "references", "compositions"]) mkdirSync(path.join(directory, name), { mode: 0o700 });
  for (const asset of input.assets) {
    copyFileSync(asset.path, path.join(directory, asset.file), constants.COPYFILE_EXCL | constants.COPYFILE_FICLONE);
    if (fileSha256(path.join(directory, asset.file)) !== asset.sha256) throw new Error("Native asset changed while staging");
  }
  for (const [name, content] of Object.entries(files)) writeFileSync(path.join(directory, name), content, { flag: "wx", mode: 0o600 });
  verifyAssets(input); verifyRequest(input);
  assertGuidedNativeLocation(input, { directory }, dependencies);
  assertGuidedNativeBinding(input, dependencies);
  const manifest = { schemaVersion: 1, scope: "native-short-review-project", projectHash: canonicalJsonSha256(input),
    files: [...Object.keys(files), ...input.assets.map((asset) => asset.file)].map((file) => ({ file, sha256: fileSha256(path.join(directory, file)) })),
    elapsedMs: performance.now() - started, sourceVerified: true, structuralStrategyChecks: "passed",
    reviewMethod: input.strategy.review.method, pixelChecks: "not-run", audioChecks: "not-run", humanApproved: false };
  writeFileSync(path.join(directory, "PROJECT-MANIFEST.json"), canonicalJson(manifest), { flag: "wx", mode: 0o600 });
  return { directory, manifest };
}

/** Reopen the exact executable project; edited/stale projects need a new build. */
export function readNativeShortProject(directory: string, dependencies: NativeGuidedDependencies = {}): NativeShortProjectInput {
  const manifest = JSON.parse(readFileSync(path.join(directory, "PROJECT-MANIFEST.json"), "utf8"));
  const input: NativeShortProjectInput = JSON.parse(readFileSync(path.join(directory, "SHORT-PROJECT.json"), "utf8"));
  const expected = ["index.html", "hyperframes.json", "SHORT-PROJECT.json", "DIRECTOR-LIBRARY.json", "BRIEF.md", "STORYBOARD.md",
    ...(input.strategy.schemaVersion >= 2 ? ["PACING-REPORT.json"] : []),
    ...(input.strategy.schemaVersion === 3 ? ["ASSET-USE-REPORT.json"] : []),
    ...(input.strategy.story ? ["STORY-REPORT.json"] : []),
    ...(input.guidedBinding ? ["GUIDED-PROPOSAL.json"] : []),
    ...input.assets.map((asset) => asset.file)].sort();
  if (manifest.schemaVersion !== 1 || manifest.scope !== "native-short-review-project" || !Array.isArray(manifest.files)
      || canonicalJsonSha256(manifest.files.map((row: { file: string }) => row.file).sort()) !== canonicalJsonSha256(expected)) {
    throw new Error("Native project manifest omits or duplicates required files");
  }
  for (const file of manifest.files) {
    if (!/^(?:[A-Z-]+\.json|index\.html|hyperframes\.json|BRIEF\.md|STORYBOARD\.md|(?:assets|references)\/[\w.-]+)$/u.test(file.file)
        || fileSha256(path.join(directory, file.file)) !== file.sha256) throw new Error("Native project changed since assembly");
  }
  if (canonicalJsonSha256(input) !== manifest.projectHash) throw new Error("Native project request/strategy changed");
  verifyAssets(input); verifyRequest(input);
  assertGuidedNativeLocation(input, { directory, legacyV9Read: true }, dependencies);
  assertGuidedNativeBinding(input, dependencies);
  if (input.guidedBinding && readFileSync(path.join(directory, "GUIDED-PROPOSAL.json"), "utf8") !== canonicalJson(input.guidedBinding)) {
    throw new Error("Guided proposal sidecar differs from its persistent native project binding");
  }
  for (const asset of input.assets) {
    if (fileSha256(path.join(directory, asset.file)) !== asset.sha256) throw new Error("Staged native asset changed");
  }
  const html = assembleNativeShortHtml(input);
  if (readFileSync(path.join(directory, "index.html"), "utf8") !== html) throw new Error("Native executable differs from its strategy/canvas");
  if (input.strategy.schemaVersion >= 2 && readFileSync(path.join(directory, "PACING-REPORT.json"), "utf8")
      !== canonicalJson(nativeShortPacingReport(input, html))) throw new Error("Native pacing report differs from its actual source and plan");
  if (input.strategy.schemaVersion === 3 && readFileSync(path.join(directory, "ASSET-USE-REPORT.json"), "utf8")
      !== canonicalJson(nativeShortAssetUseReport(input, html, assetUseOptions(input)))) throw new Error("Native asset-use report differs from its source and decisions");
  if (input.strategy.story && readFileSync(path.join(directory, "STORY-REPORT.json"), "utf8")
      !== canonicalJson(nativeShortStoryReport(input, html))) throw new Error("Native story report differs from its authored obligations");
  return input;
}
