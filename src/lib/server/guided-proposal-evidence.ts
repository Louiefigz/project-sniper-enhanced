import { CATALOG_KINDS } from "@/lib/producer/visual-source-policy";
import path from "node:path";
import { packetCutSegments } from "@/app/api/producer/auto-edit/plan-review-packet-source";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { runCutPreviewProcess } from "@/app/api/producer/auto-edit/cut-preview-process";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { objectValue, exactKeys } from "@/lib/producer/contracts/validation";
import { proposalInteger } from "@/lib/producer/contracts/treatment-proposal-v2";
import { PROPOSAL_PRESENTATION_POLICY } from "@/lib/producer/contracts/treatment-proposal-v3";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { restoreAutoEditDoctrine, doctrinePromptPath } from "./auto-edit-doctrine";
import { stageTimingEnv } from "./stage-timing-context";
import type { AcceptedGuidedCut } from "./guided-raw-treatment-store";
import { readRawTreatmentClock } from "./guided-raw-treatment-store";
import type { AutoEditCtx, AutoEditPipelineAuthority } from "@/app/api/producer/auto-edit/stream";
import { readGuidedObject } from "./guided-cut-v2-store";
import { assertProposalAudioWindows, readProposalSourceSpeech, mapProposalOccurrences, type ProposalWordOccurrence } from "./guided-proposal-speech";
import { GUIDED_CAPTION_CONFIG_FILES, guidedCaptionPolicy } from "./guided-proposal-captions";
import { CURRENT_TREATMENT_PROPOSAL_VERSION } from "@/lib/producer/contracts/treatment-proposal-v5";
import { assertGuidedMusicIntent, guidedMusicPolicy, type GuidedMusicPolicy } from "./guided-proposal-music";
import { assertGuidedPresenterIntent, guidedPresenterPolicy, type GuidedPresenterPolicy } from "./guided-proposal-presenter";
import type { NativeReference } from "./guided-native-references";
import { assertDirectorSource, type NativeDirectorRecord } from "./native-director-store";
import { buildNativeSupportingPolicy, type NativeSupportingPolicy } from "./guided-native-supporting";

export interface ProposalSegment {
  index: number; sourceId: string; startFrame: number; endFrameExclusive: number; text: string;
}
export interface ProposalCatalogEntry { kind: string; canvas: number[]; defaults: Record<string, unknown>; fields: string[] }
/** One internal output cut boundary inside the long-form hook window; the renderer decides it by outTime. */
export interface ProposalIntroSeam { seamIndex: number; outTime: number; startFrame: number }
export interface ProposalEvidence {
  schemaVersion: 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10; cutDecisionHash: string; parentRevisionHash: string; timelineMapHash: string;
  frameRate: string; totalFrames: number; target: Record<string, unknown>; segments: ProposalSegment[];
  catalog: ProposalCatalogEntry[]; catalogHash: string; graphicsAdvice: Record<string, unknown>;
  doctrine: Array<{ name: string; sha256: string; content: string }>; pipelineHash: string;
  occurrences: ProposalWordOccurrence[]; anchors: number[]; cleanEnds: number[]; wordTupleFields: string[];
  wordTimingScope: "transcript-derived-floor-start-ceil-end-not-audibility-or-semantic-approval";
  scope: "full-program-proposal-evidence-not-render-or-quality-approval";
  presentationPolicy?: typeof PROPOSAL_PRESENTATION_POLICY;
  introSeams?: ProposalIntroSeam[]; hookWindowS?: number;
  captionPolicy?: ReturnType<typeof guidedCaptionPolicy>;
  musicPolicy?: GuidedMusicPolicy;
  presenterPolicy?: GuidedPresenterPolicy;
  nativeReferences?: NativeReference[];
  nativeDirector?: NativeDirectorRecord;
  nativeSupportingPolicy?: NativeSupportingPolicy;
}

function captionEvidence(cut: AcceptedGuidedCut) {
  return guidedCaptionPolicy(GUIDED_CAPTION_CONFIG_FILES.map((name) => ({ name, sha256: pinnedProposalFile(cut, name, true).sha256 })));
}

/** producer_config.HOOK_CONTRACT_WINDOW_S["longform"]; the seam gates read the same window. */
export const PROPOSAL_HOOK_WINDOW_S = 60;

/** Same internal boundaries intro_transition_contract.intro_seams derives, on the executed frame clock. */
export function proposalIntroSeams(segments: ProposalSegment[], frameRate: string): ProposalIntroSeam[] {
  const [numerator, denominator] = frameRate.split("/").map(Number);
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || numerator <= 0 || denominator <= 0) throw new Error("Proposal seam evidence needs an exact rational frame rate");
  const boundaries = segments.flatMap((part, index) => index === 0 ? [] : [{ startFrame: part.startFrame, outTime: part.startFrame * denominator / numerator }]);
  return boundaries.filter((row) => row.outTime > 0 && row.outTime < PROPOSAL_HOOK_WINDOW_S)
    .map((row, seamIndex) => ({ seamIndex, outTime: row.outTime, startFrame: row.startFrame }));
}

/** Current TS executor must match its captured source; old snapshots never borrow today's compiler. */
export function pinnedProposalFile(cut: AcceptedGuidedCut, relative: string, current = false) {
  if (!cut.job.ctx.pipeline) throw new Error("Treatment proposal requires pinned pipeline authority");
  return pinnedPipelineSourceFile(cut.job.ctx.pipeline, relative, { current });
}

/** Exact source bytes only; callers authenticate the original pipeline and retain their own lifetime. */
export function pinnedPipelineSourceFile(pipeline: Pick<AutoEditPipelineAuthority, "files" | "snapshotRoot">,
  relative: string, options: { current?: boolean; guard?: () => void } = {}) {
  const row = pipeline.files.find((item) => item.path === relative);
  if (!row) throw new Error(`Pinned pipeline predates required proposal module: ${relative}`);
  if (path.isAbsolute(relative) || relative.split("/").includes("..")) throw new Error("Proposal source path is invalid");
  const file = path.join(pipeline.snapshotRoot, ...relative.split("/"));
  const observed = observeCutPreviewFile(file, 2 * 1024 * 1024, true, options.guard);
  if (observed.sha256 !== row.hash || (options.current
      && observeCutPreviewFile(path.join(process.cwd(), relative), 2 * 1024 * 1024, false, options.guard).sha256 !== row.hash)) {
    throw new Error(`Proposal source differs from pinned implementation: ${relative}`);
  }
  return { file, ...observed };
}

function speechSegments(cut: AcceptedGuidedCut, staged: { ctx: AutoEditCtx; manifest: Record<string, unknown> }) {
  const ctx = cut.job.ctx, segments = packetCutSegments(cut.plan.value);
  const clock = readCutPreviewObject(path.join(ctx.dir, "cut-previews", cut.request.requestHash, cut.receipt.executionKey, "audio-clock.json"));
  if (clock.sha256 !== cut.receipt.audioClockHash || !Array.isArray(clock.value.parts) || clock.value.parts.length !== segments.length) throw new Error("Proposal cut frame partition changed");
  assertProposalAudioWindows(clock.value.parts);
  const speech = readProposalSourceSpeech(staged.ctx, staged.manifest, segments);
  let frames = 0;
  const output = segments.map((segment, index) => {
    const part = objectValue((clock.value.parts as unknown[])[index], "cut frame partition"), count = proposalInteger(part.videoFrames, "videoFrames");
    if (!count || part.index !== index || part.sourceId !== segment.sourceId || part.srcStart !== segment.sourceStart
        || part.srcEnd !== segment.sourceEnd || part.speed !== 1 || segment.speed !== 1) throw new Error("Proposal cut partition differs from actual speed-1 preview");
    const startFrame = frames; frames += count;
    return { index, sourceId: segment.sourceId, startFrame, endFrameExclusive: frames,
      text: "" };
  });
  if (frames !== cut.receipt.media.videoFrames) throw new Error("Proposal full-program frame partition is incomplete");
  const mapped = mapProposalOccurrences({ segments, partitions: output, frameRate: cut.receipt.profile.fps, totalFrames: frames }, speech);
  const text = new Map<number, string[]>();
  for (const word of mapped.occurrences) { const words = text.get(word[1]) ?? []; words.push(word[5]); text.set(word[1], words); }
  for (const part of output) part.text = (text.get(part.index) ?? []).join(" ");
  return { segments: output, ...mapped };
}

function canvas(target: Record<string, unknown>) {
  if (!["width", "height"].every((key) => Number.isSafeInteger(target[key]) && Number(target[key]) > 0 && Number(target[key]) <= 16384)) {
    throw new Error("Proposal requires an exact bounded destination canvas; mode-only or proxy dimensions are not authority");
  }
  return { width: Number(target.width), height: Number(target.height) };
}

/** Use the actual accepted destination object, never the source-aspect private-preview dimensions. */
export function proposalTargetProfile(cut: AcceptedGuidedCut) {
  const hash = cut.revision.canvasProfileHash, target = readGuidedObject(cut.job.ctx.dir, hash);
  if (cut.revision.destinationProfileHashes.length !== 1 || cut.revision.destinationProfileHashes[0] !== hash
      || cut.revision.authoritativeSidecars.declaredTargetProfile !== hash || canonicalJsonSha256(target) !== canonicalJsonSha256(cut.plan.value.target)) {
    throw new Error("Proposal destination profile differs from the exact accepted cut target");
  }
  canvas(target); return target;
}

function pinnedDoctrine(cut: AcceptedGuidedCut) {
  if (!cut.job.ctx.doctrine) throw new Error("Proposal requires pinned Producer doctrine");
  restoreAutoEditDoctrine(cut.job.ctx.doctrine);
  return [".claude/skills/producer/SKILL.md", "docs/PIPELINE.md"].map((name) => {
    if (!cut.job.ctx.doctrine?.files[name]) throw new Error("Required proposal doctrine is absent");
    const observed = observeCutPreviewFile(doctrinePromptPath(cut.job.ctx, name), 256 * 1024, true);
    return { name, sha256: observed.sha256, content: new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes) };
  });
}

/** Existing measured catalog authority is checked by its pinned Python validator, without rendering. */
async function catalogEvidence(cut: AcceptedGuidedCut) {
  const source = pinnedProposalFile(cut, "scripts/producer/graphics/comp_capability_artifact.py");
  const root = path.dirname(path.dirname(source.file));
  const code = "import json,sys; from graphics.comp_capability_artifact import load_artifact; value,error=load_artifact(sys.argv[1]); assert value is not None,error; print(json.dumps(value,sort_keys=True))";
  const matrix = pinnedProposalFile(cut, "templates/motion/comp_capabilities.json");
  const result = await runCutPreviewProcess({ command: pythonInterpreter(), args: ["-c", code, matrix.file], cwd: root,
    env: { ...stageTimingEnv(), PYTHONPATH: root, PYTHONDONTWRITEBYTECODE: "1" }, timeoutMs: 30_000 });
  const rows = objectValue(JSON.parse(result.stdout), "measured catalog"), target = proposalTargetProfile(cut);
  return { catalog: selectProposalCatalog(rows, target), catalogHash: matrix.sha256 };
}

/** Exact V6–V8 graphics-off previsual owns no generated catalog work or capability claim. */
export function omittedProposalCatalog(version: number, plan: Record<string, unknown>) {
  // V9 is an internal mechanism proof. Native catalog eligibility belongs to the primary
  // HyperFrames registry, never this legacy local catalog or these two development mechanisms.
  if (version === 9 || version === 10) return { catalog: [] as ProposalCatalogEntry[], catalogHash: canonicalJsonSha256({
    schemaVersion: 1, route: "native-short-v1", mechanisms: ["presenter-hold", "message-reveal", ...(version === 10 ? ["supporting-asset"] : [])],
    scope: "bounded-development-mechanisms-not-qualified-catalog" }) };
  if (version !== 6 && version !== 7 && version !== 8) return null;
  const target = objectValue(plan.target, "accepted catalog target"), lanes = target.lanes;
  if (!lanes || typeof lanes !== "object" || Array.isArray(lanes)
      || (lanes as Record<string, unknown>).graphics !== "off" || target.style === "restrained") return null;
  const fields = Object.keys(plan).sort();
  if (fields.join(",") !== "cutDecisions,cutTrack,planVersion,target") return null;
  return { catalog: [] as ProposalCatalogEntry[], catalogHash: canonicalJsonSha256({
    schemaVersion: 1, kind: "explicit-graphics-off-proposal-catalog-omission",
    scope: "no-generated-graphics-no-measured-catalog-authority", targetHash: canonicalJsonSha256(target),
  }) };
}

function storedCatalogEvidence(cut: AcceptedGuidedCut, version: number, target: Record<string, unknown>) {
  const omitted = omittedProposalCatalog(version, cut.plan.value);
  if (omitted) return omitted;
  const matrix = pinnedProposalFile(cut, "templates/motion/comp_capabilities.json");
  const catalog = objectValue(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(matrix.bytes)), "catalog artifact");
  return { catalog: selectProposalCatalog(objectValue(catalog.comps, "measured comps"), target), catalogHash: matrix.sha256 };
}

export function selectProposalCatalog(rows: Record<string, unknown>, target: Record<string, unknown>) {
  const destination = canvas(target), aspect = destination.width / destination.height;
  const catalog = Object.entries(rows).flatMap(([kind, value]) => {
    if (!CATALOG_KINDS.includes(kind)) return [];
    const row = objectValue(value, "catalog row");
    if (!Array.isArray(row.canvas) || row.canvas.length !== 2
        || row.canvas.some((value) => !Number.isSafeInteger(value) || Number(value) <= 0 || Number(value) > 16384)) throw new Error("Catalog has a malformed measured canvas");
    if (row.renderError || Math.abs(Number(row.canvas[0]) / Number(row.canvas[1]) - aspect) > 0.002) return [];
    if (!Array.isArray(row.specFields) || row.specFields.some((field) => typeof field !== "string")) return [];
    return [{ kind, canvas: row.canvas as number[], defaults: objectValue(row.specDefaults, "catalog defaults"), fields: row.specFields as string[] }];
  });
  if (!catalog.length) throw new Error("No measured catalog matches the accepted destination");
  return catalog;
}

/** Reproduce exact stored packet data without Python or snapshot restoration; no fresh visual-quality claim. */
export function assertStoredProposalEvidence(cut: AcceptedGuidedCut, evidence: ProposalEvidence,
  staged: { ctx: AutoEditCtx; manifest: Record<string, unknown>; graphicsAdvice: Record<string, unknown>; nativeReferences?: NativeReference[]; nativeDirector?: NativeDirectorRecord }) {
  const legacy = evidence.schemaVersion !== 9 && evidence.schemaVersion !== 10;
  if (legacy && evidence.schemaVersion >= 7) assertGuidedMusicIntent(cut.plan.value, cut.job.ctx.intent);
  if (evidence.schemaVersion === 8) assertGuidedPresenterIntent(cut.plan.value, cut.job.ctx.intent);
  const keys = ["schemaVersion", "cutDecisionHash", "parentRevisionHash", "timelineMapHash", "frameRate", "totalFrames", "target",
    "segments", "catalog", "catalogHash", "graphicsAdvice", "doctrine", "pipelineHash", "scope",
    "occurrences", "anchors", "cleanEnds", "wordTupleFields", "wordTimingScope"];
  if (legacy && evidence.schemaVersion >= 3) keys.push("presentationPolicy");
  if (legacy && evidence.schemaVersion >= 4) keys.push("introSeams", "hookWindowS");
  if (legacy && evidence.schemaVersion >= 5) keys.push("captionPolicy");
  if (legacy && evidence.schemaVersion >= 7) keys.push("musicPolicy");
  if (!legacy) keys.push("nativeReferences");
  if (evidence.schemaVersion === 10) keys.push("nativeSupportingPolicy");
  if (!legacy && staged.graphicsAdvice.nativeDirectorVersion === 1) keys.push("nativeDirector");
  if (evidence.schemaVersion === 8) keys.push("presenterPolicy");
  exactKeys(evidence as unknown as Record<string, unknown>, keys, keys, "proposal evidence");
  const doctrine = [".claude/skills/producer/SKILL.md", "docs/PIPELINE.md"].map((name) => {
    if (!cut.job.ctx.doctrine?.files[name]) throw new Error("Proposal doctrine is absent");
    const observed = observeCutPreviewFile(doctrinePromptPath(cut.job.ctx, name), 256 * 1024, true);
    return { name, sha256: observed.sha256, content: new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes) };
  });
  const target = proposalTargetProfile(cut);
  if (![2, 3, 4, 5, 6, 7, 8, 9, 10].includes(evidence.schemaVersion)) throw new Error("Unsupported proposal evidence version");
  const speech = speechSegments(cut, staged);
  const expected = { schemaVersion: evidence.schemaVersion, cutDecisionHash: cut.pointer.cutDecisionHash, parentRevisionHash: cut.pointer.pictureLockedRevisionHash,
    timelineMapHash: cut.request.timelineMapHash, frameRate: cut.receipt.profile.fps, totalFrames: cut.receipt.media.videoFrames,
    target, ...speech, ...storedCatalogEvidence(cut, evidence.schemaVersion, target),
    graphicsAdvice: staged.graphicsAdvice, doctrine, pipelineHash: canonicalJsonSha256(cut.job.ctx.pipeline),
    scope: "full-program-proposal-evidence-not-render-or-quality-approval",
    ...(!legacy ? { nativeReferences: staged.nativeReferences } : {}),
    ...(evidence.schemaVersion === 10 ? { nativeSupportingPolicy: supportingEvidence(cut, target) } : {}),
    ...(!legacy && staged.graphicsAdvice.nativeDirectorVersion === 1 ? { nativeDirector: staged.nativeDirector } : {}),
    ...(legacy && evidence.schemaVersion >= 3 ? { presentationPolicy: PROPOSAL_PRESENTATION_POLICY } : {}),
    ...(legacy && evidence.schemaVersion >= 4 ? { introSeams: proposalIntroSeams(speech.segments, cut.receipt.profile.fps), hookWindowS: PROPOSAL_HOOK_WINDOW_S } : {}),
    ...(legacy && evidence.schemaVersion >= 5 ? { captionPolicy: captionEvidence(cut) } : {}),
    ...(legacy && evidence.schemaVersion >= 7 ? { musicPolicy: guidedMusicPolicy(cut.plan.value, staged.manifest) } : {}),
    ...(evidence.schemaVersion === 8 ? { presenterPolicy: guidedPresenterPolicy(cut.plan.value, staged.manifest) } : {}) };
  if (canonicalJsonSha256(expected) !== canonicalJsonSha256(evidence)) throw new Error("Stored proposal evidence differs from accepted speech, catalog, target or doctrine");
  if (!legacy && staged.graphicsAdvice.nativeDirectorVersion === 1) {
    if (!staged.nativeDirector) throw new Error("Native source has no Director strategy");
    assertDirectorSource(staged.nativeDirector, readRawTreatmentClock(cut).submission.rawIntent, evidence);
  }
}

/** Exact full-program text/cut/catalog input, with no raw-media egress or file-writing brain tools. */
export async function buildProposalEvidence(cut: AcceptedGuidedCut,
  staged: { ctx: AutoEditCtx; manifest: Record<string, unknown>; graphicsAdvice: Record<string, unknown>; nativeReferences?: NativeReference[] },
  options: { version: 4 | 5 | 6 | 7 | 8 | 9 | 10 } = { version: CURRENT_TREATMENT_PROPOSAL_VERSION }): Promise<ProposalEvidence> {
  const legacy = options.version !== 9 && options.version !== 10;
  if (!legacy && !staged.nativeReferences?.length) throw new Error("Native proposal requires frozen reference images");
  if (legacy && options.version >= 7) assertGuidedMusicIntent(cut.plan.value, cut.job.ctx.intent);
  if (options.version === 8) assertGuidedPresenterIntent(cut.plan.value, cut.job.ctx.intent);
  if (!cut.job.ctx.pipeline) throw new Error("Proposal has no pinned pipeline");
  const speech = speechSegments(cut, staged);
  const measured = omittedProposalCatalog(options.version, cut.plan.value) ?? await catalogEvidence(cut);
  return { schemaVersion: options.version, cutDecisionHash: cut.pointer.cutDecisionHash, parentRevisionHash: cut.pointer.pictureLockedRevisionHash,
    timelineMapHash: cut.request.timelineMapHash, frameRate: cut.receipt.profile.fps, totalFrames: cut.receipt.media.videoFrames,
    target: proposalTargetProfile(cut), ...speech, ...measured, graphicsAdvice: staged.graphicsAdvice,
    doctrine: pinnedDoctrine(cut), pipelineHash: canonicalJsonSha256(cut.job.ctx.pipeline),
    scope: "full-program-proposal-evidence-not-render-or-quality-approval",
    ...(!legacy ? { nativeReferences: staged.nativeReferences } : { presentationPolicy: PROPOSAL_PRESENTATION_POLICY,
      introSeams: proposalIntroSeams(speech.segments, cut.receipt.profile.fps), hookWindowS: PROPOSAL_HOOK_WINDOW_S }),
    ...(options.version === 10 ? { nativeSupportingPolicy: supportingEvidence(cut, proposalTargetProfile(cut)) } : {}),
    ...(legacy && options.version >= 5 ? { captionPolicy: captionEvidence(cut) } : {}),
    ...(legacy && options.version >= 7 ? { musicPolicy: guidedMusicPolicy(cut.plan.value, staged.manifest) } : {}),
    ...(options.version === 8 ? { presenterPolicy: guidedPresenterPolicy(cut.plan.value, staged.manifest) } : {}) };
}

function supportingEvidence(cut: AcceptedGuidedCut, target: Record<string, unknown>): NativeSupportingPolicy {
  return buildNativeSupportingPolicy({ manifestPath: cut.job.ctx.manifestPath, manifest: cut.manifest.value,
    intent: cut.job.ctx.intent, target });
}
