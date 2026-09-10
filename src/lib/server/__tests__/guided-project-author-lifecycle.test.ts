/** Actual metadata lifecycle boundaries; all provider/source-media work is explicitly stubbed. */
import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";
import { readFileSync, writeFileSync } from "node:fs";
import { settleWorkerExecution } from "@/app/api/producer/auto-edit/worker-outcome";
import { parseCutApprovalRequest } from "@/lib/producer/contracts/cut-approval-request";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { autoEditJobPath, parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { completeAutoEditJob, advanceAutoEditJob, invalidateAutoEditJob } from "../auto-edit-job-store";
import { bootstrapPauseHash, sealBootstrapPause, assertBootstrapQuiescence } from "../guided-project-bootstrap-quiescence";
import { withBootstrapProcessScope } from "../guided-project-bootstrap-observer";
import { runBootstrapWorker, bootstrapWorkerServices, bootstrapMayReleaseLease } from "../guided-project-bootstrap-worker";
import { retainBootstrapFailure } from "../guided-project-bootstrap-store";
import { authoredPreparationRuntime, AUTHORED_PREPARATION_LIMIT_MS } from "../guided-project-preparation-deadline";
import { authorFixture } from "./_guided-project-author-fixture";
import { HASH } from "./_guided-project-bootstrap-fixture";
import type { AutoEditJob } from "../auto-edit-job-types";

function requestFor(job: AutoEditJob) {
  const core = { schemaVersion: 1, requestKey: job.requestKey, planHash: job.ctx.authoredCut!.initialPlanSha256,
    authorityDigest: HASH, cutAuthorityDigest: HASH, cutApprovalReceiptHash: HASH, cutReviewApprovalReceiptHash: HASH,
    pictureLockHash: HASH, timelineMapHash: HASH, projectionReceiptHash: HASH, createdAt: new Date().toISOString() };
  return parseCutApprovalRequest({ ...core, requestHash: canonicalJsonSha256(core) });
}

test("authored PAUSE needs actual observed scope and sealed fact; human waiting does not restart or expire preparation", async t => {
  const f = authorFixture(t), { job } = await f.start(), request = requestFor(job);
  const preview = { executionKey: HASH, receiptHash: HASH };
  await assert.rejects(sealBootstrapPause(job, request, preview), /scope/);
  await withBootstrapProcessScope(() => sealBootstrapPause(job, request, preview), () => assert.fail("TEST unexpected late process"));
  job.cutApprovalRequest = request; job.cutPreview = preview;
  assert.throws(() => assertBootstrapQuiescence(job), /journal-held/);
  job.bootstrapQuiescenceHash = bootstrapPauseHash(job, request, preview);
  job.status = "awaiting_cut_approval"; job.checkpoint = "cut_reviewed";
  job.cutApprovalWaitStartedAt = new Date().toISOString();
  assert.doesNotThrow(() => parseAutoEditJobRecord(job));
  t.mock.method(authoredPreparationRuntime, "wall", () => Date.now() + AUTHORED_PREPARATION_LIMIT_MS + 60000);
  assert.doesNotThrow(() => assertBootstrapQuiescence(job));
  assert.throws(() => bootstrapPauseHash({ ...job, status: "running" }, request, preview), /expired/);
  retainBootstrapFailure(job.ctx.dir, "TEST late process after pause", { verified: false, forcedStop: true });
  assert.throws(() => assertBootstrapQuiescence(job), /cleanup/);
  assert.equal(bootstrapMayReleaseLease(job), false);
});

test("cold PAUSE rejects recorded times outside original preparation even if caller adopts a new hash", async t => {
  const f = authorFixture(t), { job } = await f.start(), request = requestFor(job), preview = { executionKey: HASH, receiptHash: HASH };
  await withBootstrapProcessScope(() => sealBootstrapPause(job, request, preview), () => {});
  job.status = "awaiting_cut_approval";
  const file = path.join(job.ctx.dir, "bootstrap-process-quiescence.json"), original = JSON.parse(readFileSync(file, "utf8"));
  const began = Date.parse(job.ctx.authoredCut!.preparationStartedAt);
  for (const recordedAt of [new Date(began - 1).toISOString(), new Date(began + AUTHORED_PREPARATION_LIMIT_MS).toISOString()]) {
    writeFileSync(file, JSON.stringify({ ...original, recordedAt }));
    assert.throws(() => bootstrapPauseHash(job, request, preview), /original preparation window/);
  }
});

test("authored worker verifies sources first, retains unknown failure, and never runs after expired preparation", async t => {
  const f = authorFixture(t), { job } = await f.start(), calls: string[] = [];
  t.mock.method(bootstrapWorkerServices, "verifySources", async () => { calls.push("sources"); });
  await runBootstrapWorker(job, { release: () => {} }, async () => { calls.push("writer"); });
  assert.deepEqual(calls, ["sources", "writer"]);
  t.mock.method(authoredPreparationRuntime, "wall", () => Date.now() + AUTHORED_PREPARATION_LIMIT_MS + 60000);
  await assert.rejects(runBootstrapWorker(job, { release: () => {} }, async () => { calls.push("forbidden"); }), /expired/);
  assert.deepEqual(calls, ["sources", "writer"]);
});

test("even a completed pipeline outcome cannot deliver an authored bootstrap or emit complete", async t => {
  const f = authorFixture(t), { job } = await f.start(), jobPath = autoEditJobPath(job.ctx.dir);
  const before = readFileSync(jobPath), events: unknown[] = []; let stopped = 0;
  await assert.rejects(settleWorkerExecution({ jobPath, token: job.token, run: async () => ({ status: "completed" }),
    send: event => { events.push(event); }, stopHeartbeat: () => { stopped++; } }), /cannot approve delivery/);
  assert.equal(stopped, 2); assert.deepEqual(events, []); assert.deepEqual(readFileSync(jobPath), before);
});

test("lower job mutators cannot bypass the cut-only worker completion refusal", async t => {
  const f = authorFixture(t), { job } = await f.start(), jobPath = autoEditJobPath(job.ctx.dir);
  const before = readFileSync(jobPath);
  assert.throws(() => completeAutoEditJob(jobPath, job.token), /cannot persist completion/);
  for (const mutate of [advanceAutoEditJob, invalidateAutoEditJob]) {
    assert.throws(() => mutate(jobPath, job.token, { checkpoint: "rendered", phase: "rendering", message: "TEST forbidden" }), /cannot persist/);
  }
  assert.deepEqual(readFileSync(jobPath), before);
});
