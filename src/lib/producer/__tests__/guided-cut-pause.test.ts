import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { createHash } from "node:crypto";
import { runAuthorStage } from "@/app/api/producer/auto-edit/authoring-stage";
import { runAutoEditPipeline } from "@/app/api/producer/auto-edit/pipeline";
import { autoEditJobStream } from "@/app/api/producer/auto-edit/job-stream";
import { settleWorkerExecution, withWorkerMutationLease } from "@/app/api/producer/auto-edit/worker-outcome";
import { assertCutApprovalRequestCurrent, parseCutApprovalRequest } from "@/app/api/producer/auto-edit/cut-approval-request";
import { verifyCutReviewApproval } from "@/app/api/producer/auto-edit/cut-review-approval";
import { validateCutReviewReceipt } from "@/app/api/producer/auto-edit/cut-review-receipt";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { pauseAutoEditForCutApproval } from "@/lib/server/auto-edit-cut-pause-store";
import {
  completeAutoEditJob, failAutoEditJob, heartbeatAutoEditJob, readAutoEditJob,
  recoverAutoEditJob, resumableAutoEditJob, startAutoEditJob,
} from "@/lib/server/auto-edit-job-store";
import { producerRun } from "@/lib/server/producer-run-registry";
import { acquireProjectMutationLease } from "@/lib/server/project-mutation-lease";
import { canResumeAutoEdit } from "@/lib/producer/project-state";
import { guidedFixture } from "./_guided-cut-fixture";

async function fixtureTask(run: (fixture: ReturnType<typeof guidedFixture>, root: string) => Promise<void>): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-guided-cut-"));
  try { await run(guidedFixture(root), root); }
  finally { rmSync(root, { recursive: true, force: true }); }
}

test("guided pipeline pauses only after actual cut gates and two clean independent reviews", async () => {
  await fixtureTask(async (fixture) => {
    const result = await runAutoEditPipeline(fixture.run, fixture.deps);
    assert.equal(result.status, "awaiting_cut_approval");
    assert.deepEqual(fixture.calls, { cutWriters: 1, visualWriters: 0, critics: 2, verifications: 1, locks: 1, planning: 0, renders: 0 });
    assert.equal(fixture.run.job.checkpoint, "cut_reviewed");
    assert.ok(!fixture.events.some((event) => ["outputs", "complete", "mp4_only_delivery_receipt"].includes(String(event.event))));
    if (result.status !== "awaiting_cut_approval") throw new Error("missing pause");
    assert.equal(assertCutApprovalRequestCurrent(fixture.run.job, result.request).requestHash, result.request.requestHash);
    assert.equal(result.request.planHash, fixture.run.job.planHash);
  });
});

test("a reusable reviewed cut pauses without repeating its writers, critics or deterministic gate", async () => {
  await fixtureTask(async (fixture) => {
    const first = await runAuthorStage(fixture.run, fixture.deps);
    if (first.status !== "awaiting_cut_approval") throw new Error("missing pause");
    const receiptPath = path.join(fixture.ctx.dir, ".sniper-cut-review-approved.json");
    const receipt = readFileSync(receiptPath);
    const second = await runAuthorStage(fixture.run, fixture.deps);
    if (second.status !== "awaiting_cut_approval") throw new Error("missing second pause");
    assert.deepEqual(fixture.calls, { cutWriters: 1, visualWriters: 0, critics: 2, verifications: 2, locks: 2, planning: 0, renders: 0 });
    assert.equal(first.request.planHash, second.request.planHash);
    assert.equal(first.request.pictureLockHash, second.request.pictureLockHash);
    assert.deepEqual(readFileSync(receiptPath), receipt, "request capture must not rewrite the review receipt");
  });
});

test("worker failure still stops heartbeat and releases the actual writer lease", async () => {
  await fixtureTask(async (fixture, root) => {
    let stopped = 0;
    await assert.rejects(withWorkerMutationLease(fixture.run.job, () => settleWorkerExecution({
      jobPath: fixture.jobPath, token: fixture.run.job.token,
      run: async () => { throw new Error("cut verification failed"); },
      send: fixture.run.io.send, stopHeartbeat: () => { stopped += 1; },
    })), /cut verification failed/);
    assert.equal(stopped, 1);
    assert.equal(readAutoEditJob(fixture.jobPath)?.cutApprovalRequest, undefined);
    assert.ok(!fixture.events.some((event) => event.event === "complete"));
    const lease = acquireProjectMutationLease(root, "test after failure");
    assert.ok(lease.lease);
    lease.lease.release();
  });
});

test("waiting state survives restart, stops heartbeat, releases lease and cannot Resume or complete", async () => {
  await fixtureTask(async (fixture, root) => {
    let stopped = 0;
    await withWorkerMutationLease(fixture.run.job, () => settleWorkerExecution({
      jobPath: fixture.jobPath, token: fixture.run.job.token,
      run: () => runAutoEditPipeline(fixture.run, fixture.deps),
      send: fixture.run.io.send, stopHeartbeat: () => { stopped += 1; },
    }));
    const waiting = readAutoEditJob(fixture.jobPath)!;
    assert.ok(stopped >= 1);
    assert.equal(waiting.status, "awaiting_cut_approval");
    assert.equal(waiting.error, undefined);
    assert.equal(waiting.workerPid, undefined);
    assert.equal(recoverAutoEditJob(fixture.jobPath)?.status, "awaiting_cut_approval");
    assert.equal(producerRun(fixture.ctx.dir)?.status, "awaiting_cut_approval");
    assert.equal(canResumeAutoEdit(producerRun(fixture.ctx.dir)), false);
    assert.equal(resumableAutoEditJob(fixture.ctx), null);
    for (const resume of [undefined, waiting]) assert.throws(() => startAutoEditJob({
      ctx: fixture.ctx, token: "cannot-accept", snapshots: 0, resume,
    }), /awaiting separate approval/);
    assert.throws(() => completeAutoEditJob(fixture.jobPath, waiting.token), /already awaiting_cut_approval/);
    assert.throws(() => failAutoEditJob(fixture.jobPath, waiting.token, "late failure"), /already awaiting_cut_approval/);
    assert.throws(() => heartbeatAutoEditJob(fixture.jobPath, waiting.token, "late"), /may not mutate/);
    const lease = acquireProjectMutationLease(root, "test after pause");
    assert.ok(lease.lease, "worker released its actual project mutation lease");
    lease.lease.release();
    const stream = await new Response(autoEditJobStream(fixture.jobPath, waiting.token)).text();
    assert.match(stream, /"event":"awaiting_cut_approval"/);
    assert.doesNotMatch(stream, /"event":"(?:outputs|complete|error)"/);
  });
});

test("request parser and current-artifact reobservation reject drift or missing evidence", async () => {
  await fixtureTask(async (fixture) => {
    const result = await runAuthorStage(fixture.run, fixture.deps);
    if (result.status !== "awaiting_cut_approval") throw new Error("missing pause");
    for (const patch of [{ createdAt: "2026-09-06" }, { requestHash: "0".repeat(64) }, { extra: true }]) {
      assert.throws(() => parseCutApprovalRequest({ ...result.request, ...patch }));
    }
    const paths = [fixture.ctx.planPath, fixture.ctx.manifestPath,
      path.join(fixture.ctx.transcriptsDir, "raw.transcript.json"),
      path.join(fixture.ctx.dir, ".sniper-cut-approval.json"),
      path.join(fixture.ctx.dir, ".sniper-cut-review-approved.json"),
      path.join(fixture.ctx.dir, "picture_locks", `${result.request.pictureLockHash}.json`),
      path.join(fixture.ctx.dir, "compatibility_projections", `${result.request.projectionReceiptHash}.json`)];
    for (const file of paths) {
      const bytes = readFileSync(file);
      writeFileSync(file, Buffer.concat([bytes, Buffer.from("\n")]));
      assert.throws(() => assertCutApprovalRequestCurrent(fixture.run.job, result.request), Error, file);
      writeFileSync(file, bytes);
    }
    const original = fixture.run.job.ctx.intent;
    fixture.run.job.ctx.intent = { ...original, music: true };
    assert.throws(() => assertCutApprovalRequestCurrent(fixture.run.job, result.request), /match this guided/);
    fixture.run.job.ctx.intent = original;
    const review = JSON.parse(readFileSync(paths[4], "utf8"));
    const critic = review.reviews[0].path;
    const bytes = readFileSync(critic);
    writeFileSync(critic, "{}");
    assert.throws(() => assertCutApprovalRequestCurrent(fixture.run.job, result.request), /hash changed/);
    writeFileSync(critic, bytes);
    rmSync(paths[5]);
    symlinkSync(paths[6], paths[5]);
    assert.throws(() => assertCutApprovalRequestCurrent(fixture.run.job, result.request), /unsafe/);
  });
});

test("failed independent cut checks never create a waiting request or visual plan", async () => {
  await fixtureTask(async (fixture) => {
    fixture.deps.reviewCut = async () => { throw new Error("independent review failed"); };
    await assert.rejects(runAutoEditPipeline(fixture.run, fixture.deps), /independent review failed/);
    assert.equal(readAutoEditJob(fixture.jobPath)?.cutApprovalRequest, undefined);
    assert.equal(fixture.calls.visualWriters, 0);
    assert.equal(fixture.calls.renders, 0);
  });
});

test("CAS review verification reuses bound bytes and cannot perform a legacy receipt upgrade", async () => {
  await fixtureTask(async (fixture) => {
    const result = await runAuthorStage(fixture.run, fixture.deps);
    if (result.status !== "awaiting_cut_approval") throw new Error("missing pause");
    const receiptPath = path.join(fixture.ctx.dir, ".sniper-cut-review-approved.json");
    const receipt = validateCutReviewReceipt(JSON.parse(readFileSync(receiptPath, "utf8")));
    const { cutAuthorityDigest: _authority, cutIntentDigest: _intent, ...legacy } = receipt;
    const legacyBytes = JSON.stringify(legacy);
    writeFileSync(receiptPath, legacyBytes);
    const lockPath = path.join(fixture.ctx.dir, "picture_locks", `${result.request.pictureLockHash}.json`);
    const lock = JSON.parse(readFileSync(lockPath, "utf8"));
    const evidence = { planHash: result.request.planHash, manifestHash: lock.manifestHash,
      transcriptDigest: lock.transcriptDigest, cutTrackDigest: lock.cutTrackDigest, cutDecisionsDigest: lock.cutDecisionsDigest };
    let reads = 0;
    const verified = verifyCutReviewApproval(fixture.ctx, evidence, {
      boundReceipt: receipt,
      readBoundArtifact: (_ctx, filePath, hash) => {
        reads += 1;
        const bytes = readFileSync(filePath);
        assert.equal(createHash("sha256").update(bytes).digest("hex"), hash);
        return JSON.parse(bytes.toString("utf8"));
      },
    });
    assert.equal(verified.cutAuthorityDigest, receipt.cutAuthorityDigest);
    assert.equal(reads, 2, "both independently bound critic artifacts must still be validated");
    assert.equal(readFileSync(receiptPath, "utf8"), legacyBytes, "CAS observation must not upgrade disk receipts");
    assert.throws(() => verifyCutReviewApproval(fixture.ctx, evidence, { boundReceipt: legacy as never }));
    assert.equal(readFileSync(receiptPath, "utf8"), legacyBytes);
    assert.throws(() => assertCutApprovalRequestCurrent(fixture.run.job, result.request), /hash changed/);
  });
});

test("unknown/autopilot and hybrid opt-ins cannot bypass guided gates", async () => {
  await fixtureTask(async (fixture) => {
    for (const policy of ["autopilot", "unknown"]) {
      const ctx = { ...fixture.ctx, workflowPolicy: policy } as never;
      await assert.rejects(runAutoEditPipeline({ ...fixture.run, job: { ...fixture.run.job, ctx } }, fixture.deps), /requires explicit/);
    }
    fixture.run.job.ctx.deliveryPolicy = "palmier-hybrid";
    await assert.rejects(runAutoEditPipeline(fixture.run, fixture.deps), /requires explicit/);
    assert.equal(fixture.calls.cutWriters, 0);
  });
});

test("malformed waiting journals fail closed and stale workers cannot replace the request", async () => {
  await fixtureTask(async (fixture) => {
    const result = await runAuthorStage(fixture.run, fixture.deps);
    if (result.status !== "awaiting_cut_approval") throw new Error("missing pause");
    const waiting = pauseAutoEditForCutApproval(fixture.jobPath, fixture.run.job.token, result.request);
    assert.equal(pauseAutoEditForCutApproval(fixture.jobPath, waiting.token, result.request).updatedAt, waiting.updatedAt);
    assert.throws(() => pauseAutoEditForCutApproval(fixture.jobPath, "stale", result.request), /token changed/);
    const before = readFileSync(fixture.jobPath);
    for (const patch of [{ cutApprovalRequest: undefined }, { checkpoint: "plan_authored" },
      { cutApprovalRequest: { ...result.request, requestHash: "0".repeat(64) } }]) {
      writeFileSync(fixture.jobPath, JSON.stringify({ ...waiting, ...patch }));
      assert.equal(readAutoEditJob(fixture.jobPath), null);
    }
    writeFileSync(fixture.jobPath, before);
    const changed = { ...result.request, createdAt: "2026-09-06T01:00:00.000Z" };
    const { requestHash: _hash, ...core } = changed;
    changed.requestHash = canonicalJsonSha256(core);
    assert.throws(() => pauseAutoEditForCutApproval(fixture.jobPath, waiting.token, changed), /only the current running worker/);
  });
});
