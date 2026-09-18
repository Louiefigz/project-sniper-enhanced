import assert from "node:assert/strict";
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test, { mock } from "node:test";
import { spawnPlanningGate } from "../../../app/api/producer/auto-edit/planning-gate-runner";
import { runAuditGate } from "../../../app/api/_lib/audit-gate";
import { timedStage, stageTimingsPath } from "../stage-timing";
import { withStageTimingContext } from "../stage-timing-context";

const producer = path.resolve("scripts/producer");
const probe = [
  "import sys, json",
  "sys.path.insert(0, sys.argv[1])",
  "from stage_timing import stage_span",
  "with stage_span(sys.argv[2], 'python_child'):",
  "    print(json.dumps({'status': 'done', 'overall': 'pass', 'passed': 1, 'warnings': 0, 'failed': 0}))",
  "    raise SystemExit(int(sys.argv[3]))",
].join("\n");

type Row = Record<string, unknown>;
function rows(dir: string): Row[] {
  return readFileSync(stageTimingsPath(dir), "utf8").trim().split("\n")
    .map((line) => JSON.parse(line) as Row);
}

function assertLineage(dir: string, name: string, attemptNo: number, exit: number): void {
  const found = rows(dir);
  const parent = found.find((row) => row.stage === name && row.event === "start")!;
  const child = found.find((row) => row.stage === "python_child" && row.event === "start")!;
  assert.equal(child.parentSpanId, parent.spanId);
  assert.equal(child.runId, `${name}-run`);
  assert.equal(child.attemptId, `${name}-attempt`);
  assert.equal(child.attemptNo, attemptNo);
  assert.notEqual(child.writerId, parent.writerId);
  assert.notEqual(child.writerPid, parent.writerPid);
  assert.equal(found.find((row) => row.spanId === child.spanId && row.event === "end")?.status,
    exit === 0 ? "completed" : "failed");
}

test("real concurrent planning children receive their own run, attempt and current parent", async () => {
  const directories = [0, 1].map(() => mkdtempSync(path.join(os.tmpdir(), "gate-lineage-")));
  const initial = { ...process.env };
  try {
    await Promise.all(directories.map(async (dir, index) => {
      const name = `gate-${index}`;
      const exit = index === 0 ? 0 : 7;
      const result = await withStageTimingContext({
        runId: `${name}-run`, attemptId: `${name}-attempt`, attemptNo: index + 2,
      }, () => timedStage(dir, name, () => spawnPlanningGate({
        gate: "plan_lint", script: "-c", args: [probe, producer, dir, String(exit)],
      })));
      assert.equal(result.exit, exit);
      assert.equal(result.spawnError, undefined);
      assertLineage(dir, name, index + 2, exit);
    }));
    assert.deepEqual({ ...process.env }, initial, "spawn context must never mutate ambient environment");
  } finally { for (const dir of directories) rmSync(dir, { recursive: true, force: true }); }
});

test("Audit B preserves timing identity and its existing PYTHONPATH without running a media audit", async () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), "audit-lineage-"));
  const initial = { ...process.env };
  const spawn = childProcess.spawn;
  const replacement: typeof childProcess.spawn = ((...args: Parameters<typeof childProcess.spawn>) => {
    const command = args[1] as string[];
    assert.equal(command[0], path.join(producer, "audit", "audit_render.py"));
    assert.equal(command[1], dir);
    const options = args[2] as childProcess.SpawnOptions;
    assert.equal(options.env?.SNIPER_TIMING_RUN_ID, "audit-run");
    assert.ok(String(options.env?.PYTHONPATH).startsWith(producer));
    return spawn(String(args[0]), ["-c", probe, producer, dir, "0"], options);
  }) as typeof childProcess.spawn;
  const stub = mock.method(childProcess, "spawn", replacement);
  syncBuiltinESMExports();
  try {
    const result = await withStageTimingContext({
      runId: "audit-run", attemptId: "audit-attempt", attemptNo: 3,
    }, () => timedStage(dir, "audit", () => runAuditGate(dir, 5_000)));
    assert.match(result.failure ?? "", /audit report evidence is missing from disk/);
    assert.equal(result.event.overall, "error", "timing success never substitutes for audit evidence");
    assert.equal(stub.mock.callCount(), 1);
    assertLineage(dir, "audit", 3, 0);
    assert.deepEqual({ ...process.env }, initial);
  } finally {
    stub.mock.restore();
    syncBuiltinESMExports();
    rmSync(dir, { recursive: true, force: true });
  }
});
