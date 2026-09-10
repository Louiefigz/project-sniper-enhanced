import assert from "node:assert/strict";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  mintCompatibilityPictureLock,
  type CompatibilityPictureLockDependencies,
} from "../../../app/api/producer/auto-edit/compatibility-picture-lock";
import { compileCompatibilityProjection } from
  "../../../app/api/producer/auto-edit/compatibility-timeline-projection";
import { cutApprovalPath } from
  "../../../app/api/producer/auto-edit/cut-approval";
import {
  cutReviewApprovalPath,
  type CutReviewApprovalReceipt,
} from "../../../app/api/producer/auto-edit/cut-review-approval";
import type { PlanningGateVerdict } from
  "../../../app/api/producer/auto-edit/planning-gate-contract";
import type { AutoEditCtx } from
  "../../../app/api/producer/auto-edit/stream";
import { canonicalJsonSha256, fileSha256 } from "../../server/auto-edit-hash";
import type { AutoEditAuthoritySnapshot } from
  "../../server/auto-edit-authority-snapshot";
import { writeContentAddressedJsonSync } from "../../server/content-addressed-json";

const H = {
  transcript: "1".repeat(64),
  reviewAuthority: "2".repeat(64),
  cutAuthority: "3".repeat(64),
};

interface Fixture {
  ctx: AutoEditCtx;
  approval: Record<string, unknown>;
  review: CutReviewApprovalReceipt;
}

function plan(graphics = false): Record<string, unknown> {
  return {
    planVersion: 1,
    target: { mode: "longform", width: 1920, height: 1080, fps: 30 },
    cutTrack: [
      { sourceId: "raw", start: 0, end: 4, speed: 1 },
      { sourceId: "raw", start: 5, end: 9, speed: 1, audioLeadMs: 100 },
    ],
    cutDecisions: { schemaVersion: 1, removals: [] },
    ...(graphics ? {
      graphicsTrack: [{
        id: "card-1", kind: "statement-card", outStart: 1, outEnd: 2,
        spec: { text: "Visual-only copy" },
      }],
    } : {}),
  };
}

function fixture(root: string): Fixture {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(planPath, JSON.stringify(plan()));
  writeFileSync(manifestPath, JSON.stringify({ sources: [{ id: "raw" }] }));
  const ctx: AutoEditCtx = {
    dir, planPath, manifestPath, transcriptsDir: source, scope: "produced",
    intent: { mode: "longform", lanes: {} },
  };
  const value = JSON.parse(readFileSync(planPath, "utf8")) as Record<string, unknown>;
  const approval = {
    schemaVersion: 1, stage: "previsual",
    planHash: fileSha256(planPath)!,
    manifestHash: fileSha256(manifestPath)!,
    transcriptDigest: H.transcript,
    cutTrackDigest: canonicalJsonSha256(value.cutTrack),
    cutDecisionsDigest: canonicalJsonSha256(value.cutDecisions),
    cuts: 2, seams: [], removals: [],
  };
  writeFileSync(cutApprovalPath(ctx), JSON.stringify(approval));
  const review: CutReviewApprovalReceipt = {
    schemaVersion: 1, stage: "cut-review",
    requiredCleanReviews: 2, qualityPolicyVersion: 1,
    planHash: approval.planHash, manifestHash: approval.manifestHash,
    transcriptDigest: H.transcript, authorityDigest: H.reviewAuthority,
    cutTrackDigest: approval.cutTrackDigest,
    cutDecisionsDigest: approval.cutDecisionsDigest,
    doctrineHash: null, cutIntentDigest: "d".repeat(64),
    cutAuthorityDigest: H.cutAuthority,
    reviews: [
      { round: 1, path: path.join(dir, "review-1.json"), hash: "4".repeat(64) },
      { round: 2, path: path.join(dir, "review-2.json"), hash: "5".repeat(64) },
    ],
  };
  writeFileSync(cutReviewApprovalPath(ctx), JSON.stringify(review));
  return { ctx, approval, review };
}

function snapshot(ctx: AutoEditCtx, transcript = H.transcript): AutoEditAuthoritySnapshot {
  return {
    schemaVersion: 1, qualityPolicyVersion: 1,
    digest: "6".repeat(64),
    planHash: fileSha256(ctx.planPath) ?? null,
    planContentHash: "7".repeat(64),
    manifestHash: fileSha256(ctx.manifestPath) ?? null,
    operatorIntentDigest: "8".repeat(64),
    transcriptDigest: transcript,
    referenceDigest: "9".repeat(64),
    pipelineDigest: "a".repeat(64),
  };
}

function gate(item: Fixture): PlanningGateVerdict {
  return {
    gate: "transcript_cut", ok: true, errors: [], warnings: [], exit: 0,
    metrics: { receipt: {
      ...item.approval,
      stage: "planning_gate",
      planHash: fileSha256(item.ctx.planPath),
      approvalHash: fileSha256(cutApprovalPath(item.ctx)),
      approvedPrevisualPlanHash: item.approval.planHash,
    } },
  };
}

function deps(
  snapshotter: CompatibilityPictureLockDependencies["snapshot"] = snapshot,
): CompatibilityPictureLockDependencies {
  return {
    snapshot: snapshotter,
    compileProjection: compileCompatibilityProjection,
    writeJson: writeContentAddressedJsonSync,
  };
}

async function testStableAndVisualOnly(item: Fixture): Promise<void> {
  const first = await mintCompatibilityPictureLock(
    item.ctx, gate(item), item.review, deps(),
  );
  const second = await mintCompatibilityPictureLock(
    item.ctx, gate(item), item.review, deps(),
  );
  assert.equal(second.hash, first.hash);
  assert.equal(second.path, first.path);
  assert.equal(second.reused, true);
  assert.equal(fileSha256(first.path), first.hash);
  assert.equal(fileSha256(first.projectionPath), first.projectionHash);
  const projection = JSON.parse(readFileSync(first.projectionPath, "utf8"));
  assert.equal("projectionReceiptHash" in projection, false);
  const schema = JSON.parse(readFileSync(path.join(
    process.cwd(), "schemas", "producer", "compatibility-picture-lock-v1.schema.json",
  ), "utf8")) as {
    additionalProperties: boolean;
    required: string[];
    properties: Record<string, unknown>;
  };
  assert.equal(schema.additionalProperties, false);
  assert.deepEqual(Object.keys(first.lock).sort(), [...schema.required].sort());
  assert.deepEqual(Object.keys(first.lock).sort(), Object.keys(schema.properties).sort());

  const visualPlan = plan(true);
  visualPlan.target = {
    ...(visualPlan.target as Record<string, unknown>),
    graphicsStyle: "face-bridge",
    graphicsStyleRationale: "Evidence-dense visual treatment",
    visualProfile: "nateherk-editorial-v1",
  };
  writeFileSync(item.ctx.planPath, JSON.stringify(visualPlan));
  const visual = await mintCompatibilityPictureLock(
    item.ctx, gate(item), item.review, deps(),
  );
  assert.equal(visual.hash, first.hash, "visual-only lanes must preserve picture lock");
}

async function testDriftAndTampering(item: Fixture): Promise<void> {
  const baseline = await mintCompatibilityPictureLock(
    item.ctx, gate(item), item.review, deps(),
  );
  const originalPlan = readFileSync(item.ctx.planPath);
  writeFileSync(item.ctx.planPath, JSON.stringify({
    ...plan(), cutTrack: [{ sourceId: "raw", start: 0, end: 3, speed: 1 }],
  }));
  await assert.rejects(
    mintCompatibilityPictureLock(item.ctx, gate(item), item.review, deps()),
    /projection cut-track digest differs/,
  );
  writeFileSync(item.ctx.planPath, originalPlan);

  await assert.rejects(
    mintCompatibilityPictureLock(
      item.ctx, gate(item), item.review,
      deps((ctx) => snapshot(ctx, "b".repeat(64))),
    ),
    /transcript digest differs/,
  );
  const approvalPath = cutApprovalPath(item.ctx);
  const originalApproval = readFileSync(approvalPath);
  writeFileSync(approvalPath, Buffer.concat([originalApproval, Buffer.from("\n")]));
  const changedApproval = await mintCompatibilityPictureLock(
    item.ctx, gate(item), item.review, deps(),
  );
  assert.notEqual(changedApproval.hash, baseline.hash,
    "changing approved receipt bytes must invalidate the prior lock");
  writeFileSync(approvalPath, originalApproval);

  const reviewPath = cutReviewApprovalPath(item.ctx);
  const originalReview = readFileSync(reviewPath);
  writeFileSync(reviewPath, JSON.stringify({ ...item.review, authorityDigest: "c".repeat(64) }));
  await assert.rejects(
    mintCompatibilityPictureLock(item.ctx, gate(item), item.review, deps()),
    /review approval bytes/,
  );
  writeFileSync(reviewPath, originalReview);
}

async function testTargetIdentityAndNoClobber(item: Fixture): Promise<void> {
  const first = await mintCompatibilityPictureLock(
    item.ctx, gate(item), item.review, deps(),
  );
  const changed = plan();
  changed.target = { mode: "longform", width: 3840, height: 2160, fps: 30 };
  writeFileSync(item.ctx.planPath, JSON.stringify(changed));
  const targetLock = await mintCompatibilityPictureLock(
    item.ctx, gate(item), item.review, deps(),
  );
  assert.notEqual(targetLock.hash, first.hash);
  assert.notEqual(targetLock.lock.planContentHash, first.lock.planContentHash);

  writeFileSync(targetLock.path, "tampered");
  await assert.rejects(
    mintCompatibilityPictureLock(item.ctx, gate(item), item.review, deps()),
    /bytes conflict/,
  );
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-picture-lock-"));
  try {
    await testStableAndVisualOnly(fixture(path.join(root, "stable")));
    await testDriftAndTampering(fixture(path.join(root, "drift")));
    await testTargetIdentityAndNoClobber(fixture(path.join(root, "target")));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("compatibility-picture-lock.test.ts: all assertions passed");
}

void main();
