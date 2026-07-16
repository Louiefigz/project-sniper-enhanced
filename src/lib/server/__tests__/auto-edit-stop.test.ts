import assert from "node:assert/strict";
import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import {
  advanceAutoEditJob,
  appendAutoEditJobEvent,
  autoEditJobPath,
  completeAutoEditJob,
  interruptAutoEditJob,
  markAutoEditWorker,
  readAutoEditJob,
  startAutoEditJob,
  StaleAutoEditWorkerError,
} from "../auto-edit-job-store";
import {
  AutoEditStopConflictError,
  AutoEditStopSignalError,
  stopAutoEdit,
  workerSignalTarget,
} from "../auto-edit-stop";
import {
  beginProducerRunWithToken,
  clearProducerRun,
  producerRun,
} from "../producer-run-registry";

const WORKER_PID = 424_242;

function fixture(root: string, name: string): AutoEditCtx {
  const project = path.join(root, name);
  const dir = path.join(project, "producer");
  mkdirSync(dir, { recursive: true });
  return {
    dir,
    scope: "light",
    planPath: path.join(dir, "edit_plan.json"),
    manifestPath: path.join(project, "source", "asset_manifest.json"),
    transcriptsDir: path.join(project, "source"),
  };
}

function runningJob(ctx: AutoEditCtx, token: string, withWorker = true) {
  const job = startAutoEditJob({ ctx, token, snapshots: 0 });
  if (withWorker) markAutoEditWorker(autoEditJobPath(ctx.dir), token, WORKER_PID);
  beginProducerRunWithToken({
    dir: ctx.dir,
    kind: "auto_edit",
    phase: "authoring",
    message: "running",
    token,
  });
  return job;
}

function testSignalTargets(): void {
  assert.equal(workerSignalTarget(123, "darwin"), -123);
  assert.equal(workerSignalTarget(123, "linux"), -123);
  assert.equal(workerSignalTarget(123, "win32"), 123);
  assert.throws(() => workerSignalTarget(0, "linux"), /positive integer/);
}

function testStopAndTerminalFence(root: string): void {
  const ctx = fixture(root, "normal-stop");
  runningJob(ctx, "current-token");
  const signals: Array<[number, NodeJS.Signals]> = [];
  const result = stopAutoEdit({ dir: ctx.dir, token: "current-token" }, {
    kill: (pid, signal) => { signals.push([pid, signal]); },
    groupAlive: () => false,
  });
  assert.deepEqual(signals, [[workerSignalTarget(WORKER_PID, process.platform), "SIGTERM"]]);
  assert.equal(result.status, "interrupted");
  assert.equal(result.checkpoint, "queued", "stop preserves the latest completed checkpoint");
  const saved = readAutoEditJob(autoEditJobPath(ctx.dir))!;
  assert.equal(saved.status, "interrupted");
  assert.equal(saved.orphanedWorkerGroup, WORKER_PID);
  assert.equal(saved.events.at(-1)?.payload.event, "stop_requested");
  assert.equal(producerRun(ctx.dir)?.status, "interrupted");
  assert.throws(() => appendAutoEditJobEvent(autoEditJobPath(ctx.dir), saved.token, { event: "late" }),
    StaleAutoEditWorkerError);
  assert.throws(() => advanceAutoEditJob(autoEditJobPath(ctx.dir), saved.token, {
    checkpoint: "authoring", phase: "authoring", message: "late advance",
  }), StaleAutoEditWorkerError);
  assert.throws(() => completeAutoEditJob(autoEditJobPath(ctx.dir), saved.token),
    StaleAutoEditWorkerError);
  clearProducerRun(ctx.dir);
}

function testAttemptAndProjectFences(root: string): void {
  const ctx = fixture(root, "token-fence");
  runningJob(ctx, "right-token");
  let kills = 0;
  assert.throws(() => stopAutoEdit({ dir: ctx.dir, token: "stale-token" }, {
    kill: () => { kills += 1; }, groupAlive: () => false,
  }), AutoEditStopConflictError);
  assert.equal(kills, 0);
  assert.equal(readAutoEditJob(autoEditJobPath(ctx.dir))?.status, "running");

  const other = fixture(root, "copied-journal");
  copyFileSync(autoEditJobPath(ctx.dir), autoEditJobPath(other.dir));
  assert.throws(() => stopAutoEdit({ dir: other.dir, token: "right-token" }, {
    kill: () => { kills += 1; }, groupAlive: () => false,
  }), /does not belong to this project/);
  assert.equal(kills, 0);
  interruptAutoEditJob(autoEditJobPath(ctx.dir), "right-token", "test cleanup", WORKER_PID);
  clearProducerRun(ctx.dir);
}

function testWorkerAndSignalFailures(root: string): void {
  const queued = fixture(root, "worker-not-ready");
  runningJob(queued, "queued-token", false);
  assert.throws(() => stopAutoEdit({ dir: queued.dir, token: "queued-token" }, {
    kill: () => {}, groupAlive: () => false,
  }), /has not started/);
  interruptAutoEditJob(autoEditJobPath(queued.dir), "queued-token", "test cleanup");
  clearProducerRun(queued.dir);

  const stuck = fixture(root, "signal-failure");
  runningJob(stuck, "stuck-token");
  assert.throws(() => stopAutoEdit({ dir: stuck.dir, token: "stuck-token" }, {
    kill: () => { throw new Error("EPERM"); }, groupAlive: () => true,
  }), AutoEditStopSignalError);
  assert.equal(readAutoEditJob(autoEditJobPath(stuck.dir))?.status, "interrupted");
  clearProducerRun(stuck.dir);
}

function testEscalatesSurvivingWorker(root: string): void {
  const ctx = fixture(root, "stop-escalation");
  runningJob(ctx, "escalate-token");
  const signals: Array<[number, NodeJS.Signals]> = [];
  let escalation: (() => void) | undefined;
  let delay = 0;
  let unrefCalled = false;
  stopAutoEdit({ dir: ctx.dir, token: "escalate-token" }, {
    kill: (pid, signal) => { signals.push([pid, signal]); },
    groupAlive: () => true,
    graceMs: 321,
    schedule: (callback, delayMs) => {
      escalation = callback;
      delay = delayMs;
      return { unref: () => { unrefCalled = true; } } as ReturnType<typeof setTimeout>;
    },
  });
  assert.equal(delay, 321);
  assert.equal(unrefCalled, true);
  assert.deepEqual(signals, [[workerSignalTarget(WORKER_PID, process.platform), "SIGTERM"]]);
  escalation?.();
  assert.deepEqual(signals, [
    [workerSignalTarget(WORKER_PID, process.platform), "SIGTERM"],
    [workerSignalTarget(WORKER_PID, process.platform), "SIGKILL"],
  ]);
  clearProducerRun(ctx.dir);
}

function main(): void {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-auto-edit-stop-"));
  try {
    testSignalTargets();
    testStopAndTerminalFence(root);
    testAttemptAndProjectFences(root);
    testWorkerAndSignalFailures(root);
    testEscalatesSurvivingWorker(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

main();
console.log("auto-edit-stop.test.ts: all assertions passed");
