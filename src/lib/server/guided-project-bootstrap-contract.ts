/** New-only project intake; neither a cut decision nor source/preview approval. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { exactKeys, objectValue, sha256, stringValue, uuid, isoDate } from "@/lib/producer/contracts/validation";
import { parseGuidedWorkflowV2 } from "@/lib/producer/contracts/guided-workflow-v2";
import { validateIntent, validateLaneOverrides, resolveLanes, type ProjectIntent } from "@/lib/producer/intent-presets";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";

export interface BootstrapFileRef { path: string; sha256: string }
export interface GuidedProjectBootstrapRequest {
  schemaVersion: 1; operation: "bootstrap-existing-cut"; idempotencyKey: string;
  manifest: BootstrapFileRef; candidate: BootstrapFileRef; intent: ProjectIntent;
}
export interface ExistingCutCandidatePolicy {
  schemaVersion: 1; policy: "previsual-review-only";
  requestHash: string; inputPlanSha256: string; savedPlanSha256: string;
}
export interface GuidedProjectAuthorCutRequest {
  schemaVersion: 1; operation: "author-cut"; idempotencyKey: string;
  manifest: BootstrapFileRef; intent: ProjectIntent;
  output: { width: number; height: number; fps: number };
}
export type GuidedProjectRequest = GuidedProjectBootstrapRequest | GuidedProjectAuthorCutRequest;
export interface AuthoredCutPolicy {
  schemaVersion: 1; policy: "source-brief-cut"; requestHash: string;
  initialPlanSha256: string; transcriptDigest: string; preparationStartedAt: string;
}

export function bootstrapFileRef(value: unknown): BootstrapFileRef {
  const row = objectValue(value, "bootstrap file");
  exactKeys(row, ["path", "sha256"], ["path", "sha256"], "bootstrap file");
  const file = stringValue(row.path, "bootstrap file path", 4096);
  if (!path.isAbsolute(file) || path.resolve(file) !== file || /[\0\r\n]/u.test(file)) {
    throw new Error("Bootstrap input path must be absolute and canonical");
  }
  return { path: file, sha256: sha256(row.sha256, "bootstrap file hash") };
}

export function parseBootstrapRequest(value: unknown): GuidedProjectBootstrapRequest {
  const row = objectValue(value, "guided project bootstrap");
  const keys = ["schemaVersion", "operation", "idempotencyKey", "manifest", "candidate", "intent"];
  exactKeys(row, keys, keys, "guided project bootstrap");
  if (row.schemaVersion !== 1 || row.operation !== "bootstrap-existing-cut") throw new Error("Unsupported bootstrap operation");
  uuid(row.idempotencyKey, "idempotencyKey"); bootstrapFileRef(row.manifest); bootstrapFileRef(row.candidate);
  bootstrapIntent(row.intent);
  return row as unknown as GuidedProjectBootstrapRequest;
}

function bootstrapIntent(value: unknown): ProjectIntent {
  const intent = objectValue(value, "operator intent");
  exactKeys(intent, ["mode", "scope", "lanes", "brief", "excerpt", "pace", "style", "reference", "music", "audioEnhance", "preset"],
    ["mode", "scope", "lanes"], "operator intent");
  const parsed = validateIntent(intent);
  if (!isDeepStrictEqual(parsed, intent)) throw new Error("Submit exact validated operator intent; bootstrap does not normalize it");
  // Studied references need the existing resolved reference decision, not a caller path.
  if (parsed.reference) throw new Error("Existing-cut bootstrap does not yet support studied-reference context");
  return parsed;
}

function outputRate(value: unknown): void {
  if (typeof value === "number" && Number.isFinite(value) && value >= 1 && value <= 60) return;
  throw new Error("Output fps must be a finite number within 1..60; rational-string targets are unsupported");
}

export function parseAuthorCutRequest(value: unknown): GuidedProjectAuthorCutRequest {
  const row = objectValue(value, "guided authored cut");
  const keys = ["schemaVersion", "operation", "idempotencyKey", "manifest", "intent", "output"];
  exactKeys(row, keys, keys, "guided authored cut");
  if (row.schemaVersion !== 1 || row.operation !== "author-cut") throw new Error("Unsupported authored-cut operation");
  uuid(row.idempotencyKey, "idempotencyKey"); bootstrapFileRef(row.manifest);
  const intent = bootstrapIntent(row.intent);
  stringValue(intent.brief, "author-cut intent.brief", 1200);
  const output = objectValue(row.output, "author-cut output");
  exactKeys(output, ["width", "height", "fps"], ["width", "height", "fps"], "author-cut output");
  const [width, height] = intent.mode === "short" ? [1080, 1920] : [1920, 1080];
  if (output.width !== width || output.height !== height) throw new Error("Author-cut output canvas is unsupported for this mode");
  outputRate(output.fps);
  return row as unknown as GuidedProjectAuthorCutRequest;
}

export function parseGuidedProjectRequest(value: unknown): GuidedProjectRequest {
  const row = objectValue(value, "guided project request");
  return row.operation === "author-cut" ? parseAuthorCutRequest(row) : parseBootstrapRequest(row);
}

export function parseAuthoredCutPolicy(value: unknown): AuthoredCutPolicy {
  const row = objectValue(value, "authored cut policy");
  const keys = ["schemaVersion", "policy", "requestHash", "initialPlanSha256", "transcriptDigest", "preparationStartedAt"];
  exactKeys(row, keys, keys, "authored cut policy");
  if (row.schemaVersion !== 1 || row.policy !== "source-brief-cut") throw new Error("Unsupported authored-cut policy");
  for (const key of ["requestHash", "initialPlanSha256", "transcriptDigest"]) sha256(row[key], key);
  const started = isoDate(row.preparationStartedAt, "preparationStartedAt");
  if (Date.parse(started) > Date.now()) throw new Error("Authored-cut preparation time cannot be future");
  return row as unknown as AuthoredCutPolicy;
}

/** Presence only, never validation or execution permission. */
export function hasGuidedBootstrap(ctx: AutoEditCtx): boolean {
  return ctx.existingCutCandidate !== undefined || ctx.authoredCut !== undefined;
}

export function parseExistingCutCandidate(value: unknown): ExistingCutCandidatePolicy {
  const row = objectValue(value, "existing cut candidate policy");
  const keys = ["schemaVersion", "policy", "requestHash", "inputPlanSha256", "savedPlanSha256"];
  exactKeys(row, keys, keys, "existing cut candidate policy");
  if (row.schemaVersion !== 1 || row.policy !== "previsual-review-only") throw new Error("Unsupported existing-cut policy");
  for (const key of keys.slice(2)) sha256(row[key], key);
  return row as unknown as ExistingCutCandidatePolicy;
}

/** Dispatch and persistence both call this; omission leaves all historical paths unchanged. */
export function assertExistingCutContext(ctx: AutoEditCtx): void {
  if (!hasGuidedBootstrap(ctx)) return;
  if (ctx.existingCutCandidate !== undefined && ctx.authoredCut !== undefined) throw new Error("Bootstrap policies are mutually exclusive");
  if (ctx.authoredCut !== undefined) parseAuthoredCutPolicy(ctx.authoredCut);
  else parseExistingCutCandidate(ctx.existingCutCandidate);
  parseGuidedWorkflowV2(ctx.workflowV2);
  if (ctx.workflowPolicy !== "cut-first" || ctx.deliveryPolicy !== "mp4-only") {
    throw new Error("Existing cut review requires the new V2 cut-first MP4-only workflow");
  }
}

export function validExistingCutContext(ctx: AutoEditCtx): boolean {
  try { assertExistingCutContext(ctx); return true; } catch { return false; }
}

/** Identity only: previsual emptiness never waives eventual visual-lane obligations. */
export function assertBootstrapIntent(plan: Record<string, unknown>, intent: ProjectIntent): void {
  const target = objectValue(plan.target, "candidate target");
  if ((Object.hasOwn(target, "music") && typeof target.music !== "boolean")
      || (Object.hasOwn(intent, "music") && typeof intent.music !== "boolean")
      || (target.music === true) !== (intent.music === true)) {
    throw new Error("Candidate music intent must be boolean and match stored operator intent (omission means false)");
  }
  if (target.mode !== intent.mode || target.scope !== intent.scope) throw new Error("Candidate mode/scope differs from operator intent");
  if ((intent.scope === "produced" || intent.scope === "full") && target.treatment !== "produced") {
    throw new Error("Produced/full intent requires its authored produced treatment, even in a cut-only candidate");
  }
  const actual = resolveLanes(intent.scope, validateLaneOverrides(target.lanes));
  if (!isDeepStrictEqual(actual, resolveLanes(intent.scope, intent.lanes))) throw new Error("Candidate lane ownership differs from operator intent");
  for (const key of ["pace", "style", "excerpt"] as const) {
    if (target[key] !== intent[key]) throw new Error(`Candidate ${key} differs from operator intent`);
  }
  if (target.referenceId !== undefined || target.referenceStrategy !== undefined) throw new Error("Candidate has an unrequested reference");
}
