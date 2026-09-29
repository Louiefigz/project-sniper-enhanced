/** Explicit review-draft authority for native Shorts: recorded findings or a recorded pending review.
 * A draft keeps the actual review state; it is never a pass, never legacy/missing-review semantics
 * and never final admission. Source, timing and technical gates are unchanged by this module.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { canonicalJson } from "./auto-edit-hash";
import {
  assertNativePrebuildPublication, assertNativeShortPrebuildReview, nativePrebuildReviewStatus,
  nativeShortPrebuildPlanHash, readNativeShortPrebuildRecord, type NativePrebuildReview,
} from "./native-short-prebuild-review";
import type { NativeShortProjectInput } from "./native-short-project";

export const NATIVE_DRAFT_LABEL = "REVIEW DRAFT - editorial review pending; not final";

/** Command-derived; authors cannot declare it and the review plan hash excludes it. */
export type NativeShortDraftAuthority =
  | { schemaVersion: 1; state: "review-findings"; verdict: "revise" | "block"; materialIssueCodes: string[] }
  | { schemaVersion: 1; state: "review-pending" };
export type NativeReviewMode = "final" | "draft";
interface ProjectReviewAuthority { review?: NativePrebuildReview; status: Record<string, unknown>; draft: boolean }
interface ManifestReviewFields { prebuildReview?: unknown; reviewState?: unknown }

function derived(input: NativeShortProjectInput): { authority: NativeShortDraftAuthority; record?: NativePrebuildReview } {
  if (!input.prebuildReview) return { authority: { schemaVersion: 1, state: "review-pending" } };
  const record = readNativeShortPrebuildRecord(input);
  if (record.review.verdict === "pass") {
    throw new Error("The recorded prebuild review passes; use build for a final-eligible project (a draft-built project can never be promoted)");
  }
  return { record, authority: { schemaVersion: 1, state: "review-findings", verdict: record.review.verdict,
    materialIssueCodes: record.review.materialIssues.map(issue => issue.code) } };
}

/** build-draft: a current non-pass review keeps its findings; no review is recorded as pending. */
export function deriveNativeShortDraftAuthority(input: NativeShortProjectInput): NativeShortDraftAuthority {
  if ("draft" in input) throw new Error("Plan already declares draft authority; build-draft derives it from the recorded review state");
  return derived(input).authority;
}

/** build keeps its passing-review requirement; build-draft never manufactures one. */
export function assertNativeBuildAuthority(operation: "build" | "build-draft",
  plan: NativeShortProjectInput): NativeShortDraftAuthority | undefined {
  if (operation === "build-draft") return deriveNativeShortDraftAuthority(plan);
  if ("draft" in plan) throw new Error("A final build cannot carry draft authority; use build-draft");
  assertNativeShortPrebuildReview(plan);
  return undefined;
}

function draftStatus(input: NativeShortProjectInput, value: ReturnType<typeof derived>): Record<string, unknown> {
  if (!value.record) {
    return { status: "independent-plan-review-pending-review-draft", planHash: nativeShortPrebuildPlanHash(input), finalEligible: false };
  }
  return { status: "recorded-independent-plan-findings-review-draft", planHash: value.record.planHash,
    receiptSha256: input.prebuildReview!.sha256, verdict: value.record.review.verdict,
    materialIssueCodes: value.record.review.materialIssues.map(issue => issue.code),
    independence: "reviewer-declared-not-authenticated", finalEligible: false };
}

/** Writer and reader authority: a final requires a pass; a draft must equal its recorded state. */
export function nativeProjectReviewAuthority(input: NativeShortProjectInput): ProjectReviewAuthority {
  if (input.draft === undefined) {
    const review = assertNativeShortPrebuildReview(input);
    return { review, status: nativePrebuildReviewStatus(input, review), draft: false };
  }
  const authored = { ...input }; delete authored.draft;
  const value = derived(authored);
  if (canonicalJson(value.authority) !== canonicalJson(input.draft)) {
    throw new Error("Native draft authority differs from its recorded prebuild review state");
  }
  return { review: value.record, status: draftStatus(authored, value), draft: true };
}

export function nativeReviewFiles(authority: ProjectReviewAuthority): Record<string, string> {
  return authority.review ? { "PREBUILD-REVIEW.json": canonicalJson(authority.review) } : {};
}

export function nativeReviewManifest(authority: ProjectReviewAuthority):
  { prebuildReview: Record<string, unknown>; reviewState?: "draft" } {
  return { prebuildReview: authority.status, ...(authority.draft ? { reviewState: "draft" as const } : {}) };
}

function describe(draft: NativeShortDraftAuthority): string {
  return draft.state === "review-pending" ? "independent plan review pending"
    : `${draft.verdict}: ${draft.materialIssueCodes.join(", ")}`;
}

/** Final readers refuse drafts with a clear reason; draft readers refuse legacy unreviewed projects. */
export function assertNativeReviewMode(input: NativeShortProjectInput, manifest: ManifestReviewFields,
  mode: NativeReviewMode): void {
  if (mode !== "final" && mode !== "draft") throw new Error("Unknown native project review mode");
  if (manifest.reviewState !== undefined && manifest.reviewState !== "draft") {
    throw new Error("Native project manifest declares an unknown review state");
  }
  const draft = input.draft !== undefined;
  if (draft !== (manifest.reviewState === "draft")) throw new Error("Native project review state differs from its draft authority");
  if (draft && mode === "final") {
    throw new Error(`Native project is a review-draft project (${describe(input.draft!)}): ${NATIVE_DRAFT_LABEL}. `
      + "Final readers, builds and exports refuse draft projects; use check-draft or native_export.py --review-draft. "
      + "A draft-built project can never be promoted: rebuild the corrected plan with a passing independent review.");
  }
  if (!draft && mode === "draft" && !input.prebuildReview) {
    throw new Error("Legacy unreviewed native projects cannot become review drafts; rebuild the plan with build-draft");
  }
}

/** Replace the legacy/final publication check with one that keeps draft state explicit. */
export function assertNativeReviewPublication(input: NativeShortProjectInput, directory: string,
  manifest: ManifestReviewFields): void {
  if (input.draft === undefined) {
    assertNativePrebuildPublication(input, directory, manifest.prebuildReview);
    return;
  }
  const authority = nativeProjectReviewAuthority(input);
  if (canonicalJson(manifest.prebuildReview) !== canonicalJson(authority.status)
      || (authority.review && readFileSync(path.join(directory, "PREBUILD-REVIEW.json"), "utf8")
        !== canonicalJson(authority.review))) {
    throw new Error("Native draft review publication differs from its current receipt");
  }
}

/** Draft-mode check result: explicit review state, open findings and promotion eligibility. */
export function nativeDraftCheck(input: NativeShortProjectInput) {
  const authority = nativeProjectReviewAuthority(input);
  const issues = authority.draft ? authority.review?.review.materialIssues ?? [] : [];
  return { status: "project-current", reviewState: authority.draft ? "draft" : "final-eligible",
    finalEligible: !authority.draft, promotable: !authority.draft, draft: input.draft ?? null,
    label: authority.draft ? NATIVE_DRAFT_LABEL : null, prebuildReview: authority.status,
    openFindings: issues.map(({ code, severity, lane, message, requiredAction }) =>
      ({ code, severity, lane, message, requiredAction, source: "prebuild-review" })),
    totalFrames: input.canvas.totalFrames, humanApproved: false };
}
