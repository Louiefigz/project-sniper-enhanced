import assert from "node:assert/strict";
import type { ChildProcess, SpawnOptions } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  linkSync,
  rmSync,
  symlinkSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { autoEditLogPath } from "../../server/auto-edit-log";
import { autoEditJobPath, readAutoEditJob, startAutoEditJob } from "../../server/auto-edit-job-store";
import { captureAutoEditPipeline } from "../../server/auto-edit-pipeline-authority";
import {
  detachedWorkerInvocation,
  launchDetachedAutoEditWorker,
} from "../../server/auto-edit-worker-launcher";
import { beginProducerRunWithToken, clearProducerRun } from "../../server/producer-run-registry";

function fixture(root: string): AutoEditCtx {
  const dir = path.join(root, "producer");
  mkdirSync(dir, { recursive: true });
  return {
    dir,
    scope: "light",
    planPath: path.join(dir, "edit_plan.json"),
    manifestPath: path.join(root, "source", "asset_manifest.json"),
    transcriptsDir: path.join(root, "source"),
  };
}

interface Capture {
  call?: { command: string; args: readonly string[]; options: SpawnOptions };
  unref: boolean;
}

function fakeSpawner(capture: Capture) {
  return (command: string, args: readonly string[], options: SpawnOptions) => {
    capture.call = { command, args, options };
    return {
      pid: 424_242,
      unref: () => { capture.unref = true; },
    } as unknown as ChildProcess;
  };
}

async function testDetachedLaunch(tmp: string, capture: Capture): Promise<void> {
  const base = fixture(path.join(tmp, "launch"));
  const ctx: AutoEditCtx = {
    ...base,
    pipeline: captureAutoEditPipeline(base, "launch-token"),
  };
  const job = startAutoEditJob({ ctx, token: "launch-token", snapshots: 0 });
  beginProducerRunWithToken({
    dir: ctx.dir,
    kind: "auto_edit",
    phase: "authoring",
    message: "launching",
    token: job.token,
  });
  const fakeSpawn = fakeSpawner(capture);
  const pid = await launchDetachedAutoEditWorker(autoEditJobPath(ctx.dir), {
    repoRoot: process.cwd(),
    nodePath: "/node",
    spawnWorker: fakeSpawn,
  });
  const call = capture.call!;
  const stdio = call.options.stdio as unknown[];
  assert.equal(pid, 424_242);
  assert.equal(capture.unref, true);
  assert.equal(call.command, "/node");
  assert.deepEqual(call.args, [
    "--import",
    "tsx",
    path.join(process.cwd(), "src/app/api/producer/auto-edit/worker.ts"),
    autoEditJobPath(ctx.dir),
    "launch-token",
  ]);
  assert.equal(call.options.detached, true);
  assert.equal(call.options.env?.SNIPER_PIPELINE_ROOT, process.cwd());
  assert.equal(call.options.env?.SNIPER_RUNTIME_REPO_ROOT, process.cwd());
  assert.equal(stdio[0], "ignore");
  assert.equal(typeof stdio[1], "number");
  assert.equal(readAutoEditJob(autoEditJobPath(ctx.dir))?.workerPid, 424_242);
  assert.equal(readAutoEditJob(autoEditJobPath(ctx.dir))?.workerIdentity?.pid, 424_242);
  const runState = JSON.parse(readFileSync(path.join(ctx.dir, ".sniper-run-state.json"), "utf8"));
  assert.equal(runState.ownerPid, 424_242);
  assert.equal(runState.ownerIdentity.pid, 424_242);
  assert.equal(runState.ownerGroup, true);
  assert.match(readFileSync(autoEditLogPath(ctx.dir), "utf8"), /attempt \d+ started/);
  clearProducerRun(ctx.dir);

  const invocation = detachedWorkerInvocation("/tmp/job.json", "token", "/repo", "/node");
  assert.equal(invocation.cwd, "/repo");
  assert.equal(invocation.args.at(-1), "token");
}

async function testLogSymlink(tmp: string, capture: Capture): Promise<void> {
  const base = fixture(path.join(tmp, "log-symlink"));
  const symlinkCtx = {
    ...base,
    pipeline: captureAutoEditPipeline(base, "symlink-token"),
  };
  startAutoEditJob({ ctx: symlinkCtx, token: "symlink-token", snapshots: 0 });
  const sentinel = path.join(tmp, "log-sentinel.txt");
  writeFileSync(sentinel, "keep-me");
  symlinkSync(sentinel, autoEditLogPath(symlinkCtx.dir));
  await assert.rejects(
    launchDetachedAutoEditWorker(autoEditJobPath(symlinkCtx.dir), {
      repoRoot: "/repo",
      nodePath: "/node",
      spawnWorker: fakeSpawner(capture),
    }),
    /Refusing non-regular Auto Edit log/,
  );
  assert.equal(readFileSync(sentinel, "utf8"), "keep-me");
}

async function testUnlistedSnapshotModule(tmp: string): Promise<void> {
  const base = fixture(path.join(tmp, "extra-module"));
  const pipeline = captureAutoEditPipeline(base, "extra-module-token");
  const ctx: AutoEditCtx = { ...base, pipeline };
  const modulePath = path.join(pipeline.snapshotRoot, "scripts", "producer", "json.py");
  mkdirSync(path.dirname(modulePath), { recursive: true });
  writeFileSync(modulePath, "raise RuntimeError('must never execute')\n");
  startAutoEditJob({ ctx, token: "extra-module-token", snapshots: 0 });
  const capture: Capture = { unref: false };
  await assert.rejects(
    launchDetachedAutoEditWorker(autoEditJobPath(ctx.dir), {
      repoRoot: process.cwd(),
      nodePath: "/node",
      spawnWorker: fakeSpawner(capture),
    }),
    /unlisted file: scripts\/producer\/json\.py/,
  );
  assert.equal(capture.call, undefined);
}

async function testHardlinkedSnapshotFile(tmp: string): Promise<void> {
  const base = fixture(path.join(tmp, "hardlinked-file"));
  const pipeline = captureAutoEditPipeline(base, "hardlink-token");
  const ctx: AutoEditCtx = { ...base, pipeline };
  const relative = "scripts/producer/plan_lint.py";
  const captured = path.join(pipeline.snapshotRoot, ...relative.split("/"));
  const outside = path.join(tmp, "outside-plan-lint.py");
  writeFileSync(outside, readFileSync(captured));
  unlinkSync(captured);
  linkSync(outside, captured);
  startAutoEditJob({ ctx, token: "hardlink-token", snapshots: 0 });
  await assert.rejects(
    launchDetachedAutoEditWorker(autoEditJobPath(ctx.dir), {
      repoRoot: process.cwd(), nodePath: "/node",
      spawnWorker: fakeSpawner({ unref: false }),
    }),
    /hardlinked file: scripts\/producer\/plan_lint\.py/,
  );
}

function testBoundedJobJournal(tmp: string): void {
  const oversized = path.join(tmp, "oversized-job.json");
  writeFileSync(oversized, `{"padding":"${"x".repeat(8 * 1024 * 1024)}"}`);
  assert.equal(readAutoEditJob(oversized), null);
  const outside = path.join(tmp, "outside-job.json");
  const linked = path.join(tmp, "linked-job.json");
  writeFileSync(outside, "{}\n");
  linkSync(outside, linked);
  assert.equal(readAutoEditJob(linked), null);
}

async function main(): Promise<void> {
  const tmp = mkdtempSync(path.join(os.tmpdir(), "sniper-auto-edit-launcher-"));
  const capture: Capture = { unref: false };
  try {
    await testDetachedLaunch(tmp, capture);
    await testLogSymlink(tmp, capture);
    await testUnlistedSnapshotModule(tmp);
    await testHardlinkedSnapshotFile(tmp);
    testBoundedJobJournal(tmp);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

void main()
  .then(() => console.log("auto-edit-worker-launcher.test.ts: all assertions passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
