import path from "node:path";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import type { ColorGroup, ColorJob } from "@/lib/producer/color-diagnostic";
import { privateDir, readJson, type JobRequest, type JobTerminal } from "./files";
import { ColorError, object, UUID } from "./request";

const POLICY = "sniper-private-source-color-v1";
const strings = (value: unknown): string[] => Array.isArray(value) ? value.slice(0, 40).map(item => String(item).slice(0, 1000)) : [];
const number = (value: unknown): number | null => typeof value === "number" && Number.isFinite(value) ? value : null;
function atoms(value: unknown): Record<string, string | number | boolean | null> {
  const row = object(value), keys = ["range", "matrix", "transfer", "primaries", "pixelFormat", "bitsPerRawSample",
    "codec", "startTime", "frameRate", "width", "height", "duration", "supportedSamplingClass", "hdrSignaled", "logProfileInferred"];
  return Object.fromEntries(keys.map(key => [key, typeof row[key] === "string" ? row[key].slice(0, 200)
    : typeof row[key] === "boolean" ? row[key] : number(row[key])]));
}
function checkedArtifact(file: string): Record<string, unknown> {
  const { artifactHash, ...value } = readJson(file);
  if (artifactHash !== canonicalJsonSha256(value)) throw new ColorError("Diagnostic evidence integrity check failed", 409);
  return value;
}
function intervals(request: JobRequest, source: string) {
  const plan = object(JSON.parse(request.planText));
  let cursor = 0;
  return (plan.cutTrack as unknown[]).map(object).flatMap(row => {
    const start = number(row.start), end = number(row.end), speed = number(row.speed ?? 1);
    if (start === null || end === null || speed === null || speed <= 0) throw new ColorError("Diagnostic cut binding is invalid", 409);
    const output = cursor; cursor += (end - start) / speed;
    return row.sourceId === source ? [{ sourceStart: start, sourceEnd: end, outStart: output, outEnd: cursor }] : [];
  });
}
function groupProjection(value: unknown, request: JobRequest): ColorGroup {
  const row = object(value), context = request.request.contexts.find(item => item.sourceId === row.sourceId);
  if (!context || row.groupId !== "whole-source" || row.intent !== context.lightingGroups[0].intent
      || canonicalJsonSha256(row.context) !== canonicalJsonSha256(context)) throw new ColorError("Diagnostic lighting binding is invalid", 409);
  const expected = intervals(request, context.sourceId);
  const actual = (row.retainedIntervals as unknown[]).map(object);
  if (actual.length !== expected.length || actual.some((piece, index) => Object.entries(expected[index]).some(([key, n]) =>
    number(piece[key]) === null || Math.abs(Number(piece[key]) - n) > 0.000002))) throw new ColorError("Diagnostic retained intervals differ from the saved cut", 409);
  const samples = (row.samples as unknown[]).map(object), observations = (row.observations as unknown[]).map(object);
  if (samples.length < 5 || samples.length > 64 || observations.length !== samples.length
      || observations.some((item, i) => item.id !== samples[i].id || item.requestedTime !== samples[i].sourceTime)) {
    throw new ColorError("Diagnostic sample closure is invalid", 409);
  }
  assertSamples({ row, samples, observations, expected });
  const summary = object(row.summary);
  return { sourceId: context.sourceId, groupId: "whole-source", intent: context.lightingGroups[0].intent,
    context, metadata: atoms(row.metadata), retainedIntervals: expected,
    unsampledIntervalIndices: expected.map((_, i) => i).filter(i => !samples.some(sample => sample.intervalIndex === i)),
    observations: observations.map(item => ({ requestedTime: Number(item.requestedTime), actualSourceTime: number(item.actualSourceTime),
      status: String(item.status).slice(0, 30), error: typeof item.error === "string" ? item.error.slice(0, 200) : null,
      elapsedMs: number(item.elapsedMs) ?? 0, frameMetadata: frameAtoms(item.frameMetadata) })),
    sampledFrames: number(summary.sampledFrames) ?? 0, minimumMeanLuma: number(summary.minimumMeanLuma),
    maximumMeanLuma: number(summary.maximumMeanLuma), worstNominalBlackFraction: number(summary.worstNominalBlackFraction),
    worstNominalWhiteFraction: number(summary.worstNominalWhiteFraction), warnings: strings(row.warnings),
    screeningOffsets: screening(row.suggestions) };
}
function assertSamples(input: { row: Record<string, unknown>; samples: Record<string, unknown>[];
  observations: Record<string, unknown>[]; expected: ReturnType<typeof intervals> }): void {
  const { row, samples, observations, expected } = input;
  if (new Set(samples.map(item => item.id)).size !== samples.length) throw new ColorError("Duplicate color samples", 409);
  samples.forEach((sample, index) => {
    const piece = expected[Number(sample.intervalIndex)], observation = observations[index];
    if (!piece || sample.sourceId !== row.sourceId || sample.groupId !== row.groupId
        || typeof sample.sourceTime !== "number" || sample.sourceTime < piece.sourceStart || sample.sourceTime >= piece.sourceEnd
        || !["sampled", "failed", "skipped"].includes(String(observation.status))) throw new ColorError("Color sample interval binding is invalid", 409);
    if (observation.status === "sampled" && (typeof observation.actualSourceTime !== "number"
        || observation.actualSourceTime < piece.sourceStart || observation.actualSourceTime >= piece.sourceEnd
        || observation.actualSourceTime - sample.sourceTime < -0.000001
        || observation.actualSourceTime - sample.sourceTime > Number(sample.maximumSeekDeltaS))) throw new ColorError("Color sampled time is invalid", 409);
  });
  const unvisited = expected.map((_, i) => i).filter(i => !samples.some(sample => sample.intervalIndex === i));
  if (canonicalJsonSha256(unvisited) !== canonicalJsonSha256(row.unsampledIntervalIndices)) throw new ColorError("Color omitted interval evidence is inconsistent", 409);
  const context = object(row.context), metadata = object(row.metadata);
  if (screening(row.suggestions).length && (context.sourceProfile !== "bt709-sdr" || context.cameraProfile !== null
      || context.historyState !== "known" || (context.transformHistory as unknown[]).length || row.intent !== "neutral"
      || metadata.supportedSamplingClass !== "limited-8bit-bt709" || unvisited.length
      || observations.some(observation => observation.status !== "sampled"))) throw new ColorError("Unsupported context carried a numeric correction", 409);
}
function frameAtoms(value: unknown): Record<string, string | boolean | null> {
  if (!value || typeof value !== "object") return {};
  const row = object(value);
  return Object.fromEntries(["pixelFormat", "range", "matrix", "primaries", "transfer", "hdrSignaled"].map(key =>
    [key, typeof row[key] === "string" ? row[key].slice(0, 100) : typeof row[key] === "boolean" ? row[key] : null]));
}
function screening(value: unknown): number[] {
  if (!Array.isArray(value) || value.length > 1) throw new ColorError("Invalid screening evidence", 409);
  return value.map(object).map(row => {
    if (row.kind !== "review-normalized-luma-offset" || row.applicableToPlan !== false
        || row.requiresOperatorComparison !== true || row.confidence !== "screening-only"
        || number(row.value) === null || Math.abs(Number(row.value)) > 0.04) throw new ColorError("Invalid screening evidence", 409);
    return Number(row.value);
  });
}
export function baseStatus(request: JobRequest, parentsCurrent: boolean): ColorJob {
  return { ok: true, kind: "job", jobId: request.request.jobId, state: "running", startedAt: request.startedAt,
    elapsedMs: Math.max(0, Date.now() - Date.parse(request.startedAt)), queueMs: 0, cleanupVerified: false,
    inputsRevalidated: false, parentsCurrent, error: null, planHash: request.request.expectedPlanHash,
    manifestHash: request.request.expectedManifestHash, diagnosticId: null, groups: [], timings: [],
    caveats: ["Private, unreviewed screening; no grade, draft, render or approval is written."],
    reviewState: "unreviewed", deliveryApproved: false, qualityQualified: false, writesGrade: false };
}
export function completedStatus(request: JobRequest, terminal: JobTerminal, current: boolean): ColorJob {
  const base = baseStatus(request, current);
  if (terminal.requestDigest !== request.digest || typeof terminal.cleanupVerified !== "boolean" || typeof terminal.interrupted !== "boolean"
      || number(terminal.elapsedMs) === null || terminal.elapsedMs < 0) throw new ColorError("Diagnostic terminal binding is invalid", 409);
  if (!terminal.diagnosticId || terminal.interrupted) return { ...base, state: "interrupted",
    elapsedMs: terminal.elapsedMs, cleanupVerified: terminal.cleanupVerified,
    error: "Diagnostic outcome is interrupted or unknown. No grade was written; cleanup may require operator recovery." };
  if (!UUID.test(terminal.diagnosticId)) throw new ColorError("Invalid diagnostic evidence identity", 409);
  const directory = privateDir(path.join(privateDir(path.join(request.request.dir, ".sniper-color-diagnostics")), terminal.diagnosticId));
  const invocation = checkedArtifact(path.join(directory, "request.json"));
  const result = checkedArtifact(path.join(directory, "result.json"));
  if (result.diagnosticId !== terminal.diagnosticId || invocation.diagnosticId !== terminal.diagnosticId
      || result.schemaVersion !== 1 || invocation.schemaVersion !== 1) throw new ColorError("Diagnostic artifact identity is inconsistent", 409);
  verifyBindings(request, invocation, result);
  const groups = (result.groups as unknown[]).map(value => groupProjection(value, request));
  return { ...base, state: result.state as ColorJob["state"], elapsedMs: terminal.elapsedMs,
    cleanupVerified: terminal.cleanupVerified, diagnosticId: terminal.diagnosticId,
    inputsRevalidated: result.inputsRevalidated === true, groups, caveats: strings(result.caveats),
    error: result.state === "failed" ? "Diagnostic failed safely. Check source admission, configured runtime, and retained private attempt evidence; no grade was written." : null,
    timings: (result.workers as unknown[]).map(workerTiming) };
}
function verifyBindings(request: JobRequest, invocation: Record<string, unknown>, result: Record<string, unknown>): void {
  if (invocation.policy !== POLICY || invocation.producerDir !== request.request.dir
      || invocation.planHash !== request.request.expectedPlanHash || invocation.manifestHash !== request.request.expectedManifestHash
      || canonicalJsonSha256(invocation.contexts) !== canonicalJsonSha256(request.request.contexts)
      || result.policy !== POLICY || result.requestHash !== canonicalJsonSha256(invocation)
      || result.reviewState !== "unreviewed" || result.deliveryApproved !== false || result.qualityQualified !== false || result.writesGrade !== false
      || !["complete", "partial", "failed"].includes(String(result.state)) || !Array.isArray(result.groups) || result.groups.length > 8
      || !Array.isArray(result.workers) || result.workers.length > 8) throw new ColorError("Diagnostic parent or authority binding is invalid", 409);
  if (result.state === "failed" && result.groups.length) throw new ColorError("Failed diagnostic contains suggestions", 409);
  if (result.state !== "failed" && (result.inputsRevalidated !== true || result.groups.length !== request.request.contexts.length)) {
    throw new ColorError("Diagnostic source closure is invalid", 409);
  }
  if (result.state !== "failed") {
    const bindings = object(result.bindings), sources = (result.sources as unknown[]).map(object);
    if (bindings.planHash !== request.request.expectedPlanHash || bindings.manifestHash !== request.request.expectedManifestHash
        || bindings.declaredContextHash !== canonicalJsonSha256(request.request.contexts)
        || sources.length !== request.descriptor.sources.length || new Set(sources.map(row => row.sourceId)).size !== sources.length
        || sources.some(row => !request.descriptor.sources.some(source => source.id === row.sourceId && source.sha256 === row.sha256))
        || new Set((result.groups as unknown[]).map(value => object(value).sourceId)).size !== sources.length) {
      throw new ColorError("Diagnostic source/parent binding is inconsistent", 409);
    }
  }
}
function workerTiming(value: unknown): ColorJob["timings"][number] {
  const row = object(value), envelope = row.envelope ? object(row.envelope) : {};
  const worker = envelope.worker ? object(envelope.worker) : {}, tools = worker.tools ? object(worker.tools) : {};
  const timing = worker.timing ? object(worker.timing) : {};
  const phases = envelope.phaseTimingsMs ? object(envelope.phaseTimingsMs) : {};
  return { sourceId: String(row.sourceId).slice(0, 200), elapsedMs: number(envelope.elapsedMs ?? row.elapsedMs) ?? 0,
    workerMs: number(timing.elapsedMs), ffmpeg: typeof tools.ffmpeg === "string" ? tools.ffmpeg.slice(0, 200) : null,
    phases: Object.fromEntries(Object.entries(phases).filter(([, n]) => number(n) !== null && Number(n) >= 0)) as Record<string, number> };
}
