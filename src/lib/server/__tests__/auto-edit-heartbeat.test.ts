import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  AUTO_EDIT_BRAIN_HEARTBEAT_MS,
  brainHeartbeatMessage,
  brainHeartbeatTransition,
  createBrainHeartbeat,
  type BrainHeartbeatClock,
} from "../auto-edit-heartbeat";
import {
  autoEditJobPath,
  heartbeatAutoEditJob,
  readAutoEditJob,
  startAutoEditJob,
} from "../auto-edit-job-store";
import {
  beginProducerRunWithToken,
  heartbeatProducerRun,
} from "../producer-run-registry";

type Callback = () => void;

function fakeClock() {
  let now = 0;
  let next = 1;
  const callbacks = new Map<number, Callback>();
  const clock: BrainHeartbeatClock = {
    now: () => now,
    schedule(callback) {
      const handle = next++;
      callbacks.set(handle, callback);
      return handle as unknown as ReturnType<typeof setInterval>;
    },
    cancel(handle) {
      callbacks.delete(handle as unknown as number);
    },
  };
  return {
    clock,
    advance(ms: number) {
      now += ms;
      [...callbacks.values()].forEach((callback) => callback());
    },
    active: () => callbacks.size,
  };
}

assert.equal(
  brainHeartbeatMessage("Plan critic still reviewing", 0, 6 * 60_000 + 5_000),
  "Plan critic still reviewing · 6m elapsed",
);
assert.equal(
  brainHeartbeatMessage("Plan critic still reviewing", 0, 6 * 60_000 + 35_000),
  "Plan critic still reviewing · 6m 30s elapsed",
);
assert.equal(brainHeartbeatTransition({ event: "planning_review_started" }), "Plan critic still reviewing");
assert.equal(
  brainHeartbeatTransition({ event: "rendered_review_started", lens: "editorial" }),
  "Editorial critic still reviewing",
);
assert.equal(brainHeartbeatTransition({ event: "planning_review_completed" }), null);
assert.equal(brainHeartbeatTransition({ event: "unrelated" }), undefined);

const fake = fakeClock();
const writes: string[] = [];
const heartbeat = createBrainHeartbeat((message) => writes.push(message), fake.clock);
heartbeat.observe({ event: "planning_review_started" });
heartbeat.observe({ event: "planning_review_started" });
assert.equal(fake.active(), 1, "repeated events cannot create unbounded timers");
fake.advance(AUTO_EDIT_BRAIN_HEARTBEAT_MS);
assert.deepEqual(writes, ["Plan critic still reviewing · 30s elapsed"]);
fake.advance(5 * 60_000 + 30_000);
assert.equal(writes.at(-1), "Plan critic still reviewing · 6m elapsed");
heartbeat.observe({ event: "planning_review_completed" });
assert.equal(fake.active(), 0, "completion clears the interval");
fake.advance(AUTO_EDIT_BRAIN_HEARTBEAT_MS);
assert.equal(writes.length, 2, "cleared heartbeat cannot write more status");

heartbeat.observe({ event: "repair_started" });
assert.equal(fake.active(), 1);
heartbeat.stop();
assert.equal(fake.active(), 0, "worker error/finally can always clear the interval");

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-auto-edit-heartbeat-"));
try {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(manifestPath, '{"sources":[]}');
  const token = "heartbeat-test";
  const jobPath = autoEditJobPath(dir);
  startAutoEditJob({
    token,
    snapshots: 0,
    ctx: {
      dir,
      scope: "light",
      planPath: path.join(dir, "edit_plan.json"),
      manifestPath,
      transcriptsDir: source,
    },
  });
  beginProducerRunWithToken({
    dir, token, kind: "auto_edit", phase: "authoring", message: "started",
  });
  const eventCount = readAutoEditJob(jobPath)!.events.length;
  heartbeatAutoEditJob(jobPath, token, "Editor brain still authoring · 30s elapsed");
  heartbeatProducerRun(dir, token, "authoring", "Editor brain still authoring · 30s elapsed");
  const job = readAutoEditJob(jobPath)!;
  const run = JSON.parse(readFileSync(path.join(dir, ".sniper-run-state.json"), "utf8"));
  assert.equal(job.message, "Editor brain still authoring · 30s elapsed");
  assert.equal(job.events.length, eventCount, "durable heartbeat cannot grow job history");
  assert.equal(run.message, "Editor brain still authoring · 30s elapsed");
  assert.equal(run.events.length, 1, "durable heartbeat cannot grow run history");
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("auto-edit-heartbeat.test.ts: all assertions passed");
