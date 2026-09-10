import assert from "node:assert/strict";
import {
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { mintCompatibilityPictureLock } from
  "../../../app/api/producer/auto-edit/compatibility-picture-lock";
import {
  approvePrevisualCut,
  cutApprovalPath,
  cutAuthorityEvidence,
  verifyApprovedCut,
} from "../../../app/api/producer/auto-edit/cut-approval";
import {
  persistCutReviewApproval,
  verifyCutReviewApproval,
} from "../../../app/api/producer/auto-edit/cut-review-approval";
import type { AutoEditCtx } from
  "../../../app/api/producer/auto-edit/stream";
import {
  autoEditAuthoritySnapshot,
} from "../../server/auto-edit-authority-snapshot";
import { fileSha256 } from "../../server/auto-edit-hash";

function fixture(root: string): AutoEditCtx {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const transcriptPath = path.join(source, "raw.transcript.json");
  writeFileSync(transcriptPath, JSON.stringify({
    transcript: [{
      start: 0, end: 3.8, text: "This is a complete integration test sentence.",
      words: [
        { word: "This", start: 0, end: 0.5 },
        { word: "is", start: 0.5, end: 0.8 },
        { word: "a", start: 0.8, end: 1 },
        { word: "complete", start: 1, end: 1.7 },
        { word: "integration", start: 1.7, end: 2.5 },
        { word: "test", start: 2.5, end: 3 },
        { word: "sentence.", start: 3, end: 3.8 },
      ],
    }],
  }));
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(manifestPath, JSON.stringify({
    sources: [{
      id: "raw", duration: 3.8, transcriptPath: "raw.transcript.json",
    }],
  }));
  const planPath = path.join(dir, "edit_plan.json");
  writeFileSync(planPath, JSON.stringify({
    planVersion: 1, target: { mode: "longform" },
    cutTrack: [{
      sourceId: "raw", start: 0, end: 3.8, speed: 1,
      rationale: "Keep the complete sentence as the approved narrative spine.",
    }],
    cutDecisions: { schemaVersion: 1, removals: [] },
  }));
  return {
    dir, planPath, manifestPath, transcriptsDir: source, scope: "produced",
    intent: { mode: "longform", lanes: {} },
  };
}

async function runIntegration(ctx: AutoEditCtx): Promise<void> {
  const approval = await approvePrevisualCut(ctx);
  const authority = autoEditAuthoritySnapshot(ctx);
  const reviews = [1, 2].map((round) => {
    const reviewPath = path.join(ctx.dir, `real-review-${round}.json`);
    writeFileSync(reviewPath, JSON.stringify({
      schemaVersion: 1, stage: "cut", round,
      inputAuthority: { digest: authority.digest, planHash: authority.planHash },
      review: {
        schemaVersion: 1, stage: "cut", verdict: "pass",
        summary: "Cut is complete.", materialIssues: [], findings: [],
      },
    }));
    return { round, path: reviewPath, hash: fileSha256(reviewPath)! };
  });
  persistCutReviewApproval(ctx, approval, authority.digest, reviews);
  const verdict = await verifyApprovedCut(ctx);
  const review = verifyCutReviewApproval(ctx, cutAuthorityEvidence(verdict));
  const result = await mintCompatibilityPictureLock(ctx, verdict, review);
  assert.equal(fileSha256(result.path), result.hash);
  assert.equal(result.lock.cutApprovalReceiptHash, fileSha256(cutApprovalPath(ctx)));
  assert.equal(result.lock.cutReviewAuthorityDigest, authority.digest);
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-lock-integration-"));
  try {
    await runIntegration(fixture(root));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("compatibility-picture-lock-integration.test.ts: passed");
}

void main();
