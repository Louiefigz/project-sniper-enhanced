import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { autoEditQcApproval } from "../../../app/api/producer/palmier/_lib";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import {
  advanceAutoEditJob,
  autoEditJobPath,
  completeAutoEditJob,
  fileSha256,
  startAutoEditJob,
} from "../../server/auto-edit-job-store";
import {
  invalidateApprovedPreview,
  previewAuthorityInvalidated,
  promoteApprovedCandidate,
} from "../../server/auto-edit-quality-artifacts";
import { planContentHash } from "../../server/auto-edit-authority";
import { autoEditAuthoritySnapshot } from "../../server/auto-edit-authority-snapshot";
import { writeApprovalFixture } from "./auto-edit-approval-fixture";
import { markLegacyQualityPolicy } from "../../server/auto-edit-quality-policy";

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-palmier-qc-"));
try {
  const manual = path.join(root, "manual", "producer");
  mkdirSync(manual, { recursive: true });
  writeFileSync(path.join(root, "manual", "project.json"), JSON.stringify({
    origin: "raw", history: [],
    resolvedIntent: { mode: "longform", scope: "light", lanes: {} },
  }));
  markLegacyQualityPolicy(manual, "test fixture predates quality policy v1");
  assert.deepEqual(autoEditQcApproval(manual), {
    required: false, approved: true, reason: null,
  });
  writeFileSync(path.join(root, "manual", "project.json"), JSON.stringify({
    origin: "raw", history: [],
    resolvedIntent: { mode: "longform", scope: "produced", lanes: {} },
  }));
  writeFileSync(path.join(manual, "edit_plan.json"), JSON.stringify({
    target: { mode: "longform", scope: "produced", lanes: { graphics: "off" } },
  }));
  assert.equal(autoEditQcApproval(manual).approved, false,
    "legacy must not exempt produced/full work from governed delivery");
  writeFileSync(path.join(root, "manual", "project.json"), JSON.stringify({
    origin: "raw", history: [],
    resolvedIntent: { mode: "longform", scope: "light", lanes: {} },
  }));
  assert.equal(autoEditQcApproval(manual).approved, true);

  const project = path.join(root, "auto");
  const dir = path.join(project, "producer");
  const source = path.join(project, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "manifest.json");
  writeFileSync(planPath, '{"planVersion":1}');
  writeFileSync(manifestPath, '{"sources":[]}');
  const ctx: AutoEditCtx = {
    dir, scope: "light", planPath, manifestPath, transcriptsDir: source,
  };
  const token = "qc-approval";
  startAutoEditJob({ ctx, token, snapshots: 0, bootstrapPlanHash: fileSha256(planPath) });
  assert.equal(autoEditQcApproval(dir).approved, false);
  invalidateApprovedPreview(dir, "test-new-edit");
  assert.equal(previewAuthorityInvalidated(dir), true);

  const candidate = path.join(dir, ".sniper-qc", "candidate.mp4");
  mkdirSync(path.dirname(candidate), { recursive: true });
  writeFileSync(candidate, "approved-candidate");
  const finalHash = fileSha256(candidate)!;
  writeFileSync(`${candidate}.assembled.json`, JSON.stringify({
    planHash: planContentHash(planPath), authorityHash: finalHash,
  }));
  const authority = autoEditAuthoritySnapshot(ctx);
  promoteApprovedCandidate(candidate, dir, writeApprovalFixture({ ctx, token, candidate }));
  assert.equal(previewAuthorityInvalidated(dir), false,
    "only approved candidate promotion may restore durable preview authority");
  advanceAutoEditJob(autoEditJobPath(dir), token, {
    checkpoint: "quality_check", phase: "quality_check", message: "approved", finalHash,
    authorityDigest: authority.digest,
    reviewedAuthorityDigest: authority.digest,
    renderedAuthorityDigest: authority.digest,
    planningRound: 1,
    planningRoundsRequired: 1,
  });
  completeAutoEditJob(autoEditJobPath(dir), token);
  assert.equal(autoEditQcApproval(dir).approved, true);

  writeFileSync(planPath, '{"planVersion":2}');
  assert.equal(autoEditQcApproval(dir).approved, false);
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("palmier-qc-approval.test.ts: all assertions passed");
