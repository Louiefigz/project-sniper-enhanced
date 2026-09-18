import assert from "node:assert/strict";
import type { ChildProcess, SpawnOptions } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { autoEditLogPath } from "../../server/auto-edit-log";
import { autoEditJobPath, readAutoEditJob, startAutoEditJob } from "../../server/auto-edit-job-store";
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
  const ctx: AutoEditCtx = { ...base, pipeline: {
    schemaVersion: 1, runId: "launch-token", digest: "a".repeat(64),
    snapshotRoot: "/snapshot/run/files", lockPath: "/snapshot/run/pipeline-lock.json", files: [],
  } };
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
    repoRoot: "/repo",
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
    "/repo/src/app/api/producer/auto-edit/worker.ts",
    autoEditJobPath(ctx.dir),
    "launch-token",
  ]);
  assert.equal(call.options.detached, true);
  assert.equal(call.options.env?.SNIPER_PIPELINE_ROOT, "/snapshot/run/files");
  assert.equal(call.options.env?.SNIPER_RUNTIME_REPO_ROOT, "/repo");
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
  const symlinkCtx = fixture(path.join(tmp, "log-symlink"));
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

async function main(): Promise<void> {
  const tmp = mkdtempSync(path.join(os.tmpdir(), "sniper-auto-edit-launcher-"));
  const capture: Capture = { unref: false };
  try {
    await testDetachedLaunch(tmp, capture);
    await testLogSymlink(tmp, capture);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

void main()
  .then(() => console.log("auto-edit-worker-launcher.test.ts: all assertions passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
