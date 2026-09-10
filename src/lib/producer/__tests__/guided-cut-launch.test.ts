import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { guardPendingCutApproval, parseCutWorkflow, prepareRequest } from "@/app/api/producer/auto-edit/request";
import { startDetachedRun } from "@/app/api/producer/auto-edit/launch";
import { autoEditJobPath, readAutoEditJob, startAutoEditJob } from "@/lib/server/auto-edit-job-store";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import type { CutApprovalRequestV1 } from "../contracts/cut-approval-request";
import { fixture } from "./_auto-edit-pipeline-resume-fixture";

test("guided workflow is explicit, MP4-only and separate from saved-plan review", () => {
  assert.equal(parseCutWorkflow({}, "palmier-hybrid"), undefined);
  assert.equal(parseCutWorkflow({ workflowPolicy: "cut-first" }, "mp4-only"), "cut-first");
  for (const value of [null, false, "", "autopilot", "guided", []]) {
    assert.throws(() => parseCutWorkflow({ workflowPolicy: value }, "mp4-only"), /workflowPolicy/);
  }
  assert.throws(() => parseCutWorkflow({ workflowPolicy: "cut-first" }, "palmier-hybrid"), /mp4-only/);
  assert.throws(() => parseCutWorkflow({ workflowPolicy: "cut-first", reviewSavedPlan: true }, "mp4-only"), /separate actions/);
});

function pendingFixture(project: string) {
  const ctx = { ...fixture(project), workflowPolicy: "cut-first" as const, deliveryPolicy: "mp4-only" as const };
  const job = startAutoEditJob({ ctx, token: "launch-pause-fixture", snapshots: 0 });
  const hash = "a".repeat(64);
  const core = { schemaVersion: 1 as const, requestKey: job.requestKey,
    planHash: hash, authorityDigest: hash, cutAuthorityDigest: hash,
    cutApprovalReceiptHash: hash, cutReviewApprovalReceiptHash: hash,
    pictureLockHash: hash, timelineMapHash: hash, projectionReceiptHash: hash,
    createdAt: "2026-09-06T00:00:00.000Z" };
  const request: CutApprovalRequestV1 = { ...core, requestHash: canonicalJsonSha256(core) };
  writeFileSync(autoEditJobPath(ctx.dir), JSON.stringify({ ...job,
    status: "awaiting_cut_approval", checkpoint: "cut_reviewed", cutApprovalRequest: request }));
  writeFileSync(path.join(project, "project.json"), JSON.stringify({ origin: "raw", history: [] }));
  assert.equal(readAutoEditJob(autoEditJobPath(ctx.dir))?.status, "awaiting_cut_approval");
  // Parser-shape fixture only: not media, cut-approval or operator-acceptance evidence.
  return ctx;
}

test("pending or malformed journal rejects fresh, saved-plan and Resume before any prelaunch write", async () => {
  const workspace = mkdtempSync(path.join(os.tmpdir(), "guided-launch-"));
  const previous = process.env.SNIPER_WORKSPACE_ROOT;
  process.env.SNIPER_WORKSPACE_ROOT = workspace;
  try {
    const project = path.join(workspace, "test-project");
    const ctx = pendingFixture(project);
    const before = [autoEditJobPath(ctx.dir), ctx.planPath, path.join(project, "project.json")]
      .map((file) => ({ file, bytes: readFileSync(file) }));
    const files = readdirSync(ctx.dir).sort();
    for (const action of [{}, { resume: true }, { reviewSavedPlan: true }]) {
      assert.throws(() => prepareRequest({ dir: ctx.dir, ...action }), /waiting for cut approval/);
      await assert.rejects(startDetachedRun({ ctx, resume: false, ...action }), /waiting for cut approval/);
    }
    for (const item of before) assert.deepEqual(readFileSync(item.file), item.bytes);
    assert.deepEqual(readdirSync(ctx.dir).sort(), files, "no snapshot, doctrine, worker log or archive was created");
    writeFileSync(autoEditJobPath(ctx.dir), "{broken journal");
    assert.throws(() => guardPendingCutApproval(ctx.dir), /journal is invalid/);
    assert.throws(() => prepareRequest({ dir: ctx.dir }), /journal is invalid/);
    assert.equal(readFileSync(autoEditJobPath(ctx.dir), "utf8"), "{broken journal");
  } finally {
    if (previous === undefined) delete process.env.SNIPER_WORKSPACE_ROOT;
    else process.env.SNIPER_WORKSPACE_ROOT = previous;
    rmSync(workspace, { recursive: true, force: true });
  }
});
