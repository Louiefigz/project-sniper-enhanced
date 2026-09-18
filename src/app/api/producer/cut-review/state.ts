import path from "node:path";
import { autoEditJobPath, parseAutoEditJobRecord } from "@/lib/server/auto-edit-job-persistence";
import { parseCutPreviewPointer } from "@/lib/producer/contracts/cut-approval-request";
import { assertCutApprovalRequestCurrent } from "../auto-edit/cut-approval-request";
import { canonicalProducerDir } from "../auto-edit/request";
import { readCurrentCutPreview, readCutPreviewEvidence, readCutPreviewObject } from "../auto-edit/cut-preview-receipt";
import type { AutoEditJob } from "@/lib/server/auto-edit-job-types";

export class CutReviewError extends Error {
  constructor(message: string, public readonly status = 409) { super(message); }
}

/** Read-only and independently injectable for boundary tests; never approve or render. */
export const cutReviewReads = {
  canonical: canonicalProducerDir,
  object: readCutPreviewObject,
  request: assertCutApprovalRequestCurrent,
  preview: readCurrentCutPreview,
};

/** Mutable progress timestamps cannot turn verification time into operator wait. */
function reviewClock(job: AutoEditJob, created: { request: string; preview: string }) {
  const attempt = job.cutAcceptanceAttempt;
  const waitStartedAt = job.cutApprovalWaitStartedAt ?? job.updatedAt;
  const clock = [job.requestedAt, created.request, created.preview, waitStartedAt, job.updatedAt];
  if (clock.some((at) => typeof at !== "string" || !Number.isFinite(Date.parse(at)) || new Date(at).toISOString() !== at)
      || clock.some((at, index) => index > 0 && Date.parse(at) < Date.parse(clock[index - 1]))
      || Date.parse(job.updatedAt) > Date.now() + 60_000
      || (attempt && !job.cutApprovalWaitStartedAt)) {
    throw new CutReviewError("Cut review clocks are invalid or skewed; operator waiting time cannot be qualified");
  }
  if (attempt?.state === "verifying" && (attempt.receivedAt < waitStartedAt || attempt.startedAt > job.updatedAt)) {
    throw new CutReviewError("Cut verification clocks disagree with the paused job");
  }
  if (attempt?.state === "failed" && attempt.completedAt !== waitStartedAt) {
    throw new CutReviewError("Failed cut verification did not record a new operator waiting interval");
  }
  return { waitStartedAt, waitStoppedAt: attempt?.state === "verifying" ? attempt.receivedAt : null,
    acceptanceState: attempt?.state === "verifying" ? "verifying" as const
      : attempt?.state === "failed" ? "verification-failed" as const : "awaiting-decision" as const,
    acceptanceError: attempt?.state === "failed" ? attempt.error : null };
}

function observeCutReview(value: unknown, reads: typeof cutReviewReads) {
  const dir = reads.canonical(value);
  const journalPath = autoEditJobPath(dir);
  const observed = reads.object(journalPath);
  const job = parseAutoEditJobRecord(observed.value);
  if (job.ctx.dir !== dir || job.status !== "awaiting_cut_approval" || !job.cutApprovalRequest) {
    throw new CutReviewError("This project is not waiting for review of a cut preview");
  }
  if (!job.cutPreview) throw new CutReviewError("This earlier cut checkpoint has no qualified playable preview; it cannot be accepted");
  const request = reads.request(job, job.cutApprovalRequest);
  const pointer = parseCutPreviewPointer(job.cutPreview);
  const directory = path.join(dir, "cut-previews", request.requestHash, pointer.executionKey);
  const receipt = reads.preview(directory, request);
  const manifest = reads.object(job.ctx.manifestPath);
  const admission = manifest.value.sourceSetAdmission as Record<string, unknown> | undefined;
  if (receipt.receiptHash !== pointer.receiptHash || receipt.executionKey !== pointer.executionKey
      || receipt.runId !== (job.artifactToken ?? job.token) || receipt.attempt !== job.attempts
      || receipt.manifestHash !== manifest.sha256 || receipt.sourceSetDigest !== admission?.sourceSetDigest
      || receipt.sourceSetReceiptHash !== admission?.receiptSha256) {
    throw new CutReviewError("The playable cut does not match the paused job and admitted source set");
  }
  const clock = reviewClock(job, { request: request.createdAt, preview: receipt.createdAt });
  reads.request(job, request);
  if (reads.object(journalPath).sha256 !== observed.sha256) throw new CutReviewError("The cut checkpoint changed during review readback");
  return { dir, directory, job, request, receipt, clock };
}

/** Strong descriptor/acceptance observation: includes the entire media hash. */
export function currentCutReview(value: unknown, reads = cutReviewReads) {
  return { ...observeCutReview(value, reads), mediaBytesObserved: true as const };
}

export const cutReviewMediaReads = { ...cutReviewReads, evidence: readCutPreviewEvidence };

/** Metadata only. The media route MUST hash and stream its own single descriptor next. */
export function currentCutReviewForMedia(value: unknown, reads = cutReviewMediaReads) {
  const observed = observeCutReview(value, { ...reads,
    preview: (directory, request) => reads.evidence(directory, request).receipt });
  return { ...observed, mediaBytesObserved: false as const };
}

export type CurrentCutReview = ReturnType<typeof currentCutReview>;

/** Browser URLs carry exact identities, not a caller-chosen file path. */
export function cutReviewMediaUrl(review: CurrentCutReview): string {
  const query = new URLSearchParams({ dir: review.dir, requestHash: review.request.requestHash,
    executionKey: review.receipt.executionKey, receiptHash: review.receipt.receiptHash });
  return `/api/producer/cut-review/video?${query}`;
}

export function cutReviewDescription(review: CurrentCutReview) {
  const { job, request, receipt } = review;
  const [numerator, denominator] = receipt.profile.fps.split("/").map(Number);
  return { ok: true as const, state: "awaiting_cut_approval" as const,
    requestHash: request.requestHash, planHash: request.planHash, expectedToken: job.token,
    ...review.clock, previewStartedAt: receipt.createdAt,
    executionKey: receipt.executionKey, receiptHash: receipt.receiptHash,
    mediaSha256: receipt.media.sha256, mediaUrl: cutReviewMediaUrl(review),
    durationSeconds: receipt.media.videoFrames * denominator / numerator,
    width: receipt.profile.width, height: receipt.profile.height,
    scope: receipt.scope, accepted: false as const,
    caveat: "Cut-only preview at source aspect. Graphics, final crop, grade and mix are not represented. Review the story and audio edit; this is not an approved final." };
}
