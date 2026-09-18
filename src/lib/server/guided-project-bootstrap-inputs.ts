/** Observe submitted input metadata without moving sources or synthesizing transcript authority. */
import { isDeepStrictEqual } from "node:util";
import path from "node:path";
import { realpathSync } from "node:fs";
import { objectValue } from "@/lib/producer/contracts/validation";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseTreatmentRequestJson, MAX_TREATMENT_REQUEST_BYTES } from "../../../scripts/producer/guided-treatment-json";
import { assertBootstrapIntent, type BootstrapFileRef, type GuidedProjectRequest, type GuidedProjectAuthorCutRequest } from "./guided-project-bootstrap-contract";
import { autoEditTranscriptDigest } from "./auto-edit-authority-snapshot";

export function readBootstrapJson(ref: BootstrapFileRef) {
  const held = observeCutPreviewFile(ref.path, MAX_TREATMENT_REQUEST_BYTES, true);
  if (held.sha256 !== ref.sha256) throw new Error("Submitted bootstrap file hash is stale");
  const value = objectValue(parseTreatmentRequestJson(new TextDecoder("utf-8", { fatal: true }).decode(held.bytes)), "bootstrap metadata");
  return { ...held, value };
}

function assertCutOnly(plan: Record<string, unknown>): void {
  const cuts = plan.cutTrack;
  if (!Array.isArray(cuts) || cuts.length < 1 || cuts.length > 500) throw new Error("Bootstrap needs 1..500 explicit existing cuts");
  for (const key of ["graphicsTrack", "punchIns", "brollTrack", "transitions", "overlays", "captionsTrack"]) {
    if (plan[key] !== undefined && !isDeepStrictEqual(plan[key], [])) throw new Error("Existing-cut bootstrap requires an empty previsual candidate");
  }
  const version = plan.planVersion ?? 0;
  if (!Number.isSafeInteger(version) || Number(version) < 0 || Number(version) >= Number.MAX_SAFE_INTEGER) {
    throw new Error("Candidate planVersion must be a nonnegative safe integer");
  }
}

function admittedManifest(request: GuidedProjectRequest) {
  const manifest = readBootstrapJson(request.manifest);
  const admission = objectValue(manifest.value.sourceSetAdmission, "existing source-set admission");
  if (!Array.isArray(manifest.value.sources) || !manifest.value.sources.length
      || admission.schemaVersion !== 1) throw new Error("Bootstrap needs an already admitted source manifest");
  return manifest;
}

/** Deliberately unapproved and empty; only the ordinary writer may propose kept speech. */
export function authoredCutSeed(request: GuidedProjectAuthorCutRequest): Record<string, unknown> {
  const intent = request.intent;
  const target = { mode: intent.mode, scope: intent.scope, lanes: structuredClone(intent.lanes),
    ...request.output, durationTargetS: 0,
    platforms: intent.mode === "short" ? ["tiktok", "reels", "shorts"] : ["youtube"],
    ...((intent.scope === "produced" || intent.scope === "full") ? { treatment: "produced" } : {}),
    ...(intent.music !== undefined ? { music: intent.music } : {}),
    ...(intent.excerpt !== undefined ? { excerpt: intent.excerpt } : {}),
    ...(intent.pace !== undefined ? { pace: intent.pace } : {}),
    ...(intent.shortDirection ? { shortDirection: intent.shortDirection } : {}),
    ...(intent.style !== undefined ? { style: intent.style } : {}) };
  return { planVersion: 1, target, cutTrack: [], cutDecisions: { schemaVersion: 1, removals: [] } };
}

function transcriptDigest(request: GuidedProjectAuthorCutRequest, manifest: Record<string, unknown>): string {
  const ctx = { manifestPath: request.manifest.path, transcriptsDir: path.dirname(request.manifest.path) };
  const refs: BootstrapFileRef[] = [];
  for (const value of manifest.sources as unknown[]) {
    const source = objectValue(value, "admitted source"), name = source.transcriptPath;
    if (typeof name !== "string" || !name.trim() || /[\0\r\n]/u.test(name)) throw new Error("Author-cut requires every source transcriptPath");
    const file = path.resolve(path.dirname(request.manifest.path), name);
    if (realpathSync(file) !== file) throw new Error("Author-cut transcript path must resolve canonically without links");
    const held = observeCutPreviewFile(file, 16 * 1024 * 1024, true);
    objectValue(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(held.bytes)), "source transcript");
    refs.push({ path: file, sha256: held.sha256 });
  }
  const original = autoEditTranscriptDigest(ctx);
  for (const ref of refs) {
    if (observeCutPreviewFile(ref.path, 16 * 1024 * 1024).sha256 !== ref.sha256) throw new Error("Author-cut transcripts changed during intake");
  }
  return original;
}

export function readBootstrapInputs(request: GuidedProjectRequest) {
  const manifest = admittedManifest(request);
  if (request.operation === "author-cut") {
    return { manifest, candidate: { value: authoredCutSeed(request) }, transcriptDigest: transcriptDigest(request, manifest.value) };
  }
  const candidate = readBootstrapJson(request.candidate);
  // These are expectations only; the actual pinned Python verifier must reobserve source bytes.
  assertCutOnly(candidate.value); assertBootstrapIntent(candidate.value, request.intent);
  return { manifest, candidate };
}
