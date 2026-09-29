/** Recorded independent editorial review admission; hashes do not authenticate reviewer independence. */
import { readFileSync } from "node:fs";
import path from "node:path";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { validateProducerReview, type ProducerReview } from "@/app/api/producer/auto-edit/review-contract";
import { exactKeys, objectValue, sha256, stringValue } from "@/lib/producer/contracts/validation";
import { canonicalJson, canonicalJsonSha256 } from "./auto-edit-hash";
import type { NativeShortProjectInput } from "./native-short-project";
import { assertBoundToTargets, readInspection, type Inspection } from "./native-review-submission-shared";
import { assertSubmission, type Submission } from "./native-review-provenance";
import type { ApprovedContent } from "./native-review-approved-content";

export interface NativePrebuildReviewBinding { path: string; sha256: string }
export const NATIVE_PREBUILD_COVERAGE = ["briefAndRetainedMessage", "assetsAndSourceEvidence", "cuesAndSceneCoverage",
  "layoutCropAndText", "motionAndTransitions", "pacingAndAudio", "feasibility", "visualSourceSelection"] as const;
/** Schema 2 adds typed inspection (stills/playback/listening of bound artifacts); schema 1 stays readable, untyped. */
export interface NativePrebuildReview {
  schemaVersion: 1 | 2; scope: "native-short-full-plan" | "native-long-full-project" | "native-long-section-snapshot"; planHash: string;
  reviewer: { identity: string; sessionId: string; plannerSessionId: string; independent: true };
  /** Explain each assessment, including a reason when a lane is not applicable. */
  coverage: Record<(typeof NATIVE_PREBUILD_COVERAGE)[number], string>;
  evidence: NativePrebuildReviewBinding[];
  review: ProducerReview;
  /** Present exactly when schemaVersion is 2. A plan review approves the plan only, so approves is always []. */
  inspection?: Inspection;
  /** Schema 2: the answered role packet and times, re-checked on every read. */
  submission?: Submission;
  /** Schema 2: the operator's approved identity, departures and approved-content findings. */
  approvedContent?: ApprovedContent;
}
const RECORD_KEYS = ["schemaVersion", "scope", "planHash", "reviewer", "coverage", "evidence", "review"];

/** Bind every authored field. Generated transport retains its separate source/proposal validators.
 * preparedSources changes only executable media URLs; guidedBinding hashes this review reference,
 * so including either generated binding would stale the review or create a digest cycle.
 * draft is review-draft authority that build-draft derives from this review (or its recorded
 * absence); like the review reference it is never authored and would create the same cycle.
 */
export function nativeShortPrebuildPlanHash(input: NativeShortProjectInput): string {
  const authored = { ...input };
  delete authored.prebuildReview; delete authored.preparedSources; delete authored.guidedBinding;
  delete authored.draft;
  return canonicalJsonSha256(authored);
}

function binding(value: unknown): NativePrebuildReviewBinding {
  const row = objectValue(value, "Native prebuild review file");
  exactKeys(row, ["path", "sha256"], ["path", "sha256"], "Native prebuild review file");
  const file = stringValue(row.path, "Native prebuild review path", 4096);
  if (!path.isAbsolute(file) || path.resolve(file) !== file) throw new Error("Native prebuild review path must be canonical");
  return { path: file, sha256: sha256(row.sha256, "Native prebuild review file hash") };
}

export function reviewIdentity(value: unknown): NativePrebuildReview["reviewer"] {
  const row = objectValue(value, "Native prebuild reviewer"), keys = ["identity", "sessionId", "plannerSessionId", "independent"];
  exactKeys(row, keys, keys, "Native prebuild reviewer");
  const identity = stringValue(row.identity, "Reviewer identity", 256);
  const sessionId = stringValue(row.sessionId, "Reviewer session", 256);
  const plannerSessionId = stringValue(row.plannerSessionId, "Planner session", 256);
  if (row.independent !== true || sessionId === plannerSessionId) throw new Error("Native prebuild review requires a declared separate independent reviewer");
  return { identity, sessionId, plannerSessionId, independent: true };
}

export function reviewCoverage(value: unknown): NativePrebuildReview["coverage"] {
  const row = objectValue(value, "Native prebuild full-plan coverage");
  exactKeys(row, NATIVE_PREBUILD_COVERAGE, NATIVE_PREBUILD_COVERAGE, "Native prebuild full-plan coverage");
  return Object.fromEntries(NATIVE_PREBUILD_COVERAGE.map(key => [key,
    stringValue(row[key], `Native prebuild coverage ${key}`, 2000)])) as NativePrebuildReview["coverage"];
}

export function reviewEvidence(value: unknown): NativePrebuildReviewBinding[] {
  if (!Array.isArray(value) || !value.length || value.length > 32) throw new Error("Native prebuild review needs 1–32 evidence files");
  const files = value.map(binding);
  if (new Set(files.map(file => file.path)).size !== files.length) throw new Error("Native prebuild review evidence duplicates a path");
  for (const file of files) {
    if (observeCutPreviewFile(file.path, 256 * 1024 ** 2).sha256 !== file.sha256) {
      throw new Error("Native prebuild review evidence changed");
    }
  }
  return files;
}

/** A plan record's typed inspection: bound artifacts only, no program frame spans and no approved aspects. */
export function planInspection(value: unknown): Inspection {
  const inspection = readInspection(value, "Native prebuild review inspection");
  if (inspection.approves.length) {
    throw new Error("A plan review approves the plan only: approves must be []; picture, motion and audio are approved "
      + "on rendered media by the motion and final critics");
  }
  assertBoundToTargets(inspection, []);
  return inspection;
}

/** Validate a complete current record; the verdict gate is separate so drafts keep real findings. */
function parseRecord(value: unknown, planHash: string, scope: NativePrebuildReview["scope"]): NativePrebuildReview {
  const row = objectValue(value, "Native prebuild review"), typed = row.schemaVersion === 2;
  const keys = typed ? [...RECORD_KEYS, "inspection", "submission", "approvedContent"] : RECORD_KEYS;
  exactKeys(row, keys, keys, "Native prebuild review");
  if ((row.schemaVersion !== 1 && !typed) || row.scope !== scope) throw new Error("Native prebuild review must cover the full plan");
  if (sha256(row.planHash, "Native prebuild plan hash") !== planHash) {
    throw new Error("Native prebuild review is stale for the current authored plan");
  }
  const review = validateProducerReview(row.review, "plan");
  const record: NativePrebuildReview = { schemaVersion: typed ? 2 : 1, scope, planHash: row.planHash as string,
    reviewer: reviewIdentity(row.reviewer), coverage: reviewCoverage(row.coverage), evidence: reviewEvidence(row.evidence), review };
  return typed ? typedParts(row, record) : record;
}

/** Schema-2 parts: plan inspection, re-checked provenance and approved content. */
function typedParts(row: Record<string, unknown>, record: NativePrebuildReview): NativePrebuildReview {
  const inspection = planInspection(row.inspection);
  const { submission, approvedContent } = assertSubmission(row.submission, { role: "plan-critic", evidence: record.evidence,
    inspection, targets: [], fps: 1, reviewer: record.reviewer, verdict: record.review.verdict,
    approvedContent: row.approvedContent, subject: { plan: record.planHash }, record: row });
  return { ...record, inspection, submission, approvedContent };
}

function parseReview(value: unknown, planHash: string, scope: NativePrebuildReview["scope"]): NativePrebuildReview {
  const record = parseRecord(value, planHash, scope);
  if (record.review.verdict !== "pass" || record.review.materialIssues.length) throw new Error("Native prebuild review must pass with zero material issues");
  if (scope === "native-short-full-plan" && record.schemaVersion !== 2) {
    throw new Error("A native Short build needs a schema-2 plan review from a role packet (typed inspection, provenance and "
      + "the operator's approved content, re-checked now); a schema-1 record is historical and readable for display only");
  }
  return record;
}

function readShortRecord(input: NativeShortProjectInput) {
  if (!input.prebuildReview) throw new Error("Native build requires a separate current independent full-plan prebuild review");
  const ref = binding(input.prebuildReview), observed = readCutPreviewObject(ref.path);
  if (observed.sha256 !== ref.sha256) throw new Error("Native prebuild review receipt changed");
  return observed.value;
}

/** Fail before dependent preparation. This is a recorded judgment, not a pixel or playback test. */
export function assertNativeShortPrebuildReview(input: NativeShortProjectInput): NativePrebuildReview {
  return parseReview(readShortRecord(input), nativeShortPrebuildPlanHash(input), "native-short-full-plan");
}

/** The same current, independent, evidence-bound record whatever its verdict; never a final admission. */
export function readNativeShortPrebuildRecord(input: NativeShortProjectInput): NativePrebuildReview {
  return parseRecord(readShortRecord(input), nativeShortPrebuildPlanHash(input), "native-short-full-plan");
}

/** The Python inventory binds all native Long authored/media bytes, excluding this receipt. */
export function assertNativeLongPrebuildReview(file: string, planHash: string): NativePrebuildReview {
  return parseReview(readCutPreviewObject(file).value, sha256(planHash, "Long project hash"), "native-long-full-project");
}

/** Explicit provenance limits travel with the frozen project, without implying human approval. */
export function nativePrebuildReviewStatus(input: NativeShortProjectInput, review: NativePrebuildReview) {
  return { status: "recorded-independent-plan-pass", planHash: review.planHash,
    receiptSha256: input.prebuildReview!.sha256, independence: "reviewer-declared-not-authenticated" };
}

/** Historical projects without this record stay readable; they gain no creative approval. */
export function assertNativePrebuildPublication(input: NativeShortProjectInput, directory: string, status: unknown): void {
  if (!input.prebuildReview) {
    if (status !== undefined) throw new Error("Legacy native project cannot claim a prebuild review without its receipt");
    return;
  }
  const review = assertNativeShortPrebuildReview(input);
  if (canonicalJson(status) !== canonicalJson(nativePrebuildReviewStatus(input, review))
      || readFileSync(path.join(directory, "PREBUILD-REVIEW.json"), "utf8") !== canonicalJson(review)) {
    throw new Error("Native prebuild review publication differs from its current receipt");
  }
}

/** A scoped immutable snapshot may authorize owned ranges only; final Long admission rejects this scope. */
export function assertNativeLongSectionPrebuildReview(file: string, scopeHash: string): NativePrebuildReview {
  return parseReview(readCutPreviewObject(file).value, sha256(scopeHash, "Long section snapshot hash"), "native-long-section-snapshot");
}
