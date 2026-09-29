/**
 * TEST native route canary fixture: a real IMG_5954 HEVC HLG extract with explicitly
 * synthetic TEST editorial records. Technical route coverage only; never production,
 * editorial, listening, playback or delivery authority.
 *
 *   stage <new-root> <extract fixture-result.json>   copy the extract, references and runtime
 *   author <root> <variant>                            write plans/<variant>.json and its summary
 *
 * The Python driver (native_route_canary_fixture.py) runs both, then the supported
 * native-short.ts build/check/check-export and native_preflight.py commands.
 */
import { constants, copyFileSync, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { canonicalJson, fileSha256 } from "../../../src/lib/server/auto-edit-hash";
import { loadDirectorCatalog } from "../../../src/lib/server/native-director-library";
import { fillLocalHookTemplate } from "../../../src/lib/server/native-hook-template";
import { writeNativeAssetOrigin } from "../../../src/lib/server/native-short-asset-origin";
import { nativeShortPrebuildPlanHash } from "../../../src/lib/server/native-short-prebuild-review";
import type { ProposalWordOccurrence } from "../../../src/lib/server/guided-proposal-speech";
import type { NativeCanvasInput } from "../../../src/lib/server/native-short-composition";
import type { NativeShortProjectInput } from "../../../src/lib/server/native-short-project";
import type { NativeAssetBinding, NativeShortStrategy } from "../../../src/lib/server/native-short-strategy";
import type { ShortDirectionRequest } from "../../../src/lib/producer/short-direction";
import { refreshNativePacingFixture } from "../../../src/lib/server/__tests__/_native-short-project-fixture";

type Variant = "good" | "graphic-edit" | "bad-audio" | "missing-dependency";
const VARIANTS: Variant[] = ["good", "graphic-edit", "bad-audio", "missing-dependency"];
const REQUEST: ShortDirectionRequest = { selection: "auto", supportingVideo: "source-first",
  mediaPolicy: { placement: "auto", sources: "local-only" } };
const FRAMES = 150, PICTURE_END = 105, TITLE_END = 60, CUT_SECONDS = 5, FIRST_SOURCE_WORD = 623;
/** IMG_5954 clip C (native-plan-v6 canvas): complete caption groups inside output frames [0,150). */
const WORDS: Array<[number, number, string]> = [[0, 3, "I'm"], [2, 8, "sure"], [7, 10, "a"], [9, 15, "lot"],
  [14, 17, "of"], [16, 22, "you"], [21, 36, "watching"], [40, 49, "are"], [48, 56, "probably"],
  [55, 68, "overthinking"], [67, 75, "the"], [74, 85, "process."], [84, 92, "Yo."], [91, 97, "I"],
  [96, 99, "don't"], [98, 104, "know"], [103, 109, "what"], [108, 113, "to"], [112, 125, "edit."],
  [124, 130, "I"], [129, 135, "don't"], [134, 142, "even"]];
const GROUPS = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11], [12], [13, 14, 15], [16, 17, 18], [19, 20, 21]];
/** Only the title geometry differs in the graphics-only revision. */
const TITLES: Record<Variant, { top: number; fontSize: number }> = { good: { top: 96, fontSize: 64 },
  "graphic-edit": { top: 132, fontSize: 72 }, "bad-audio": { top: 96, fontSize: 64 },
  "missing-dependency": { top: 96, fontSize: 64 } };
const PACKETS: Record<Variant, string> = { good: "voice-rnn", "graphic-edit": "voice-rnn",
  "bad-audio": "no-cleanup", "missing-dependency": "voice-rnn-html-reference" };
const DESIGN = {
  route: "native Short; TEST request scope light (captions and motion automatic, graphics lane off); built-in "
    + "canvas.titleCard; no catalogFiles/catalogTitle; no VISUAL-PLAN binding",
  frameRate: "30/1", totalFrames: FRAMES, pictureView: { startFrame: 0, endFrameExclusive: PICTURE_END },
  titleCard: { startFrame: 0, endFrameExclusive: TITLE_END },
  graphicsOnlySpan: { startFrame: PICTURE_END, endFrameExclusive: FRAMES,
    content: "background and native captions only; no source picture view (captions end at frame 142)" },
  words: "IMG_5954 clip C occurrences 0-21 in complete caption groups (frames 0-142), production cut start 166.495 s",
  limitations: ["Catalog titles, catalog mounts and visual-plan application are not exercised by this fixture.",
    "Reference JPEGs are untone-mapped technical frames of 10-bit HLG video.",
    "The retained speech stops mid-sentence; frames 142-150 carry speech without captions.",
    "No preview, export, render or media QC is run by the fixture commands."],
};
const MISSING_DEPENDENCY_HTML = `<!doctype html>
<!-- TEST route-canary reference only: packaged reference HTML whose local dependency was never staged.
It exists so static preflight can block an unresolved local dependency; it is not a design or approval. -->
<html lang="en"><head><meta charset="utf-8"><title>TEST missing dependency reference</title></head>
<body><img src="assets/TEST-missing-dependency.png" alt="TEST unstaged local dependency"></body></html>
`;

interface Staged {
  source: NativeAssetBinding; runtime: NativeAssetBinding[]; references: NativeAssetBinding[];
  htmlReference: NativeAssetBinding; cutStart: number; extract: string; design: typeof DESIGN;
}
interface ExtractResult {
  source: { path: string }; keyframe: { seconds: string }; cutStart: { extractSeconds: string };
  extract: { path: string; sha256: string; presentableFrames: number }; references: Array<{ path: string }>;
}

function readJson<T>(file: string): T {
  return JSON.parse(readFileSync(file, "utf8")) as T;
}

/** Copy real bytes into the fixture; never a link to the original file. */
function copyInto(directory: string, source: string, name: string): { path: string; sha256: string } {
  const target = path.join(directory, name);
  copyFileSync(source, target, constants.COPYFILE_EXCL);
  const sha256 = fileSha256(target)!;
  if (sha256 !== fileSha256(source)) throw new Error(`TEST fixture copy changed ${name}`);
  return { path: target, sha256 };
}

/** Bind the extract's TEST origin to the supervised worker result that produced it. */
function sourceAsset(inputs: string, resultFile: string, result: ExtractResult): NativeAssetBinding {
  const media = copyInto(inputs, result.extract.path, "IMG_5954-TEST-extract.mp4");
  if (media.sha256 !== result.extract.sha256) throw new Error("TEST extract differs from its worker result");
  const asset: NativeAssetBinding = { file: `assets/${media.sha256}.mp4`, ...media, role: "source" };
  return writeNativeAssetOrigin({ asset,
    record: { schemaVersion: 1, assetId: `test-canary-${media.sha256.slice(0, 12)}`, sha256: media.sha256,
      sizeBytes: statSync(media.path).size, mime: "video/mp4", origin: "operator-upload",
      acquiredAt: new Date().toISOString(),
      rights: { license: "TEST technical extract of the operator-supplied IMG_5954 recording for a local route canary only",
        allowedUses: ["editorial"], allowedPlatforms: ["local-review"], consent: "unknown", attributionRequired: false },
      media: { width: 1920, height: 1080, durationFrames: result.extract.presentableFrames, sampleRate: 48000, channels: 2 },
      provenance: { source: `${result.source.path}#TEST-extract-from-keyframe=${result.keyframe.seconds}` },
      publicationDisposition: "needs-review" },
    acquisition: { kind: "provided", accessScope: "operator-private", sourceFrameRate: "30/1",
      evidence: [{ path: resultFile, sha256: fileSha256(resultFile)! }] },
  }, path.join(inputs, "TEST-source-origin.json"));
}

function stage(root: string, resultFile: string): Staged {
  const inputs = path.join(root, "inputs"), repo = process.cwd(), result = readJson<ExtractResult>(resultFile);
  mkdirSync(inputs, { mode: 0o700 });
  const runtime = [["templates/motion/vendor/gsap/gsap.min.js", "gsap.min.js"], ["assets/fonts/Inter-Bold.ttf", "Inter-Bold.ttf"]]
    .map(([from, name]): NativeAssetBinding => ({ file: `assets/${name}`, ...copyInto(inputs, path.join(repo, from), name),
      role: "runtime" }));
  const references = result.references.map((row): NativeAssetBinding => ({ file: `references/${path.basename(row.path)}`,
    ...copyInto(inputs, row.path, path.basename(row.path)), role: "reference" }));
  const html = path.join(inputs, "TEST-reference.html");
  writeFileSync(html, MISSING_DEPENDENCY_HTML, { flag: "wx", mode: 0o600 });
  const staged: Staged = { source: sourceAsset(inputs, resultFile, result), runtime, references, extract: resultFile,
    htmlReference: { file: "references/TEST-reference.html", path: html, sha256: fileSha256(html)!, role: "reference" },
    cutStart: Number(result.cutStart.extractSeconds), design: DESIGN };
  writeFileSync(path.join(inputs, "STAGED.json"), JSON.stringify(staged, null, 2) + "\n", { flag: "wx", mode: 0o600 });
  return staged;
}

/** TEST light-scope request: captions/motion automatic, graphics lane off, audio cleanup per variant. */
function requestPacket(root: string, variant: Variant, source: NativeAssetBinding, references: NativeAssetBinding[]) {
  const file = path.join(root, "inputs", `TEST-REQUEST-light-${PACKETS[variant]}.json`);
  const pins = references.map(row => ({ path: row.path, sha256: row.sha256 }));
  const text = canonicalJson({ schemaVersion: 1,
    fixtureScope: "TEST synthetic request packet; not an operator request, review or approval",
    intent: { mode: "short", scope: "light", lanes: {}, shortDirection: REQUEST,
      ...(variant === "bad-audio" ? {} : { audioEnhance: { preset: "voice-rnn" } }) },
    sources: [{ path: source.path, sha256: source.sha256, transcript: null }],
    availableSupportingAssets: pins, selectedReferences: pins, relatedStyleContext: null });
  if (!existsSync(file)) writeFileSync(file, text, { flag: "wx", mode: 0o600 });
  if (readFileSync(file, "utf8") !== text) throw new Error("TEST request packet differs from its variant contract");
  return { path: file, sha256: fileSha256(file)! };
}

function canvas(staged: Staged, variant: Variant): NativeCanvasInput {
  const copy = fillLocalHookTemplate(loadDirectorCatalog(), { anchor: "mistake-you-might-be",
    slots: { mistake: "overthinking your next thumbnail" } });
  return { title: "TEST native route canary fixture", frameRate: "30/1", totalFrames: FRAMES, background: "#0B0E12",
    sourceSize: { w: 1920, h: 1080 }, sourceFile: staged.source.file,
    cuts: [{ start: staged.cutStart, end: staged.cutStart + CUT_SECONDS, speed: 1 }],
    segments: [{ startFrame: 0, endFrameExclusive: FRAMES }],
    occurrences: WORDS.map(([start, end, text], index): ProposalWordOccurrence =>
      [index, 0, FIRST_SOURCE_WORD + index, start, end, text, 0]),
    captionGroups: GROUPS, captionMode: "native",
    pictureViews: [{ startFrame: 0, endFrame: PICTURE_END, crop: [70, 0, 720, 1080], box: [0, 0, 1080, 1620] }],
    captionViews: [{ startFrame: 0, endFrame: FRAMES, box: [120, 1660, 840, 160], activeColor: "#FFB020",
      strokeColor: "#0B0E12", style: { size: 60, weight: 700, color: "#FFFFFF", background: "#0B0E12",
        align: "center", padding: 16, radius: 0, lineHeight: 1.15 } }],
    text: [], shapes: [], motion: [],
    titleCard: { copy, lines: ["You might be", "overthinking your", "next thumbnail"], palette: "paper-on-ink",
      endFrame: TITLE_END, ...TITLES[variant] } };
}

function spoken(start: number, end: number): number[] {
  return WORDS.flatMap(([first, last], index) => first < end && last > start ? [index] : []);
}

function referenceId(row: NativeAssetBinding): string {
  return `TEST-${path.basename(row.file).replace(/^TEST-/u, "").replace(/\.[a-z]+$/u, "")}`;
}

function strategy(staged: Staged, references: NativeAssetBinding[]): NativeShortStrategy {
  return { schemaVersion: 3, request: REQUEST,
    selectedTreatment: "TEST technical route canary: presenter crop, built-in title, native captions and a graphics-only span",
    selectionReason: "TEST fixture exercises native route boundaries; it is not an editorial selection",
    rejectedTreatment: "TEST catalog-mounted titles and a visual plan are outside this catalog-free light-scope canary",
    viewerBenefit: "TEST none claimed; technical route coverage only",
    hookReasonToWatch: "TEST none claimed; the title is a canonical template fill only",
    payoff: "TEST none claimed; the retained words stop mid-sentence by design",
    references: references.map(row => ({ assetFile: row.file, referenceId: referenceId(row),
      observed: "TEST technical reference file; no visual inspection or review occurred",
      adaptation: "TEST binding only; no design is derived from this file" })),
    supportingSearch: { searchedSourceFiles: [staged.source.file], candidates: [],
      conclusion: "TEST no supporting-footage search was performed for this technical fixture" },
    scenes: [{ startFrame: 0, endFrame: PICTURE_END, format: "presenter",
      viewingNeed: "TEST presenter picture view with the opening title and native captions",
      paneJobs: "TEST clip C portrait crop above the native caption band; built-in title for frames 0-60",
      before: "TEST fixture opening state", action: "TEST retained source dialogue continues",
      result: "TEST source picture view ends at frame 105", holdFrames: 30,
      visibleIds: ["source-0-0", "native-title-card"], occurrenceIds: spoken(0, PICTURE_END),
      referenceIds: [referenceId(references[0])], exitReason: "TEST technical boundary into the graphics-only span" },
    { startFrame: PICTURE_END, endFrame: FRAMES, format: "diagram",
      viewingNeed: "TEST graphics-only span with no source picture view",
      paneJobs: "TEST background and native captions only; the source picture view is intentionally absent",
      before: "TEST source picture view has ended", action: "TEST dialogue continues over background and captions",
      result: "TEST fixture ends at frame 150", holdFrames: 30, visibleIds: ["caption-6-0", "caption-7-0"],
      occurrenceIds: spoken(PICTURE_END, FRAMES), referenceIds: [referenceId(references[1])],
      exitReason: "TEST end of the technical fixture" }],
    review: { method: "local-editorial",
      findings: ["TEST synthetic fixture record; no creative review, playback or listening occurred"] } };
}

/** Graphics/audio/dependency variants reuse the good build's sealed selected-media package. */
function goodPreparedSources(root: string): { path: string; sha256: string } {
  const binding = readJson<NativeShortProjectInput>(path.join(root, "projects/good/SHORT-PROJECT.json")).preparedSources;
  if (!binding || fileSha256(binding.path) !== binding.sha256) throw new Error("Build the good variant before its revisions");
  return { path: binding.path, sha256: binding.sha256 };
}

function author(root: string, variant: Variant) {
  const staged = readJson<Staged>(path.join(root, "inputs/STAGED.json"));
  const references = variant === "missing-dependency" ? [...staged.references, staged.htmlReference] : staged.references;
  const input: NativeShortProjectInput = { schemaVersion: 1, request: REQUEST,
    requestPacket: requestPacket(root, variant, staged.source, references),
    assets: [staged.source, ...staged.runtime, ...references], canvas: canvas(staged, variant),
    strategy: strategy(staged, references) };
  if (variant !== "bad-audio") {
    input.audioFinishing = { schemaVersion: 1, audioEnhance: { preset: "voice-rnn" }, rationale: "TEST fixture decision "
      + "mirroring clip C's recorded voice-rnn cleanup of IMG_5954 low-frequency room tone; no listening, comparison or "
      + "approval occurred" };
  }
  // Rebind the TEST visual-source, asset-use, pacing and prebuild-review records to this exact plan.
  refreshNativePacingFixture(input);
  if (variant !== "good") input.preparedSources = goodPreparedSources(root);
  const plan = path.join(root, "plans", `${variant}.json`);
  writeFileSync(plan, JSON.stringify(input, null, 2) + "\n", { flag: "wx", mode: 0o600 });
  const summary = { scope: "TEST-native-route-canary-plan", variant, plan, planHash: nativeShortPrebuildPlanHash(input),
    requestPacket: input.requestPacket, prebuildReview: input.prebuildReview,
    preparedSourcesReused: input.preparedSources ?? null, totalFrames: FRAMES, frameRate: "30/1",
    graphicsOnlySpan: DESIGN.graphicsOnlySpan, titleCard: { endFrame: TITLE_END, ...TITLES[variant] },
    audioFinishing: input.audioFinishing !== undefined,
    extraUnmountedReference: variant === "missing-dependency" ? staged.htmlReference.file : null,
    syntheticEditorialRecords: true, productionAuthority: false, humanApproved: false };
  writeFileSync(path.join(root, "plans", `${variant}.summary.json`), JSON.stringify(summary, null, 2) + "\n",
    { flag: "wx", mode: 0o600 });
  return summary;
}

const [operation, root, argument] = process.argv.slice(2);
if (operation === "stage" && root && argument) {
  console.log(JSON.stringify({ status: "staged", ...stage(path.resolve(root), path.resolve(argument)) }));
} else if (operation === "author" && root && VARIANTS.includes(argument as Variant)) {
  console.log(JSON.stringify({ status: "authored", ...author(path.resolve(root), argument as Variant) }));
} else {
  throw new Error("Usage: native_route_canary_fixture.ts stage <new-root> <fixture-result.json> | author <root> <variant>");
}
