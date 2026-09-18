import assert from "node:assert/strict";
import { test } from "node:test";
import path from "node:path";
import { EventEmitter } from "node:events";
import type { ChildProcess } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync, renameSync } from "node:fs";
import { trackProcessTree } from "@/app/api/_lib/child-process-lifecycle";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { commitGuidedJob } from "../guided-cut-v2";
import { observeGuidedCutV2 } from "../guided-cut-v2-store";
import { parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { assertBootstrapCurrent } from "../guided-project-bootstrap-guard";
import { sealBootstrapPause, bootstrapPauseHash, assertBootstrapQuiescence } from "../guided-project-bootstrap-quiescence";
import { withBootstrapProcessScope, BootstrapCleanupError } from "../guided-project-bootstrap-observer";
import { bootstrapMayReleaseLease, bootstrapWorkerServices, runBootstrapWorker, bootstrapFailureCleanup } from "../guided-project-bootstrap-worker";
import { retainBootstrapFailure, BOOTSTRAP_FAILURE, BOOTSTRAP_UNKNOWN } from "../guided-project-bootstrap-store";
import { readGuidedProjectBootstrapStatus } from "../guided-project-bootstrap-status";
import { bootstrapFixture, bootstrapCutRequest, HASH } from "./_guided-project-bootstrap-fixture";

test("quiescence requires actual scope, exact fact and journal-held hash; legacy omission is unchanged", async (t) => {
  const f = bootstrapFixture(t), { job } = await f.start(), request = bootstrapCutRequest(job);
  const preview = { executionKey: HASH, receiptHash: HASH };
  await assert.rejects(sealBootstrapPause(job, request, preview), /scope/);
  await withBootstrapProcessScope(() => sealBootstrapPause(job, request, preview), () => assert.fail("late"));
  job.cutApprovalRequest = request; job.cutPreview = preview;
  assert.throws(() => assertBootstrapQuiescence(job), /journal-held/);
  job.bootstrapQuiescenceHash = bootstrapPauseHash(job, request, preview);
  assert.doesNotThrow(() => assertBootstrapQuiescence(job));
  const file = path.join(job.ctx.dir, "bootstrap-process-quiescence.json"), raw = readFileSync(file);
  writeFileSync(file, Buffer.concat([raw, Buffer.from("\n")]));
  assert.throws(() => assertBootstrapQuiescence(job), /journal-held/);
  const legacy = { ...job, ctx: { ...job.ctx, existingCutCandidate: undefined } };
  assert.doesNotThrow(() => assertBootstrapQuiescence(legacy));
});

test("durable late registration blocks ordinary strong pending reader and final journal CAS", async (t) => {
  const f = bootstrapFixture(t), { job, jobPath, dir } = await f.start(), request = bootstrapCutRequest(job);
  const preview = { executionKey: HASH, receiptHash: HASH };
  await withBootstrapProcessScope(() => sealBootstrapPause(job, request, preview), () => {});
  Object.assign(job, { cutApprovalRequest: request, cutPreview: preview,
    bootstrapQuiescenceHash: bootstrapPauseHash(job, request, preview), status: "awaiting_cut_approval",
    checkpoint: "cut_reviewed", cutApprovalWaitStartedAt: new Date().toISOString() });
  writeFileSync(jobPath, JSON.stringify(job)); parseAutoEditJobRecord(job);
  const before = readCutPreviewObject(jobPath); let guards = 0;
  assert.throws(() => commitGuidedJob({ job, beforeHash: before.sha256, guard: () => {
    guards++;
    if (guards === 2) retainBootstrapFailure(dir, "TEST late before final CAS", { verified: false, forcedStop: true });
  } }), /cleanup|failure/);
  assert.equal(guards, 2); assert.deepEqual(readFileSync(jobPath), before.bytes);
  assert.throws(() => observeGuidedCutV2(dir), /cleanup|failure/);
  const status = readGuidedProjectBootstrapStatus(dir);
  assert.equal(status.preview, null); assert.equal(status.cleanupUnknown, true);
});

test("current runtime context drift is rejected even though request identity deliberately excludes pins", async (t) => {
  const f = bootstrapFixture(t), { job, jobPath } = await f.start();
  job.ctx.doctrine = { runId: "TEST", doctrineHash: HASH, snapshotPath: path.join(f.root, "TEST-doctrine"), files: {} };
  const changed = structuredClone(job); changed.ctx.doctrine!.doctrineHash = "b".repeat(64);
  writeFileSync(jobPath, JSON.stringify(changed));
  assert.equal(parseAutoEditJobRecord(changed).requestKey, job.requestKey);
  assert.throws(() => assertBootstrapCurrent(job), /runtime context/);
});

test("clean failure cannot mask later unknown cleanup; immutable first evidence is preserved", async (t) => {
  const f = bootstrapFixture(t), { job, dir } = await f.start();
  retainBootstrapFailure(dir, "TEST clean", { verified: true, forcedStop: false });
  const file = path.join(path.dirname(dir), BOOTSTRAP_FAILURE), first = readFileSync(file);
  assert.equal(bootstrapMayReleaseLease(job), true);
  retainBootstrapFailure(dir, "TEST late", { verified: false, forcedStop: true });
  assert.deepEqual(readFileSync(file), first); assert.equal(bootstrapMayReleaseLease(job), false);
  assert.equal(readGuidedProjectBootstrapStatus(dir).cleanupUnknown, true);
});

test("generic post-child failure retains unknown, typed clean failure remains distinguishable", async (t) => {
  t.mock.method(process, "kill", () => { throw Object.assign(new Error("TEST absent"), { code: "ESRCH" }); });
  const child = Object.assign(new EventEmitter(), { pid: 91004 }) as ChildProcess;
  t.after(() => child.emit("close", 0));
  await assert.rejects(withBootstrapProcessScope(async () => {
    trackProcessTree(child); throw new Error("TEST gate converted forcedStop details");
  }, () => {}), (error: unknown) => error instanceof BootstrapCleanupError
    && error.observation.clean && bootstrapFailureCleanup(error).verified === false);
  const clean = new CutPreviewProcessError("TEST ordinary exit", { groupStopped: true, forcedStop: false,
    timedOut: false, stdout: "", stderr: "" }, 1);
  assert.equal(bootstrapFailureCleanup(clean).verified, true);
});

test("unknown failure persistence failure never turns missing disk marker into release permission", async (t) => {
  const f = bootstrapFixture(t), { job, dir } = await f.start();
  t.mock.method(bootstrapWorkerServices, "verifySources", async () => {});
  // A non-directory ancestor causes publication to fail before either marker can exist.
  const root = path.dirname(dir), moved = `${root}-held`;
  renameSync(root, moved); writeFileSync(root, "TEST publication failure");
  await assert.rejects(runBootstrapWorker(job, { release: () => {} }, async () => {
    throw new CutPreviewProcessError("TEST forced", { groupStopped: true, forcedStop: true, timedOut: true, stdout: "", stderr: "" });
  }));
  assert.equal(bootstrapMayReleaseLease(job), false);
  assert.equal(canonicalJsonSha256(f.request), job.ctx.existingCutCandidate!.requestHash);
});

test("malformed unknown marker and symlink-like nonfile markers are blocking, never cleanup success", async (t) => {
  const f = bootstrapFixture(t), { job, dir } = await f.start();
  mkdirSync(path.join(path.dirname(dir), BOOTSTRAP_UNKNOWN));
  assert.equal(bootstrapMayReleaseLease(job), false);
});
