import assert from "node:assert/strict";
import {
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { autoEditJobStream } from "../../../app/api/producer/auto-edit/job-stream";
import { legacyPlanHash } from "../../../app/api/producer/auto-edit/route";
import {
  appendAutoEditJobEvent,
  autoEditJobPath,
  completeAutoEditJob,
  failAutoEditJob,
  fileSha256,
  markAutoEditWorker,
  readAutoEditJob,
  recoverAutoEditJob,
  startAutoEditJob,
  StaleAutoEditWorkerError,
} from "../../server/auto-edit-job-store";
import { acquireAutoEditLaunchLease } from "../../server/auto-edit-launch-lock";
import {
  beginProducerRunWithToken,
  clearProducerRun,
  interruptProducerRun,
  producerRun,
} from "../../server/producer-run-registry";

function fixture(root: string): AutoEditCtx {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(manifestPath, '{"sources":[]}');
  return {
    dir,
    scope: "light",
    planPath: path.join(dir, "edit_plan.json"),
    manifestPath,
    transcriptsDir: source,
  };
}

async function streamText(stream: ReadableStream): Promise<string> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let out = "";
  for (;;) {
    const next = await reader.read();
    if (next.done) return out;
    out += decoder.decode(next.value, { stream: true });
  }
}

function testFencingAndSymlink(tmp: string): void {
  const ctx = fixture(path.join(tmp, "cas"));
  const first = startAutoEditJob({ ctx, token: "token-a", snapshots: 0 });
  assert.throws(
    () => startAutoEditJob({ ctx, token: "racing-fresh", snapshots: 0 }),
    /durable Auto Edit job is already running/,
  );
  failAutoEditJob(autoEditJobPath(ctx.dir), first.token, "interrupted");
  const resumable = readAutoEditJob(autoEditJobPath(ctx.dir))!;
  const second = startAutoEditJob({ ctx: { ...ctx }, token: "token-b", snapshots: 0, resume: resumable });
  assert.equal(second.token, "token-b");
  assert.equal(second.artifactToken, "token-a", "resume keeps one immutable QC evidence namespace");
  assert.throws(
    () => appendAutoEditJobEvent(autoEditJobPath(ctx.dir), "token-a", { event: "stale" }),
    StaleAutoEditWorkerError,
  );
  assert.equal(readAutoEditJob(autoEditJobPath(ctx.dir))?.token, "token-b", "stale commit cannot resurrect A");

  const raw = JSON.parse(readFileSync(autoEditJobPath(ctx.dir), "utf8"));
  raw.ctx.scope = "full";
  writeFileSync(autoEditJobPath(ctx.dir), JSON.stringify(raw));
  assert.equal(readAutoEditJob(autoEditJobPath(ctx.dir)), null, "requestKey authenticates persisted ctx");

  const symlinkCtx = fixture(path.join(tmp, "job-symlink"));
  const sentinel = path.join(tmp, "sentinel.txt");
  writeFileSync(sentinel, "do-not-touch");
  symlinkSync(sentinel, autoEditJobPath(symlinkCtx.dir));
  startAutoEditJob({ ctx: symlinkCtx, token: "safe-token", snapshots: 0 });
  assert.equal(readFileSync(sentinel, "utf8"), "do-not-touch");
  assert.equal(lstatSync(autoEditJobPath(symlinkCtx.dir)).isFile(), true);

  const failedCtx = fixture(path.join(tmp, "failed-group"));
  startAutoEditJob({ ctx: failedCtx, token: "failed-group", snapshots: 0 });
  markAutoEditWorker(autoEditJobPath(failedCtx.dir), "failed-group", process.pid);
  failAutoEditJob(autoEditJobPath(failedCtx.dir), "failed-group", "pipeline failed");
  assert.equal(readAutoEditJob(autoEditJobPath(failedCtx.dir))?.orphanedWorkerGroup, process.pid);
}

function testLegacyBootstrap(tmp: string): void {
  const legacyCtx = fixture(path.join(tmp, "legacy"));
  beginProducerRunWithToken({
    dir: legacyCtx.dir,
    kind: "auto_edit",
    phase: "authoring",
    message: "legacy run",
    token: "legacy-token",
  });
  writeFileSync(legacyCtx.planPath, '{"planVersion":1}');
  const future = new Date(Date.now() + 2_000);
  utimesSync(legacyCtx.planPath, future, future);
  interruptProducerRun(legacyCtx.dir, "legacy-token", "server stopped");
  assert.equal(legacyPlanHash(legacyCtx, null), fileSha256(legacyCtx.planPath));
  clearProducerRun(legacyCtx.dir);
  assert.equal(legacyPlanHash(legacyCtx, null), undefined, "a saved plan alone is not a resumable legacy run");
}

function testDurableWorkerIdentity(tmp: string): void {
  const reusedCtx = fixture(path.join(tmp, "pid-reuse"));
  startAutoEditJob({ ctx: reusedCtx, token: "pid-reuse", snapshots: 0 });
  const reusedPath = autoEditJobPath(reusedCtx.dir);
  markAutoEditWorker(reusedPath, "pid-reuse", process.pid);
  const reused = JSON.parse(readFileSync(reusedPath, "utf8"));
  reused.workerIdentity = { ...reused.workerIdentity, pid: process.pid + 1 };
  writeFileSync(reusedPath, JSON.stringify(reused));
  assert.equal(recoverAutoEditJob(reusedPath)?.status, "interrupted",
    "a live PID cannot impersonate a differently bound worker identity");

  const staleCtx = fixture(path.join(tmp, "stale-heartbeat"));
  startAutoEditJob({ ctx: staleCtx, token: "stale-heartbeat", snapshots: 0 });
  const stalePath = autoEditJobPath(staleCtx.dir);
  markAutoEditWorker(stalePath, "stale-heartbeat", process.pid);
  const stale = JSON.parse(readFileSync(stalePath, "utf8"));
  stale.updatedAt = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
  writeFileSync(stalePath, JSON.stringify(stale));
  assert.equal(recoverAutoEditJob(stalePath)?.status, "interrupted",
    "a live PID without a recent durable heartbeat must not run forever");
}

function testReadOnlyStatusProjection(tmp: string): void {
  const ctx = fixture(path.join(tmp, "read-only-status"));
  startAutoEditJob({ ctx, token: "read-only-status", snapshots: 0 });
  const jobPath = autoEditJobPath(ctx.dir);
  markAutoEditWorker(jobPath, "read-only-status", process.pid);
  const raw = JSON.parse(readFileSync(jobPath, "utf8"));
  raw.workerIdentity = { ...raw.workerIdentity, pid: process.pid + 1 };
  writeFileSync(jobPath, JSON.stringify(raw));
  assert.equal(producerRun(ctx.dir, { recover: false })?.status, "running",
    "idle cards project the journal without a synchronous identity probe");
  assert.equal(readAutoEditJob(jobPath)?.status, "running",
    "read-only projection must not recover or rewrite an unrelated job");
  assert.equal(producerRun(ctx.dir)?.status, "interrupted",
    "the active recovery path still fences a reused worker PID");
}

async function testCompletionAndStreams(tmp: string): Promise<void> {
  const completeCtx = fixture(path.join(tmp, "complete"));
  startAutoEditJob({ ctx: completeCtx, token: "complete-token", snapshots: 0 });
  appendAutoEditJobEvent(autoEditJobPath(completeCtx.dir), "complete-token", { event: "outputs" });
  for (let index = 0; index < 270; index += 1) {
    appendAutoEditJobEvent(autoEditJobPath(completeCtx.dir), "complete-token", { event: "log", index });
  }
  beginProducerRunWithToken({
    dir: completeCtx.dir,
    kind: "auto_edit",
    phase: "quality_check",
    message: "finishing",
    token: "complete-token",
  });
  completeAutoEditJob(autoEditJobPath(completeCtx.dir), "complete-token");
  assert.equal(producerRun(completeCtx.dir), null, "completed job journal clears stale run mirror");

  const late = await streamText(autoEditJobStream(autoEditJobPath(completeCtx.dir), "complete-token"));
  assert.match(late, /"event":"outputs"/, "ring eviction still synthesizes required outputs");
  assert.match(late, /"recovered":true/);

  const streamCtx = fixture(path.join(tmp, "stream-token"));
  const streamA = startAutoEditJob({ ctx: streamCtx, token: "stream-a", snapshots: 0 });
  failAutoEditJob(autoEditJobPath(streamCtx.dir), streamA.token, "retry");
  const failedA = readAutoEditJob(autoEditJobPath(streamCtx.dir))!;
  startAutoEditJob({ ctx: streamCtx, token: "stream-b", snapshots: 0, resume: failedA });
  const oldStream = await streamText(autoEditJobStream(autoEditJobPath(streamCtx.dir), "stream-a"));
  assert.match(oldStream, /superseded by a newer Resume request/);
}

function testLaunchLease(tmp: string): void {
  const leaseDir = fixture(path.join(tmp, "lease")).dir;
  const firstLease = acquireAutoEditLaunchLease(leaseDir);
  assert.ok(firstLease);
  assert.equal(acquireAutoEditLaunchLease(leaseDir), null, "atomic directory lease serializes launch");
  firstLease.release();
  const nextLease = acquireAutoEditLaunchLease(leaseDir);
  assert.ok(nextLease);
  nextLease.release();
  const emptyLeaseDir = fixture(path.join(tmp, "empty-lease")).dir;
  const emptyLease = path.join(emptyLeaseDir, ".sniper-auto-edit-launch.lock");
  mkdirSync(emptyLease);
  assert.equal(acquireAutoEditLaunchLease(emptyLeaseDir), null, "young empty lease is held, never reaped");
  rmSync(emptyLease, { recursive: true, force: true });
}

async function main(): Promise<void> {
  const tmp = mkdtempSync(path.join(os.tmpdir(), "sniper-auto-edit-store-"));
  try {
    testFencingAndSymlink(tmp);
    testLegacyBootstrap(tmp);
    testDurableWorkerIdentity(tmp);
    testReadOnlyStatusProjection(tmp);
    await testCompletionAndStreams(tmp);
    testLaunchLease(tmp);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

void main()
  .then(() => console.log("auto-edit-job-store.test.ts: all assertions passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
