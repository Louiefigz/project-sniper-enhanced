import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { autoEditAuthoritySnapshot } from "@/lib/server/auto-edit-authority-snapshot";
import { autoEditRequestKey, canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import type { AutoEditJob } from "@/lib/server/auto-edit-job-types";
import { cutApprovalPath } from "./cut-approval";
import { cutReviewApprovalPath, verifyCutReviewApproval } from "./cut-review-approval";
import { validateCutReviewReceipt } from "./cut-review-receipt";
import type { CompatibilityPictureLockResult, CompatibilityPictureLockV1 } from "./compatibility-picture-lock";
import { parseCompatibilityProjection } from "./compatibility-timeline-projection";
import { AutoEditError } from "./stream";
import { parseCutApprovalRequest, type CutApprovalRequestV1 } from "@/lib/producer/contracts/cut-approval-request";
export { parseCutApprovalRequest, type CutApprovalRequestV1, type CutApprovalPauseOutcome } from
  "@/lib/producer/contracts/cut-approval-request";

function artifactBytes(dir: string, filePath: string): Buffer {
  const stat = lstatSync(filePath);
  const parent = lstatSync(path.dirname(filePath));
  const realPath = realpathSync(filePath);
  const relative = path.relative(realpathSync(dir), realpathSync(filePath));
  if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1
      || !parent.isDirectory() || parent.isSymbolicLink() || stat.size > 16 * 1024 * 1024
      || !relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new AutoEditError("cut approval request artifact is missing, unsafe or changed");
  }
  const fd = openSync(filePath, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const opened = fstatSync(fd);
    if (opened.dev !== stat.dev || opened.ino !== stat.ino || opened.size !== stat.size || opened.nlink !== 1) {
      throw new AutoEditError("cut approval artifact changed during open");
    }
    const bytes = Buffer.alloc(opened.size);
    let offset = 0;
    while (offset < bytes.length) {
      const count = readSync(fd, bytes, offset, bytes.length - offset, offset);
      if (!count) throw new AutoEditError("cut approval artifact changed during read");
      offset += count;
    }
    const after = fstatSync(fd), current = lstatSync(filePath), currentParent = lstatSync(path.dirname(filePath));
    if (after.size !== opened.size || after.mtimeMs !== opened.mtimeMs || after.nlink !== 1
        || current.isSymbolicLink() || current.dev !== opened.dev || current.ino !== opened.ino
        || currentParent.isSymbolicLink() || currentParent.dev !== parent.dev || currentParent.ino !== parent.ino
        || realpathSync(filePath) !== realPath) throw new AutoEditError("cut approval artifact changed during read");
    return bytes;
  } finally { closeSync(fd); }
}

function boundObject(dir: string, filePath: string, expectedHash: string): Record<string, unknown> {
  const bytes = artifactBytes(dir, filePath);
  if (createHash("sha256").update(bytes).digest("hex") !== expectedHash) throw new AutoEditError("cut approval artifact hash changed");
  const row: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  if (!row || typeof row !== "object" || Array.isArray(row)) throw new AutoEditError("cut approval artifact is malformed");
  return row as Record<string, unknown>;
}

function lockEvidence(job: AutoEditJob, request: CutApprovalRequestV1): CompatibilityPictureLockV1 {
  const { ctx } = job;
  const lock = boundObject(ctx.dir, path.join(ctx.dir, "picture_locks", `${request.pictureLockHash}.json`),
    request.pictureLockHash) as unknown as CompatibilityPictureLockV1;
  if (lock.schemaVersion !== 1 || lock.kind !== "compatibility-picture-lock"
      || lock.adapterVersion !== 1 || lock.qualityPolicyVersion !== 1 || lock.requiredCleanReviews !== 2
      || lock.cutAuthorityDigest !== request.cutAuthorityDigest
      || lock.cutApprovalReceiptHash !== request.cutApprovalReceiptHash
      || lock.cutReviewApprovalReceiptHash !== request.cutReviewApprovalReceiptHash
      || lock.timelineMapHash !== request.timelineMapHash
      || lock.projectionReceiptHash !== request.projectionReceiptHash) {
    throw new AutoEditError("cut approval request differs from its verified picture lock");
  }
  const projection = boundObject(ctx.dir,
    path.join(ctx.dir, "compatibility_projections", `${request.projectionReceiptHash}.json`), request.projectionReceiptHash);
  const parsed = parseCompatibilityProjection(projection, lock.approvedCutPlanHash);
  if (parsed.timelineMapHash !== lock.timelineMapHash || parsed.cutTrackDigest !== lock.cutTrackDigest
      || parsed.cutDecisionsDigest !== lock.cutDecisionsDigest) throw new AutoEditError("cut approval projection changed");
  return lock;
}

/** Reobserve every immutable binding and independent review; never mint acceptance. */
export function assertCutApprovalRequestCurrent(job: AutoEditJob, value: unknown): CutApprovalRequestV1 {
  const request = parseCutApprovalRequest(value);
  if (job.ctx.workflowPolicy !== "cut-first" || job.ctx.deliveryPolicy !== "mp4-only"
      || job.requestKey !== request.requestKey || autoEditRequestKey(job.ctx) !== request.requestKey) {
    throw new AutoEditError("cut approval request does not match this guided MP4 job");
  }
  const authority = autoEditAuthoritySnapshot(job.ctx);
  if (authority.planHash !== request.planHash || authority.digest !== request.authorityDigest) {
    throw new AutoEditError("cut approval draft, intent, sources or pipeline authority changed");
  }
  const lock = lockEvidence(job, request);
  boundObject(job.ctx.dir, cutApprovalPath(job.ctx), request.cutApprovalReceiptHash);
  const boundReceipt = validateCutReviewReceipt(
    boundObject(job.ctx.dir, cutReviewApprovalPath(job.ctx), request.cutReviewApprovalReceiptHash));
  const plan = boundObject(job.ctx.dir, job.ctx.planPath, request.planHash);
  const evidence = {
    planHash: request.planHash, manifestHash: authority.manifestHash!, transcriptDigest: authority.transcriptDigest,
    cutTrackDigest: canonicalJsonSha256(plan.cutTrack ?? []),
    cutDecisionsDigest: canonicalJsonSha256(plan.cutDecisions ?? {}),
  };
  if (!authority.manifestHash || evidence.manifestHash !== lock.manifestHash
      || evidence.transcriptDigest !== lock.transcriptDigest
      || evidence.cutTrackDigest !== lock.cutTrackDigest || evidence.cutDecisionsDigest !== lock.cutDecisionsDigest) {
    throw new AutoEditError("cut approval request cut or transcript identity changed");
  }
  // Reuse the exact parsed receipt; this observation must never upgrade it.
  const review = verifyCutReviewApproval(job.ctx, evidence, {
    boundReceipt, readBoundArtifact: (ctx, filePath, hash) => boundObject(ctx.dir, filePath, hash),
  });
  if (review.cutAuthorityDigest !== request.cutAuthorityDigest || review.authorityDigest !== lock.cutReviewAuthorityDigest) {
    throw new AutoEditError("cut approval independent review authority changed");
  }
  return request;
}

/** Capture only after both cut walls returned their verified compatibility lock. */
export function buildCutApprovalRequest(
  job: AutoEditJob,
  verified: CompatibilityPictureLockResult,
  createdAt = new Date().toISOString(),
): CutApprovalRequestV1 {
  const authority = autoEditAuthoritySnapshot(job.ctx);
  const core = {
    schemaVersion: 1 as const, requestKey: job.requestKey, createdAt,
    planHash: authority.planHash, authorityDigest: authority.digest,
    cutAuthorityDigest: verified.lock.cutAuthorityDigest,
    cutApprovalReceiptHash: verified.lock.cutApprovalReceiptHash,
    cutReviewApprovalReceiptHash: verified.lock.cutReviewApprovalReceiptHash,
    pictureLockHash: verified.hash, timelineMapHash: verified.lock.timelineMapHash,
    projectionReceiptHash: verified.projectionHash,
  };
  return assertCutApprovalRequestCurrent(job, { ...core, requestHash: canonicalJsonSha256(core) });
}
