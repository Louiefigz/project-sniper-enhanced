import assert from "node:assert/strict";
import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { runAutoEditPipeline } from "@/app/api/producer/auto-edit/pipeline";
import { settleWorkerExecution, withWorkerMutationLease } from "@/app/api/producer/auto-edit/worker-outcome";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { parseCutPreviewPointer } from "@/lib/producer/contracts/cut-approval-request";
import { readAutoEditJob } from "@/lib/server/auto-edit-job-persistence";
import { pauseAutoEditForCutApproval } from "@/lib/server/auto-edit-cut-pause-store";
import { guidedFixture } from "./_guided-cut-fixture";

const POINTER = { executionKey: "1".repeat(64), receiptHash: "2".repeat(64) };
async function scoped(run: (fixture: ReturnType<typeof guidedFixture>) => Promise<void>) {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-guided-preview-boundary-")));
  try { await run(guidedFixture(root)); } finally { rmSync(root, { recursive: true, force: true }); }
}

test("preview pointers are closed identities, never arbitrary media paths", () => {
  assert.deepEqual(parseCutPreviewPointer(POINTER), POINTER);
  for (const value of [null, {}, { ...POINTER, path: "/tmp/final.mp4" },
    { ...POINTER, executionKey: "../media" }, { ...POINTER, receiptHash: "A".repeat(64) }]) {
    assert.throws(() => parseCutPreviewPointer(value));
  }
});

test("engine preview work finishes before the atomic user-wait event and pointer", async () => scoped(async (fixture) => {
  let signalStarted!: () => void, finishPreview!: () => void;
  const started = new Promise<void>((resolve) => { signalStarted = resolve; });
  const finished = new Promise<void>((resolve) => { finishPreview = resolve; });
  fixture.deps.prepareCutPreview = async () => { signalStarted(); await finished; return POINTER; };
  const work = settleWorkerExecution({ jobPath: fixture.jobPath, token: fixture.run.job.token,
    run: () => runAutoEditPipeline(fixture.run, fixture.deps), send: fixture.run.io.send, stopHeartbeat: () => {} });
  await started;
  const before = readAutoEditJob(fixture.jobPath)!;
  assert.equal(before.status, "running");
  assert.equal(before.cutApprovalRequest, undefined);
  assert.equal(before.cutPreview, undefined);
  assert.equal(fixture.calls.visualWriters, 0);
  finishPreview(); await work;
  const waiting = readAutoEditJob(fixture.jobPath)!;
  assert.equal(waiting.status, "awaiting_cut_approval");
  assert.deepEqual(waiting.cutPreview, POINTER);
  const event = waiting.events.find((row) => row.payload.event === "awaiting_cut_approval")!;
  assert.equal(event.at, waiting.updatedAt);
  assert.equal(event.payload.previewReceiptHash, POINTER.receiptHash);
  assert.ok(Date.parse(waiting.updatedAt) >= Date.parse(waiting.cutApprovalRequest!.createdAt));
  assert.equal(fixture.calls.visualWriters, 0); assert.equal(fixture.calls.renders, 0);
  assert.equal(pauseAutoEditForCutApproval(fixture.jobPath, waiting.token, waiting.cutApprovalRequest!, POINTER).updatedAt, waiting.updatedAt);
  assert.throws(() => pauseAutoEditForCutApproval(fixture.jobPath, waiting.token, waiting.cutApprovalRequest!,
    { ...POINTER, receiptHash: "3".repeat(64) }), /cannot be replaced/);
}));

test("failed, malformed or missing preview generation never starts user wait or visual authoring", async () => {
  for (const mode of ["failure", "malformed", "missing"] as const) await scoped(async (fixture) => {
    const dependencies = { ...fixture.deps, prepareCutPreview: mode === "missing" ? undefined : async () => {
      if (mode === "failure") throw new Error("full preview decode failed");
      return { ...POINTER, receiptHash: "invalid" };
    } };
    await assert.rejects(runAutoEditPipeline(fixture.run, dependencies), /preview/);
    const current = readAutoEditJob(fixture.jobPath)!;
    assert.equal(current.status, "running"); assert.equal(current.cutPreview, undefined);
    assert.equal(current.cutApprovalRequest, undefined);
    assert.equal(fixture.calls.visualWriters, 0); assert.equal(fixture.calls.renders, 0);
  });
});

test("worker closure receives the real held project lease, released after callback", async () => scoped(async (fixture) => {
  let guard!: () => void;
  await withWorkerMutationLease(fixture.run.job, async (lease) => {
    guard = cutPreviewLeaseGuard(fixture.ctx.dir, lease);
    assert.doesNotThrow(guard);
  });
  assert.throws(guard);
}));

test("worker settlement cannot create a new pointerless waiting checkpoint", async () => scoped(async (fixture) => {
  const result = await runAutoEditPipeline(fixture.run, fixture.deps);
  if (result.status !== "awaiting_cut_approval") throw new Error("missing test request");
  let stopped = 0;
  await assert.rejects(settleWorkerExecution({ jobPath: fixture.jobPath, token: fixture.run.job.token,
    run: async () => ({ status: "awaiting_cut_approval", request: result.request }),
    send: fixture.run.io.send, stopHeartbeat: () => { stopped += 1; } }), /pointer is missing/);
  assert.ok(stopped >= 1);
  assert.equal(readAutoEditJob(fixture.jobPath)?.status, "running");
  assert.equal(readAutoEditJob(fixture.jobPath)?.cutApprovalRequest, undefined);
}));
