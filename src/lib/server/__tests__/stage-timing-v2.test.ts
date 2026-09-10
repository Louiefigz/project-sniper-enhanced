import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { stageTimingsPath, timedStage } from "../stage-timing";
import { stageTimingEnv, withStageTimingContext } from "../stage-timing-context";

type Row = Record<string, unknown>;
const readRows = (dir: string): Row[] => readFileSync(stageTimingsPath(dir), "utf8")
  .trim().split("\n").map((line) => JSON.parse(line) as Row);

async function concurrentSpans(dir: string) {
  let finishA!: () => void;
  let finishB!: () => void;
  const a = timedStage(dir, "critic_plan", () => new Promise<void>((r) => { finishA = r; }));
  const b = timedStage(dir, "critic_plan", () => new Promise<void>((r) => { finishB = r; }));
  finishA();
  await a;
  finishB();
  await b;
}

async function run() {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-timing-v2-"));
  const initialRunId = process.env.SNIPER_TIMING_RUN_ID;
  try {
    await withStageTimingContext({ runId: "run", attemptId: "attempt-1", attemptNo: 1 },
      () => timedStage(dir, "worker_run", async () => {
        await concurrentSpans(dir);
        await assert.rejects(() => timedStage(dir, "failed", async () => {
          throw new Error("error details must not enter telemetry");
        }));
        await timedStage(dir, "negative_verdict", async () => ({ ok: false }));
      }));
    const rows = readRows(dir);
    const root = rows.find((r) => r.stage === "worker_run" && r.event === "start")!;
    const critics = rows.filter((r) => r.stage === "critic_plan");
    assert.equal(new Set(critics.map((r) => r.spanId)).size, 2);
    assert.deepEqual(critics.map((r) => r.event), ["start", "start", "end", "end"]);
    assert.equal(critics[0].spanId, critics[2].spanId);
    assert.equal(critics[1].spanId, critics[3].spanId);
    assert.ok(critics.every((r) => r.parentSpanId === root.spanId));
    assert.ok(rows.every((r) => r.runId === "run" && r.attemptId === "attempt-1"));
    assert.equal(rows.find((r) => r.stage === "failed" && r.event === "end")?.status, "failed");
    assert.equal(rows.find((r) => r.stage === "negative_verdict" && r.event === "end")?.status,
      "completed");
    assert.ok(!JSON.stringify(rows).includes("error details"));
    assert.ok(rows.filter((r) => r.event === "end").every((r) => Number(r.elapsedMs) >= 0));
    await crossLanguageResume(dir);
    assert.equal(process.env.SNIPER_TIMING_RUN_ID, initialRunId);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

async function crossLanguageResume(dir: string) {
  await withStageTimingContext({ runId: "run", attemptId: "attempt-2", attemptNo: 2 },
    () => timedStage(dir, "resumed", async () => {
      const env = stageTimingEnv();
      const producer = path.resolve("scripts/producer");
      const result = spawnSync(path.resolve(".venv/bin/python3"), ["-c",
        "import sys; sys.path.insert(0, sys.argv[1]); from stage_timing import stage_span\n"
          + "with stage_span(sys.argv[2], 'python_child'): pass", producer, dir],
      { env, encoding: "utf8" });
      assert.equal(result.status, 0, result.stderr);
    }));
  const rows = readRows(dir);
  const parent = rows.find((r) => r.stage === "resumed" && r.event === "start")!;
  const child = rows.find((r) => r.stage === "python_child" && r.event === "start")!;
  assert.equal(child.parentSpanId, parent.spanId);
  assert.equal(child.runId, parent.runId);
  assert.equal(child.attemptId, "attempt-2");
  assert.equal(child.attemptNo, 2);
  assert.notEqual(child.writerId, parent.writerId);
}

run().then(() => console.log("stage-timing-v2.test.ts: all assertions passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
