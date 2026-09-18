import { exactKeys, objectValue, sha256, stringValue, uuid } from "./validation";
import { parsePositiveRationalV1 } from "./positive-rational";
import { parseOpeningFrameRange, type OpeningFrameRange } from "./guided-opening-v1";
import { openingMediaProfile, type OpeningMediaProfile } from "./guided-media-profile";
import { isPresenterOpeningProfile, type PresenterOpeningProfile } from "./guided-presenter-profile";

export type CurrentOpeningMediaProfile = OpeningMediaProfile | PresenterOpeningProfile;

export const OPENING_MEDIA_PROFILE = "unity-source-float-own-screen-v1";
export const OPENING_MEDIA_SCOPE = "private-opening-execution-not-opening-approval-body-or-delivery";
export const OPENING_DOCUMENT_NAMES = Object.freeze(["authority", "acceptedPlan", "cutRequest", "pictureLock", "cutProjection",
  "timelineMap", "readinessReceipt", "readinessPacket", "readinessBundle", "treatmentDraft", "candidatePlan", "manifest",
  "frameBindings", "occurrences"] as const);
export type OpeningDocumentName = typeof OPENING_DOCUMENT_NAMES[number];
export interface OpeningDocumentReference { path: string; sha256: string }
export interface GuidedOpeningMediaInputV1 {
  schemaVersion: 1; kind: "guided-opening-media-input"; executionId: string; executionInputHash: string;
  profile: CurrentOpeningMediaProfile; documents: Record<OpeningDocumentName, OpeningDocumentReference>;
  pipeline: { snapshotRoot: string; lockPath: string; lockSha256: string; digest: string };
}
export interface GuidedOpeningMediaAuthorityV2 {
  schemaVersion: 2; kind: "guided-opening-media-authority"; scope: typeof OPENING_MEDIA_SCOPE; profile: CurrentOpeningMediaProfile;
  runId: string; previewAttempt: number; contextHash: string; cutDecisionHash: string; acceptedRevisionHash: string;
  requestHash: string; pictureLockHash: string; projectionHash: string; sourceSetDigest: string; manifestHash: string; timelineMapHash: string;
  rawAdmissionHash: string; proposalHash: string; readinessHash: string; draftRevisionHash: string; candidatePlanHash: string;
  frameBindingsHash: string; occurrenceEvidenceHash: string; clockHash: string; generationStartedAt: string;
  frameRate: string; totalFrames: number; target: Record<string, unknown>; core: OpeningFrameRange; review: OpeningFrameRange;
}

/** Lexical POSIX boundary only. Actual readers must also reject symlinks/hardlinks and changed inodes. */
export function openingAbsolutePath(value: unknown): string {
  const result = stringValue(value, "opening artifact path", 4096);
  if (!result.startsWith("/") || /[\\\u0000-\u001f]/u.test(result)
      || result.slice(1).split("/").some((part) => !part || part === "." || part === "..")) {
    throw new Error("Opening artifact path must be canonical absolute POSIX syntax");
  }
  return result;
}

/** Server-authored private invocation, never a public request or authenticated approval by itself. */
export function parseGuidedOpeningMediaInput(value: unknown): GuidedOpeningMediaInputV1 {
  return parseOpeningInputProfile(value, OPENING_MEDIA_PROFILE);
}

/** Current dispatcher; historical entrypoint above still refuses every newer class. */
export function parseCurrentOpeningMediaInput(value: unknown): GuidedOpeningMediaInputV1 {
  return parseOpeningInputProfile(value, currentOpeningMediaProfile(objectValue(value, "opening input").profile));
}

/** Closed current token parser only. Exact plan/request and live media ownership remain separate. */
export function currentOpeningMediaProfile(value: unknown): CurrentOpeningMediaProfile {
  return isPresenterOpeningProfile(value) ? value : openingMediaProfile(value);
}

function parseOpeningInputProfile(value: unknown, profile: CurrentOpeningMediaProfile): GuidedOpeningMediaInputV1 {
  const row = objectValue(value, "opening media invocation"), keys = ["schemaVersion", "kind", "executionId", "executionInputHash", "profile", "documents", "pipeline"];
  exactKeys(row, keys, keys, "opening media invocation");
  if (row.schemaVersion !== 1 || row.kind !== "guided-opening-media-input" || row.profile !== profile) throw new Error("Unsupported private opening media class");
  uuid(row.executionId, "opening executionId"); sha256(row.executionInputHash, "executionInputHash");
  const documents = objectValue(row.documents, "opening document references");
  exactKeys(documents, OPENING_DOCUMENT_NAMES, OPENING_DOCUMENT_NAMES, "opening document references");
  for (const name of OPENING_DOCUMENT_NAMES) {
    const ref = objectValue(documents[name], name); exactKeys(ref, ["path", "sha256"], ["path", "sha256"], name);
    openingAbsolutePath(ref.path); sha256(ref.sha256, `${name}.sha256`);
  }
  const pipeline = objectValue(row.pipeline, "opening pipeline reference"), pipelineKeys = ["snapshotRoot", "lockPath", "lockSha256", "digest"];
  exactKeys(pipeline, pipelineKeys, pipelineKeys, "opening pipeline reference");
  openingAbsolutePath(pipeline.snapshotRoot); openingAbsolutePath(pipeline.lockPath);
  sha256(pipeline.lockSha256, "pipeline lockSha256"); sha256(pipeline.digest, "pipeline digest");
  if (new TextEncoder().encode(JSON.stringify(row)).length > 128 * 1024) throw new Error("Opening invocation exceeds128 KiB");
  return row as unknown as GuidedOpeningMediaInputV1;
}

/** Exact preparation identities only. Success, media and either kind of approval are absent. */
export function parseGuidedOpeningMediaAuthority(value: unknown): GuidedOpeningMediaAuthorityV2 {
  return parseOpeningAuthorityProfile(value, OPENING_MEDIA_PROFILE);
}

/** Shape only: exact plan/source/profile relationships are checked by the held reader. */
export function parseCurrentOpeningMediaAuthority(value: unknown): GuidedOpeningMediaAuthorityV2 {
  return parseOpeningAuthorityProfile(value, currentOpeningMediaProfile(objectValue(value, "opening authority").profile));
}

function parseOpeningAuthorityProfile(value: unknown, profile: CurrentOpeningMediaProfile): GuidedOpeningMediaAuthorityV2 {
  const row = objectValue(value, "opening media authority"), keys = ["schemaVersion", "kind", "scope", "profile", "runId", "previewAttempt",
    "contextHash", "cutDecisionHash", "acceptedRevisionHash", "requestHash", "pictureLockHash", "projectionHash", "sourceSetDigest",
    "manifestHash", "timelineMapHash", "rawAdmissionHash", "proposalHash", "readinessHash", "draftRevisionHash", "candidatePlanHash",
    "frameBindingsHash", "occurrenceEvidenceHash", "clockHash", "generationStartedAt", "frameRate", "totalFrames", "target", "core", "review"];
  exactKeys(row, keys, keys, "opening media authority");
  if (row.schemaVersion !== 2 || row.kind !== "guided-opening-media-authority" || row.scope !== OPENING_MEDIA_SCOPE || row.profile !== profile
      || !Number.isSafeInteger(row.previewAttempt) || Number(row.previewAttempt) < 1 || Number(row.previewAttempt) > 10_000
      || !Number.isSafeInteger(row.totalFrames) || Number(row.totalFrames) < 1 || Number(row.totalFrames) > 72_000) throw new Error("Opening media authority identity is malformed");
  for (const key of keys.filter((key) => key.endsWith("Hash") || key.endsWith("Digest"))) sha256(row[key], key);
  stringValue(row.runId, "runId", 200); const started = stringValue(row.generationStartedAt, "generationStartedAt", 30);
  if (!Number.isFinite(Date.parse(started)) || new Date(started).toISOString() !== started) throw new Error("Opening origin is malformed");
  const frameRate = stringValue(row.frameRate, "frameRate", 21), [numerator, denominator, extra] = frameRate.split("/");
  if (extra !== undefined || !denominator) throw new Error("Opening frame clock is malformed");
  const rate = parsePositiveRationalV1({ numerator, denominator }), fps = Number(rate.numerator) / Number(rate.denominator);
  if (fps < 1 || fps > 60) throw new Error("Opening frame clock is outside its qualified cut-preview class");
  const target = objectValue(row.target, "opening target");
  if (!["width", "height"].every((key) => Number.isSafeInteger(target[key]) && Number(target[key]) > 0 && Number(target[key]) <= 16_384)) throw new Error("Opening target is not exact bounded geometry");
  const core = parseOpeningFrameRange(row.core, Number(row.totalFrames)), review = parseOpeningFrameRange(row.review, Number(row.totalFrames));
  if (core.startFrame !== 0 || review.startFrame !== 0 || core.endFrameExclusive > review.endFrameExclusive) throw new Error("Opening review does not contain its origin-bound core");
  return row as unknown as GuidedOpeningMediaAuthorityV2;
}
