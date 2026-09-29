/** Recorded independent review of a checked native Short MP4 (Audit C); never human approval.
 * A checked delivery is a technical pass only. An editorial final needs a schema-2 pass approving picture,
 * motion and audio, each backed by typed whole-program inspection of the exact MP4 bytes. Schema-1 records
 * stay readable as historical untyped declarations and never establish an editorial final. */
import path from "node:path";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { validateProducerReview, type ProducerReview } from "@/app/api/producer/auto-edit/review-contract";
import { exactKeys, objectValue, sha256, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";
import { nativeShortPrebuildPlanHash, reviewCoverage, reviewEvidence, reviewIdentity,
  type NativePrebuildReviewBinding } from "./native-short-prebuild-review";
import type { NativeShortProjectInput } from "./native-short-project";
import { observeLinkedMedia } from "./native-review-packet";
import { assertApprovals, assertBoundToTargets, readInspection, REVIEW_ASPECTS, typedEvidence, untypedEvidence,
  type Inspection, type ReviewAspect, type ReviewTarget } from "./native-review-submission-shared";
import { assertSubmission, frameClock, type Submission } from "./native-review-provenance";
import type { ApprovedContent } from "./native-review-approved-content";
import type { AsSubmitted } from "./native-review-given-check";

export const NATIVE_FINAL_REVIEW_SCOPE = "native-short-rendered-review" as const;
const CHECKED = "native-short-checked-for-review";
const COMMON = ["schemaVersion", "scope", "export", "planHash", "reviewer", "coverage", "evidence", "review", "assessment"];
const KEYS: Record<1 | 2, string[]> = { 1: [...COMMON, "playback", "listening"],
  2: [...COMMON, "inspection", "submission", "approvedContent"] };
const MISSING: Record<ReviewAspect, string> = { picture: "whole-program picture approval",
  motion: "whole-program normal-speed motion playback", audio: "whole-program listening" };

/** The schema-2 record the typed submission writes. */
export interface NativeFinalReview {
  schemaVersion: 2; scope: typeof NATIVE_FINAL_REVIEW_SCOPE;
  export: { delivery: NativePrebuildReviewBinding; video: NativePrebuildReviewBinding };
  planHash: string; reviewer: ReturnType<typeof reviewIdentity>; coverage: ReturnType<typeof reviewCoverage>;
  evidence: NativePrebuildReviewBinding[]; review: ProducerReview; inspection: Inspection; submission: Submission;
  approvedContent: ApprovedContent; assessment: string;
}
interface Program { target: ReviewTarget; fps: number; evidence: NativePrebuildReviewBinding[] }

function binding(value: unknown, label: string): NativePrebuildReviewBinding {
  const row = objectValue(value, label);
  exactKeys(row, ["path", "sha256"], ["path", "sha256"], label);
  const file = stringValue(row.path, `${label} path`, 4096);
  if (!path.isAbsolute(file) || path.resolve(file) !== file) throw new Error(`${label} path must be canonical`);
  return { path: file, sha256: sha256(row.sha256, `${label} hash`) };
}

function flag(value: unknown, keys: [string, string], label: string): JsonRecord {
  const row = objectValue(value, label);
  exactKeys(row, keys, keys, label);
  if (typeof row[keys[0]] !== "boolean") throw new Error(`${label}.${keys[0]} must be true or false`);
  stringValue(row[keys[1]], `${label}.${keys[1]}`, 1000);
  return row;
}

/** The checked delivery, its unchanged MP4, and the plan digest and frame count of the project it rendered. */
export function checkedExport(delivery: NativePrebuildReviewBinding, video: NativePrebuildReviewBinding) {
  const observed = readCutPreviewObject(delivery.path), receipt = objectValue(observed.value, "delivery receipt");
  if (observed.sha256 !== delivery.sha256) throw new Error("Checked delivery receipt changed");
  if (receipt.status !== CHECKED || receipt.output !== video.path || receipt.sha256 !== video.sha256) {
    throw new Error("Final review must bind a native-short-checked-for-review delivery and its exact MP4");
  }
  if (observeLinkedMedia(video.path).sha256 !== video.sha256) throw new Error("Reviewed MP4 changed after review");
  const request = objectValue(readCutPreviewObject(path.join(path.dirname(delivery.path), "export-request.json")).value, "export request");
  const project = stringValue(request.project, "export project", 4096);
  const plan = readCutPreviewObject(path.join(project, "SHORT-PROJECT.json")).value as unknown as NativeShortProjectInput;
  const canvas = objectValue(plan.canvas, "rendered canvas"), clock = frameClock(canvas.frameRate, canvas.totalFrames);
  return { planHash: nativeShortPrebuildPlanHash(plan), totalFrames: clock.totalFrames, fps: clock.fps };
}

/** A later operator change the answered approval no longer reflects: the review stays verified as submitted, but it is
 * not a review of the approved content now in force. */
function superseded(asSubmitted: AsSubmitted | null): string[] {
  const later = asSubmitted?.supersededBy;
  return later ? [`a review of the current approved title and script (the approval this review answered was superseded `
    + `at ${later.elapsed.toFixed(1)} s of the batch clock)`] : [];
}

/** A typed record, read as submitted (read only; a closed batch's records still verify): editorial final only for a
 * pass approving every aspect over the whole exact MP4, with its answered packet, recorded submission and approved
 * content re-checked against the approval in force when it was submitted, and no later approval superseding it. */
function typedReading(row: JsonRecord, program: Program, verdict: string) {
  const inspection = readInspection(row.inspection, "final review inspection"), target = program.target;
  assertBoundToTargets(inspection, [target]);
  assertApprovals(inspection, [target], verdict);
  const { approvedContent, asSubmitted } = assertSubmission(row.submission, { role: "final-critic", evidence: program.evidence,
    inspection, targets: [target], fps: program.fps, reviewer: row.reviewer, verdict, approvedContent: row.approvedContent,
    subject: { video: { path: target.path, sha256: target.sha256 } }, record: row, asSubmitted: true });
  const missing = [...(verdict === "pass" ? REVIEW_ASPECTS.filter(aspect => !inspection.approves.includes(aspect))
    .map(aspect => MISSING[aspect]) : ["a passing verdict"]), ...superseded(asSubmitted)];
  const status = verdict !== "pass" ? `recorded-rendered-review-${verdict === "block" ? "blocked" : "requires-revision"}`
    : missing.length ? "recorded-independent-rendered-pass-not-final" : "recorded-independent-final-pass";
  return { status, inspection: typedEvidence(inspection, [target], reviewIdentity(row.reviewer)), approvedContent,
    approvalAsSubmitted: asSubmitted, editorialFinal: missing.length ? "not-established" : "approved", missing, declared: null };
}

/** A historical record: its playback/listening flags are untyped declarations and approve nothing further. */
function historicalReading(row: JsonRecord, verdict: string) {
  const playback = flag(row.playback, ["completed", "method"], "playback"), listening = flag(row.listening, ["performed", "notes"], "listening");
  if (verdict === "pass" && playback.completed !== true) throw new Error("A final pass needs completed full playback");
  return { status: `recorded-historical-rendered-review-untyped-${verdict}`, inspection: untypedEvidence(), approvedContent: null,
    approvalAsSubmitted: null, editorialFinal: "not-established",
    missing: ["typed inspection evidence (a historical record's playback and listening flags are untyped declarations)"],
    declared: { playbackCompleted: playback.completed as boolean, listeningPerformed: listening.performed as boolean } };
}

/** Validate a final review record and report what it establishes; it never authorizes publication. */
export function assertNativeFinalReview(file: string) {
  const observed = readCutPreviewObject(file), row = objectValue(observed.value, "native final review");
  const schema = row.schemaVersion === 2 ? 2 : 1;
  exactKeys(row, KEYS[schema], KEYS[schema], "native final review");
  if (row.schemaVersion !== schema || row.scope !== NATIVE_FINAL_REVIEW_SCOPE) throw new Error("Invalid native final review scope");
  const exported = objectValue(row.export, "final review export");
  exactKeys(exported, ["delivery", "video"], ["delivery", "video"], "final review export");
  const delivery = binding(exported.delivery, "final review delivery"), video = binding(exported.video, "final review video");
  const checked = checkedExport(delivery, video);
  if (checked.planHash !== sha256(row.planHash, "final review plan hash")) throw new Error("Final review plan hash is not the rendered project's");
  const reviewer = reviewIdentity(row.reviewer), review = validateProducerReview(row.review, "rendered");
  reviewCoverage(row.coverage); stringValue(row.assessment, "assessment", 4000);
  const evidence = reviewEvidence(row.evidence), target = { ...video, startFrame: 0, endFrameExclusive: checked.totalFrames };
  const reading = schema === 2 ? typedReading(row, { target, fps: checked.fps, evidence }, review.verdict)
    : historicalReading(row, review.verdict);
  return { status: reading.status, verdict: review.verdict, reviewer: reviewer.sessionId, video, inspection: reading.inspection,
    approvedContent: reading.approvedContent, approvalAsSubmitted: reading.approvalAsSubmitted,
    editorialFinal: reading.editorialFinal, missing: reading.missing,
    declared: reading.declared, humanApproved: false,
    independence: "reviewer-declared-not-authenticated", recordSha256: observed.sha256 };
}
