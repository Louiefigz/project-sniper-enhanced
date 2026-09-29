import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { journalHandoffEvent, stageTimingsPath, timedStage } from "../stage-timing";
import {
  STAGE_TIMING_LINEAGE_ENV, stageTimingContext, stageTimingEnv, stageTimingLineageEnv,
  withInheritedStageTimingLineage, withStageTimingChild, withStageTimingContext,
} from "../stage-timing-context";

// Exported SNIPER_TIMING_* from the caller's shell must not change these results.
for (const name of Object.values(STAGE_TIMING_LINEAGE_ENV)) delete process.env[name];

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
    await taskLineageAndHandoffs(dir);
    await timingNeverFailsWork(dir);
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

async function taskLineageAndHandoffs(dir: string) {
  const task = { runId: "run", attemptId: "attempt-3", attemptNo: 3, taskId: "clip-2-author", claimEpoch: 4, hostTurnId: "turn-7" };
  const badEpoch = withStageTimingContext({ ...task, claimEpoch: -1 }, () => stageTimingContext());
  assert.deepEqual([badEpoch.claimEpoch, badEpoch.taskId, badEpoch.lineageRejected], [undefined, "clip-2-author", ["claimEpoch"]]);
  const orphanTurn = withStageTimingContext({ runId: "run", attemptId: "a", attemptNo: 1, hostTurnId: "turn" }, () => stageTimingContext());
  assert.deepEqual([orphanTurn.hostTurnId, orphanTurn.lineageRejected], [undefined, ["hostTurnId"]]);
  const before = readRows(dir).length;
  await withStageTimingContext(task, () => timedStage(dir, "author_model", async () => {
    assert.deepEqual(journalHandoffEvent(dir, { stage: "clip_2", phase: "artifact-published" }),
      { recorded: false, reason: "handoff-missing-artifact" });
    assert.equal(journalHandoffEvent(dir, { stage: "clip_2", phase: "artifact-published", artifactSha256: "d".repeat(64) }).recorded, true);
    journalHandoffEvent(dir, { stage: "clip_2", phase: "consumer-accepted", artifactSha256: "d".repeat(64), consumerId: "assembly" });
  }, { activity: "model", phase: "author" }));
  assert.deepEqual(journalHandoffEvent(dir, { stage: "clip_2", phase: "ready" }), { recorded: false, reason: "handoff-missing-task" });
  assert.deepEqual(journalHandoffEvent(path.join(dir, "missing"), { stage: "", phase: "ready" }),
    { recorded: false, reason: "invalid-stage-label" });
  const rows = readRows(dir).slice(before);
  assert.deepEqual(rows.map((r) => r.event), ["start", "handoff", "handoff", "end"]);
  for (const row of rows) assert.deepEqual([row.taskId, row.claimEpoch, row.hostTurnId], ["clip-2-author", 4, "turn-7"]);
  assert.equal(rows[1].parentSpanId, rows[0].spanId);
  assert.deepEqual(rows[0].metadata, { phase: "author", activity: "model" });
  const report = spawnSync(path.resolve(".venv/bin/python3"), ["scripts/producer/stage_timing_report.py", stageTimingsPath(dir)], { encoding: "utf8" });
  assert.equal(report.status, 0, report.stderr);
  const summary = JSON.parse(report.stdout);
  assert.deepEqual(summary.handoffs.issues, []);
  assert.equal(summary.handoffs.publications[0].status, "accepted");
  assert.equal(summary.attribution.categories.modelExecution.status, "measured");
  assert.equal(summary.attribution.categories.publicationToAcceptance.status, "measured");
  assert.equal(summary.attribution.categories.hostSlotWaiting.unionSeconds, null, "absent attribution is unknown");
}

/** Partial or malformed lineage is named on the rows; the measured work always runs. */
async function timingNeverFailsWork(dir: string) {
  const start = readRows(dir).length;
  const measured = await timedStage(dir, "handoff_guard", async () => {
    assert.deepEqual(journalHandoffEvent(dir, { stage: "clip_3", phase: "consumer-accepted" }),
      { recorded: false, reason: "handoff-missing-task" });
    return 7; // the wrapped work continues after the refused handoff
  });
  assert.equal(measured, 7);
  assert.deepEqual(readRows(dir).slice(start).map((r) => [r.stage, r.event, r.status ?? null]),
    [["handoff_guard", "start", null], ["handoff_guard", "end", "completed"]]);
  const partial = { SNIPER_TIMING_RUN_ID: "run-p", SNIPER_TIMING_CLAIM_EPOCH: "3", SNIPER_TIMING_HOST_TURN_ID: "turn-3" };
  Object.assign(process.env, partial);
  try {
    const before = readRows(dir).length;
    const value = await withInheritedStageTimingLineage(() => timedStage(dir, "inherited_partial", async () =>
      withStageTimingContext({ ...stageTimingContext(), runId: "job-token" }, () => timedStage(dir, "job", async () => 42))));
    assert.equal(value, 42);
    const rows = readRows(dir).slice(before);
    assert.deepEqual(rows.map((r) => [r.stage, r.event, r.status ?? null]), [["inherited_partial", "start", null],
      ["job", "start", null], ["job", "end", "completed"], ["inherited_partial", "end", "completed"]]);
    assert.deepEqual([rows[0].runId, rows[0].claimEpoch, rows[0].hostTurnId, rows[0].lineageRejected],
      ["run-p", undefined, undefined, ["claimEpoch", "hostTurnId"]]);
    assert.equal(rows[1].runId, "job-token");
    assert.equal(rows[1].parentSpanId, rows[0].spanId);
  } finally { for (const name of Object.keys(partial)) delete process.env[name]; }
  const bad = withStageTimingContext({ runId: "bad id", attemptId: "x".repeat(300), attemptNo: 0, parentSpanId: "p q" },
    () => [stageTimingContext(), stageTimingLineageEnv()] as const);
  assert.ok(bad[0].runId.startsWith("standalone:"));
  assert.deepEqual(bad[0].lineageRejected, ["runId", "attemptId", "attemptNo", "parentSpanId"]);
  assert.deepEqual(Object.keys(bad[1]).sort(), ["SNIPER_TIMING_ATTEMPT_ID", "SNIPER_TIMING_ATTEMPT_NO", "SNIPER_TIMING_RUN_ID"]);
  assert.equal(bad[1].SNIPER_TIMING_ATTEMPT_NO, "1");
  // Nesting takes only a span id: the store keeps the validated context it already had.
  const nested = withStageTimingContext({ runId: "r", attemptId: "a", attemptNo: 2, taskId: "t" },
    () => [withStageTimingChild("span-1", () => stageTimingContext()), withStageTimingChild("bad id", () => stageTimingContext())]);
  assert.deepEqual(nested[0], { runId: "r", attemptId: "a", attemptNo: 2, taskId: "t", parentSpanId: "span-1" });
  assert.deepEqual(nested[1], { runId: "r", attemptId: "a", attemptNo: 2, taskId: "t" });
}

run().then(() => console.log("stage-timing-v2.test.ts: all assertions passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
