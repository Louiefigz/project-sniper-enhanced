/**
 * TEST performance fixture shaped like audited clip E, on a real IMG_5954 HEVC HLG extract, with
 * explicitly synthetic TEST editorial records. Route-cost measurement only; never production,
 * editorial, listening, playback or delivery authority. Driven by native_perf_fixture.py:
 *
 *   stage <new-root> <extract fixture-result.json>   copy the extract, references and runtime assets
 *   author <root> <clip E native-plan.json>           write plans/dense.json and its summary
 */
import { constants, copyFileSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { canonicalJson, fileSha256 } from "../../../src/lib/server/auto-edit-hash";
import { loadDirectorCatalog } from "../../../src/lib/server/native-director-library";
import { fillLocalHookTemplate } from "../../../src/lib/server/native-hook-template";
import { writeNativeAssetOrigin } from "../../../src/lib/server/native-short-asset-origin";
import { nativeShortPrebuildPlanHash } from "../../../src/lib/server/native-short-prebuild-review";
import type { NativeCanvasInput } from "../../../src/lib/server/native-short-composition";
import type { NativeShortProjectInput } from "../../../src/lib/server/native-short-project";
import type { NativeAssetBinding, NativeShortStrategy } from "../../../src/lib/server/native-short-strategy";
import type { ShortDirectionRequest } from "../../../src/lib/producer/short-direction";
import { refreshNativePacingFixture } from "../../../src/lib/server/__tests__/_native-short-project-fixture";

const REQUEST: ShortDirectionRequest = { selection: "auto", supportingVideo: "source-first",
  mediaPolicy: { placement: "auto", sources: "local-only" } };
const TITLE_END = 60;

interface Staged {
  source: NativeAssetBinding; runtime: NativeAssetBinding[]; references: NativeAssetBinding[];
  extract: string; keyframeSeconds: string;
}
interface ExtractResult {
  source: { path: string }; keyframe: { seconds: string };
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
  const media = copyInto(inputs, result.extract.path, "IMG_5954-TEST-perf-extract.mp4");
  if (media.sha256 !== result.extract.sha256) throw new Error("TEST extract differs from its worker result");
  const asset: NativeAssetBinding = { file: `assets/${media.sha256}.mp4`, ...media, role: "source" };
  return writeNativeAssetOrigin({ asset,
    record: { schemaVersion: 1, assetId: `test-perf-${media.sha256.slice(0, 12)}`, sha256: media.sha256,
      sizeBytes: statSync(media.path).size, mime: "video/mp4", origin: "operator-upload",
      acquiredAt: new Date().toISOString(),
      rights: { license: "TEST technical extract of the operator-supplied IMG_5954 recording for local performance measurement only",
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
  const staged: Staged = { source: sourceAsset(inputs, resultFile, result), runtime, references, extract: resultFile,
    keyframeSeconds: result.keyframe.seconds };
  writeFileSync(path.join(inputs, "STAGED.json"), JSON.stringify(staged, null, 2) + "\n", { flag: "wx", mode: 0o600 });
  return staged;
}

function requestPacket(root: string, source: NativeAssetBinding, references: NativeAssetBinding[]) {
  const file = path.join(root, "inputs", "TEST-REQUEST-dense-voice-rnn.json");
  const pins = references.map(row => ({ path: row.path, sha256: row.sha256 }));
  writeFileSync(file, canonicalJson({ schemaVersion: 1,
    fixtureScope: "TEST synthetic request packet; not an operator request, review or approval",
    intent: { mode: "short", scope: "light", lanes: {}, shortDirection: REQUEST, audioEnhance: { preset: "voice-rnn" } },
    sources: [{ path: source.path, sha256: source.sha256, transcript: null }],
    availableSupportingAssets: pins, selectedReferences: pins, relatedStyleContext: null }), { flag: "wx", mode: 0o600 });
  return { path: file, sha256: fileSha256(file)! };
}

/** Clip E's retained clock, views, phrases and words, re-timed onto the extract's zero. */
function canvas(staged: Staged, shape: NativeCanvasInput): NativeCanvasInput {
  const origin = Number(staged.keyframeSeconds), shift = (value: number) => Math.round((value - origin) * 1e6) / 1e6;
  const copy = fillLocalHookTemplate(loadDirectorCatalog(), { anchor: "mistake-you-might-be",
    slots: { mistake: "overthinking your next thumbnail" } });
  return { title: "TEST dense native performance fixture", frameRate: shape.frameRate, totalFrames: shape.totalFrames,
    background: shape.background, sourceSize: shape.sourceSize, sourceFile: staged.source.file,
    cuts: shape.cuts.map(cut => ({ start: shift(cut.start), end: shift(cut.end), speed: 1 })),
    segments: shape.segments, occurrences: shape.occurrences, captionGroups: shape.captionGroups,
    captionCorrections: shape.captionCorrections, captionMode: "native", pictureViews: shape.pictureViews,
    captionViews: shape.captionViews, text: [], shapes: [], motion: [],
    titleCard: { copy, lines: ["You might be", "overthinking your", "next thumbnail"], palette: "paper-on-ink",
      endFrame: TITLE_END, top: 96, fontSize: 64 } };
}

function referenceId(row: NativeAssetBinding): string {
  return `TEST-${path.basename(row.file).replace(/^TEST-/u, "").replace(/\.[a-z]+$/u, "")}`;
}

function strategy(staged: Staged, value: NativeCanvasInput): NativeShortStrategy {
  const spoken = (start: number, end: number) => value.occurrences.flatMap(word => word[3] < end && word[4] > start ? [word[0]] : []);
  return { schemaVersion: 3, request: REQUEST,
    selectedTreatment: "TEST technical performance fixture: six presenter crops, built-in title and dense native captions",
    selectionReason: "TEST fixture reproduces clip E's measured capture workload; it is not an editorial selection",
    rejectedTreatment: "TEST catalog-mounted titles and a visual plan are outside this catalog-free fixture",
    viewerBenefit: "TEST none claimed; technical route measurement only",
    hookReasonToWatch: "TEST none claimed; the title is a canonical template fill only",
    payoff: "TEST none claimed; clip E's retained words are reused only for their timing density",
    references: staged.references.map(row => ({ assetFile: row.file, referenceId: referenceId(row),
      observed: "TEST technical reference file; no visual inspection or review occurred",
      adaptation: "TEST binding only; no design is derived from this file" })),
    supportingSearch: { searchedSourceFiles: [staged.source.file], candidates: [],
      conclusion: "TEST no supporting-footage search was performed for this technical fixture" },
    scenes: value.segments.map((segment, index) => ({ startFrame: segment.startFrame, endFrame: segment.endFrameExclusive,
      format: "presenter", viewingNeed: "TEST presenter view of the retained dialogue",
      paneJobs: "TEST portrait crop above the native caption band", before: "TEST previous retained cut",
      action: "TEST retained source dialogue continues", result: "TEST the cut ends at its retained boundary",
      holdFrames: Math.min(30, segment.endFrameExclusive - segment.startFrame),
      visibleIds: index === 0 ? [`source-${index}-${index}`, "native-title-card"] : [`source-${index}-${index}`],
      occurrenceIds: spoken(segment.startFrame, segment.endFrameExclusive),
      referenceIds: [referenceId(staged.references[index % staged.references.length])],
      exitReason: "TEST technical boundary at the next retained cut" })),
    review: { method: "local-editorial",
      findings: ["TEST synthetic fixture record; no creative review, playback or listening occurred"] } };
}

function author(root: string, shapeFile: string) {
  const staged = readJson<Staged>(path.join(root, "inputs/STAGED.json"));
  const shape = readJson<NativeShortProjectInput>(shapeFile).canvas, value = canvas(staged, shape);
  const input: NativeShortProjectInput = { schemaVersion: 1, request: REQUEST,
    requestPacket: requestPacket(root, staged.source, staged.references),
    assets: [staged.source, ...staged.runtime, ...staged.references], canvas: value, strategy: strategy(staged, value),
    audioFinishing: { schemaVersion: 1, audioEnhance: { preset: "voice-rnn" }, channelMode: "mono", rationale: "TEST fixture "
      + "decision mirroring clip E's recorded centered-mono voice-rnn finishing of the two-person IMG_5954 conversation "
      + "(its stereo channels are imbalanced by 14 dB in places); no listening, comparison or approval occurred" } };
  refreshNativePacingFixture(input);  // TEST visual-source, asset-use, pacing and prebuild-review records for this plan
  const plan = path.join(root, "plans", "dense.json");
  writeFileSync(plan, JSON.stringify(input, null, 2) + "\n", { flag: "wx", mode: 0o600 });
  const summary = { scope: "TEST-native-perf-plan", plan, planHash: nativeShortPrebuildPlanHash(input),
    requestPacket: input.requestPacket, prebuildReview: input.prebuildReview, totalFrames: value.totalFrames,
    frameRate: value.frameRate, pictureViews: value.pictureViews.length, captionWords: value.occurrences.length,
    captionPhrases: value.captionGroups.length, titleCard: { endFrame: TITLE_END },
    syntheticEditorialRecords: true, productionAuthority: false, humanApproved: false };
  writeFileSync(path.join(root, "plans", "dense.summary.json"), JSON.stringify(summary, null, 2) + "\n",
    { flag: "wx", mode: 0o600 });
  return summary;
}

const [operation, root, argument] = process.argv.slice(2);
if (operation === "stage" && root && argument) {
  console.log(JSON.stringify({ status: "staged", ...stage(path.resolve(root), path.resolve(argument)) }));
} else if (operation === "author" && root && argument) {
  console.log(JSON.stringify({ status: "authored", ...author(path.resolve(root), path.resolve(argument)) }));
} else {
  throw new Error("Usage: native_perf_fixture.ts stage <new-root> <fixture-result.json> | author <root> <clip E plan>");
}
