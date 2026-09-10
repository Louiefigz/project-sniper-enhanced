import { createHash } from "node:crypto";
import {
  lstatSync,
  readFileSync,
} from "node:fs";
import path from "node:path";
import { canonicalJson } from "@/lib/server/auto-edit-hash";
import {
  autoEditAuthoritySnapshot,
  type AutoEditAuthoritySnapshot,
} from "@/lib/server/auto-edit-authority-snapshot";
import {
  writeContentAddressedJsonSync,
  type ContentAddressedJsonResult,
} from "@/lib/server/content-addressed-json";
import { cutApprovalPath } from "./cut-approval";
import {
  cutReviewApprovalPath,
  type CutReviewApprovalReceipt,
} from "./cut-review-approval";
import type { PlanningGateVerdict } from "./planning-gate-contract";
import {
  compileCompatibilityProjection,
  type CompatibilityTimelineProjectionV1,
} from "./compatibility-timeline-projection";
import { AutoEditError, type AutoEditCtx } from "./stream";
import { compatibilityPlanHash } from "./compatibility-picture-identity";

const SHA256 = /^[a-f0-9]{64}$/;
const ADAPTER_VERSION = 1;

interface ApprovedCutAuthority {
  planHash: string;
  manifestHash: string;
  transcriptDigest: string;
  cutTrackDigest: string;
  cutDecisionsDigest: string;
  approvalHash: string;
  approvedCutPlanHash: string;
}

export interface CompatibilityPictureLockV1 {
  schemaVersion: 1;
  kind: "compatibility-picture-lock";
  adapterVersion: 1;
  approvedCutPlanHash: string;
  planContentHash: string;
  manifestHash: string;
  transcriptDigest: string;
  cutTrackDigest: string;
  cutDecisionsDigest: string;
  cutApprovalReceiptHash: string;
  cutReviewApprovalReceiptHash: string;
  cutReviewAuthorityDigest: string;
  cutAuthorityDigest: string;
  projectionReceiptHash: string;
  timelineMapHash: string;
  qualityPolicyVersion: 1;
  requiredCleanReviews: 2;
}

export interface CompatibilityPictureLockResult {
  hash: string;
  path: string;
  reused: boolean;
  lock: CompatibilityPictureLockV1;
  projectionHash: string;
  projectionPath: string;
}

export interface CompatibilityPictureLockDependencies {
  snapshot: (ctx: AutoEditCtx) => AutoEditAuthoritySnapshot;
  compileProjection: (
    planBytes: Buffer,
    approvedCutPlanHash: string,
  ) => Promise<CompatibilityTimelineProjectionV1>;
  writeJson: (directory: string, value: unknown) => ContentAddressedJsonResult;
}

const DEFAULT_DEPS: CompatibilityPictureLockDependencies = {
  snapshot: autoEditAuthoritySnapshot,
  compileProjection: compileCompatibilityProjection,
  writeJson: writeContentAddressedJsonSync,
};

interface BoundJson {
  bytes: Buffer;
  hash: string;
  value: Record<string, unknown>;
}

function sha256(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function boundJson(filePath: string, label: string): BoundJson {
  let stat;
  try {
    stat = lstatSync(filePath);
  } catch {
    throw new AutoEditError(`${label} is missing`);
  }
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new AutoEditError(`${label} must be a regular non-symlink file`);
  }
  const bytes = readFileSync(filePath);
  try {
    const value = JSON.parse(bytes.toString("utf8")) as unknown;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return { bytes, hash: sha256(bytes), value: value as Record<string, unknown> };
    }
  } catch {
    // Use the closed error below for malformed and unreadable JSON alike.
  }
  throw new AutoEditError(`${label} is invalid JSON`);
}

function gateAuthority(verdict: PlanningGateVerdict): ApprovedCutAuthority {
  const value = verdict.metrics?.receipt as Record<string, unknown> | undefined;
  const mapping = {
    planHash: value?.planHash,
    manifestHash: value?.manifestHash,
    transcriptDigest: value?.transcriptDigest,
    cutTrackDigest: value?.cutTrackDigest,
    cutDecisionsDigest: value?.cutDecisionsDigest,
    approvalHash: value?.approvalHash,
    approvedCutPlanHash: value?.approvedPrevisualPlanHash,
  };
  const valid = verdict.gate === "transcript_cut" && verdict.ok
    && value?.stage === "planning_gate"
    && Object.values(mapping).every(
      (item) => typeof item === "string" && SHA256.test(item),
    );
  if (!valid) throw new AutoEditError("approved cut gate has no lockable authority receipt");
  return mapping as ApprovedCutAuthority;
}

function assertSame(label: string, values: unknown[]): void {
  if (values.some((value) => value !== values[0])) {
    throw new AutoEditError(`${label} differs across compatibility cut authorities`);
  }
}

function assertCurrent(
  authority: ApprovedCutAuthority,
  snapshot: AutoEditAuthoritySnapshot,
  planHash: string,
): void {
  assertSame("current plan hash", [authority.planHash, snapshot.planHash, planHash]);
  assertSame("manifest hash", [authority.manifestHash, snapshot.manifestHash]);
  assertSame("transcript digest", [
    authority.transcriptDigest, snapshot.transcriptDigest,
  ]);
}

function assertApproval(
  authority: ApprovedCutAuthority,
  approval: BoundJson,
): void {
  const value = approval.value;
  if (approval.hash !== authority.approvalHash
      || value.schemaVersion !== 1 || value.stage !== "previsual") {
    throw new AutoEditError("cut approval receipt bytes do not match approved gate authority");
  }
  assertSame("approved cut plan hash", [
    authority.approvedCutPlanHash, value.planHash,
  ]);
  for (const key of [
    "manifestHash", "transcriptDigest", "cutTrackDigest", "cutDecisionsDigest",
  ] as const) {
    assertSame(`cut approval ${key}`, [authority[key], value[key]]);
  }
}

function assertReview(
  authority: ApprovedCutAuthority,
  review: CutReviewApprovalReceipt,
  artifact: BoundJson,
): void {
  if (canonicalJson(artifact.value) !== canonicalJson(review)
      || review.schemaVersion !== 1 || review.stage !== "cut-review"
      || review.qualityPolicyVersion !== 1 || review.requiredCleanReviews !== 2
      || review.reviews.length !== 2) {
    throw new AutoEditError("cut review approval bytes do not match verified authority");
  }
  assertSame("reviewed cut plan hash", [
    authority.approvedCutPlanHash, review.planHash,
  ]);
  for (const key of [
    "manifestHash", "transcriptDigest", "cutTrackDigest", "cutDecisionsDigest",
  ] as const) {
    assertSame(`cut review ${key}`, [authority[key], review[key]]);
  }
  for (const digest of [review.authorityDigest, review.cutAuthorityDigest]) {
    if (!SHA256.test(digest)) {
      throw new AutoEditError("cut review approval contains a malformed authority digest");
    }
  }
}

function parsePlan(planArtifact: BoundJson): Record<string, unknown> {
  if (!Array.isArray(planArtifact.value.cutTrack)
      || !planArtifact.value.cutDecisions
      || typeof planArtifact.value.cutDecisions !== "object"
      || Array.isArray(planArtifact.value.cutDecisions)) {
    throw new AutoEditError("current edit plan has no compatibility cut authority");
  }
  return planArtifact.value;
}

interface BuildLockInput {
  authority: ApprovedCutAuthority;
  review: CutReviewApprovalReceipt;
  reviewHash: string;
  planContentHash: string;
  projection: CompatibilityTimelineProjectionV1;
  projectionHash: string;
}

function buildLock(input: BuildLockInput): CompatibilityPictureLockV1 {
  const { authority, review, reviewHash, planContentHash } = input;
  return {
    schemaVersion: 1,
    kind: "compatibility-picture-lock",
    adapterVersion: ADAPTER_VERSION,
    approvedCutPlanHash: authority.approvedCutPlanHash,
    planContentHash,
    manifestHash: authority.manifestHash,
    transcriptDigest: authority.transcriptDigest,
    cutTrackDigest: authority.cutTrackDigest,
    cutDecisionsDigest: authority.cutDecisionsDigest,
    cutApprovalReceiptHash: authority.approvalHash,
    cutReviewApprovalReceiptHash: reviewHash,
    cutReviewAuthorityDigest: review.authorityDigest,
    cutAuthorityDigest: review.cutAuthorityDigest,
    projectionReceiptHash: input.projectionHash,
    timelineMapHash: input.projection.timelineMapHash,
    qualityPolicyVersion: 1,
    requiredCleanReviews: 2,
  };
}

export async function mintCompatibilityPictureLock(
  ctx: AutoEditCtx,
  verdict: PlanningGateVerdict,
  review: CutReviewApprovalReceipt,
  deps: CompatibilityPictureLockDependencies = DEFAULT_DEPS,
): Promise<CompatibilityPictureLockResult> {
  const authority = gateAuthority(verdict);
  const planArtifact = boundJson(ctx.planPath, "current edit plan");
  const approval = boundJson(cutApprovalPath(ctx), "cut approval receipt");
  const reviewArtifact = boundJson(
    cutReviewApprovalPath(ctx), "cut review approval receipt",
  );
  assertCurrent(authority, deps.snapshot(ctx), planArtifact.hash);
  assertApproval(authority, approval);
  assertReview(authority, review, reviewArtifact);
  const plan = parsePlan(planArtifact);
  const projection = await deps.compileProjection(
    planArtifact.bytes, authority.approvedCutPlanHash,
  );
  assertSame("projection cut-track digest", [
    projection.cutTrackDigest, authority.cutTrackDigest,
  ]);
  assertSame("projection cut-decisions digest", [
    projection.cutDecisionsDigest, authority.cutDecisionsDigest,
  ]);
  const projectionObject = deps.writeJson(
    path.join(ctx.dir, "compatibility_projections"), projection,
  );
  const lock = buildLock({
    authority,
    review,
    reviewHash: reviewArtifact.hash,
    planContentHash: compatibilityPlanHash(
      plan, authority.cutTrackDigest, authority.cutDecisionsDigest,
    ),
    projection,
    projectionHash: projectionObject.hash,
  });
  const lockObject = deps.writeJson(path.join(ctx.dir, "picture_locks"), lock);
  return {
    hash: lockObject.hash,
    path: lockObject.path,
    reused: lockObject.reused,
    lock,
    projectionHash: projectionObject.hash,
    projectionPath: projectionObject.path,
  };
}
