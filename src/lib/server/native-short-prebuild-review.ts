/** Recorded independent editorial review admission; hashes do not authenticate reviewer independence. */
import { readFileSync } from "node:fs";
import path from "node:path";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { validateProducerReview, type ProducerReview } from "@/app/api/producer/auto-edit/review-contract";
import { exactKeys, objectValue, sha256, stringValue } from "@/lib/producer/contracts/validation";
import { canonicalJson, canonicalJsonSha256 } from "./auto-edit-hash";
import type { NativeShortProjectInput } from "./native-short-project";

export interface NativePrebuildReviewBinding { path: string; sha256: string }
export const NATIVE_PREBUILD_COVERAGE = ["briefAndRetainedMessage", "assetsAndSourceEvidence", "cuesAndSceneCoverage",
  "layoutCropAndText", "motionAndTransitions", "pacingAndAudio", "feasibility"] as const;
export interface NativePrebuildReview {
  schemaVersion: 1; scope: "native-short-full-plan" | "native-long-full-project"; planHash: string;
  reviewer: { identity: string; sessionId: string; plannerSessionId: string; independent: true };
  /** Explain each assessment, including a reason when a lane is not applicable. */
  coverage: Record<(typeof NATIVE_PREBUILD_COVERAGE)[number], string>;
  evidence: NativePrebuildReviewBinding[];
  review: ProducerReview;
}

/** Bind every authored field. Generated transport retains its separate source/proposal validators.
 * preparedSources changes only executable media URLs; guidedBinding hashes this review reference,
 * so including either generated binding would stale the review or create a digest cycle.
 */
export function nativeShortPrebuildPlanHash(input: NativeShortProjectInput): string {
  const authored = { ...input };
  delete authored.prebuildReview; delete authored.preparedSources; delete authored.guidedBinding;
  return canonicalJsonSha256(authored);
}

function binding(value: unknown): NativePrebuildReviewBinding {
  const row = objectValue(value, "Native prebuild review file");
  exactKeys(row, ["path", "sha256"], ["path", "sha256"], "Native prebuild review file");
  const file = stringValue(row.path, "Native prebuild review path", 4096);
  if (!path.isAbsolute(file) || path.resolve(file) !== file) throw new Error("Native prebuild review path must be canonical");
  return { path: file, sha256: sha256(row.sha256, "Native prebuild review file hash") };
}

function reviewer(value: unknown): NativePrebuildReview["reviewer"] {
  const row = objectValue(value, "Native prebuild reviewer"), keys = ["identity", "sessionId", "plannerSessionId", "independent"];
  exactKeys(row, keys, keys, "Native prebuild reviewer");
  const identity = stringValue(row.identity, "Reviewer identity", 256);
  const sessionId = stringValue(row.sessionId, "Reviewer session", 256);
  const plannerSessionId = stringValue(row.plannerSessionId, "Planner session", 256);
  if (row.independent !== true || sessionId === plannerSessionId) throw new Error("Native prebuild review requires a declared separate independent reviewer");
  return { identity, sessionId, plannerSessionId, independent: true };
}

function coverage(value: unknown): NativePrebuildReview["coverage"] {
  const row = objectValue(value, "Native prebuild full-plan coverage");
  exactKeys(row, NATIVE_PREBUILD_COVERAGE, NATIVE_PREBUILD_COVERAGE, "Native prebuild full-plan coverage");
  return Object.fromEntries(NATIVE_PREBUILD_COVERAGE.map(key => [key,
    stringValue(row[key], `Native prebuild coverage ${key}`, 2000)])) as NativePrebuildReview["coverage"];
}

function evidence(value: unknown): NativePrebuildReviewBinding[] {
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

function parseReview(value: unknown, planHash: string, scope: NativePrebuildReview["scope"]): NativePrebuildReview {
  const row = objectValue(value, "Native prebuild review"), keys = ["schemaVersion", "scope", "planHash", "reviewer", "coverage", "evidence", "review"];
  exactKeys(row, keys, keys, "Native prebuild review");
  if (row.schemaVersion !== 1 || row.scope !== scope) throw new Error("Native prebuild review must cover the full plan");
  if (sha256(row.planHash, "Native prebuild plan hash") !== planHash) {
    throw new Error("Native prebuild review is stale for the current authored plan");
  }
  const review = validateProducerReview(row.review, "plan");
  if (review.verdict !== "pass" || review.materialIssues.length) throw new Error("Native prebuild review must pass with zero material issues");
  return { schemaVersion: 1, scope, planHash: row.planHash as string,
    reviewer: reviewer(row.reviewer), coverage: coverage(row.coverage), evidence: evidence(row.evidence), review };
}

/** Fail before dependent preparation. This is a recorded judgment, not a pixel or playback test. */
export function assertNativeShortPrebuildReview(input: NativeShortProjectInput): NativePrebuildReview {
  if (!input.prebuildReview) throw new Error("Native build requires a separate current independent full-plan prebuild review");
  const ref = binding(input.prebuildReview), observed = readCutPreviewObject(ref.path);
  if (observed.sha256 !== ref.sha256) throw new Error("Native prebuild review receipt changed");
  return parseReview(observed.value, nativeShortPrebuildPlanHash(input), "native-short-full-plan");
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
