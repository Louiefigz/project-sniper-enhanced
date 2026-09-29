import assert from "node:assert/strict";
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test, { mock } from "node:test";
import { spawnPlanningGate } from "../../../app/api/producer/auto-edit/planning-gate-runner";
import { runAuditGate } from "../../../app/api/_lib/audit-gate";
import { timedStage, stageTimingsPath } from "../stage-timing";
import { STAGE_TIMING_LINEAGE_ENV, stageTimingLineageEnv, withStageTimingContext } from "../stage-timing-context";

// Exported SNIPER_TIMING_* from the caller's shell must not change these results.
for (const name of Object.values(STAGE_TIMING_LINEAGE_ENV)) delete process.env[name];

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

const LINEAGE = new Set<string>(Object.values(STAGE_TIMING_LINEAGE_ENV));
const MACOS_SELF_SET = "__CF_USER_TEXT_ENCODING"; // CoreFoundation sets it inside the child; never inherited
// Extensionless imports, as repository entry points use, so the child shares one context module.
const tsChild = (dir: string) => [
  `import { writeFileSync } from "node:fs";`,
  `import { timedStage } from ${JSON.stringify(path.resolve("src/lib/server/stage-timing"))};`,
  `import { withInheritedStageTimingLineage, withStageTimingFallback } from ${JSON.stringify(path.resolve("src/lib/server/stage-timing-context"))};`,
  `void withInheritedStageTimingLineage(() => withStageTimingFallback({ runId: "job-fallback", attemptId: "job", attemptNo: 1 }, () =>`,
  `  timedStage(${JSON.stringify(dir)}, "ts_child", async () => writeFileSync(${JSON.stringify(path.join(dir, "ts-env.json"))},`,
  `    JSON.stringify(Object.keys(process.env).sort())))));`,
].join("\n");
const pythonParent = [
  "import subprocess, sys",
  "sys.path.insert(0, sys.argv[1])",
  "from stage_timing import stage_span",
  "from stage_timing_context import task_scope",
  "from studio.native_run_config import launch_environment",
  "closed = {'PATH': '/usr/bin:/bin', 'TMPDIR': sys.argv[4]}",
  "with task_scope('ts-task', 5, 'turn-ts'), stage_span(sys.argv[2], 'py_parent'):",
  "    subprocess.run([sys.argv[5], '--import', 'tsx', sys.argv[3]], env=launch_environment(closed), check=True)",
].join("\n");

test("a closed Python launch reaches a TypeScript child with only allowlisted lineage, and the child links", () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), "py-ts-lineage-"));
  try {
    const child = path.join(dir, "child.ts");
    writeFileSync(child, tsChild(dir));
    const result = childProcess.spawnSync(path.resolve(".venv/bin/python3"),
      ["-c", pythonParent, producer, dir, child, os.tmpdir(), process.execPath],
      { encoding: "utf8", env: { ...process.env, SNIPER_TIMING_RUN_ID: "py-run", UNRELATED_API_KEY: "TEST-NOT-A-SECRET" } });
    assert.equal(result.status, 0, result.stderr);
    const names = (JSON.parse(readFileSync(path.join(dir, "ts-env.json"), "utf8")) as string[]).filter((name) => name !== MACOS_SELF_SET);
    assert.deepEqual(new Set(names), new Set(["PATH", "TMPDIR", ...LINEAGE]));
    assert.ok(!names.includes("UNRELATED_API_KEY"));
    const found = rows(dir);
    const parent = found.find((row) => row.stage === "py_parent" && row.event === "start")!;
    const tsRow = found.find((row) => row.stage === "ts_child" && row.event === "start")!;
    assert.equal(tsRow.parentSpanId, parent.spanId);
    assert.deepEqual([tsRow.runId, tsRow.attemptId, tsRow.taskId, tsRow.claimEpoch, tsRow.hostTurnId],
      ["py-run", parent.attemptId, "ts-task", 5, "turn-ts"], "the job fallback never replaces inherited lineage");
    assert.notEqual(tsRow.writerId, parent.writerId);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("a TypeScript parent hands a closed Python child only its lineage; malformed inherited values are named", async () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), "ts-py-lineage-"));
  const initial = { ...process.env };
  try {
    await withStageTimingContext({ runId: "ts-run", attemptId: "ts-attempt", attemptNo: 2, taskId: "py-task", claimEpoch: 0 },
      () => timedStage(dir, "ts_parent", async () => {
        const env = { PATH: "/usr/bin:/bin", ...stageTimingLineageEnv() };
        assert.deepEqual(new Set(Object.keys(env)), new Set(["PATH", "SNIPER_TIMING_RUN_ID", "SNIPER_TIMING_ATTEMPT_ID",
          "SNIPER_TIMING_ATTEMPT_NO", "SNIPER_TIMING_PARENT_SPAN_ID", "SNIPER_TIMING_TASK_ID", "SNIPER_TIMING_CLAIM_EPOCH"]));
        const script = "import sys; sys.path.insert(0, sys.argv[1]); from stage_timing import stage_span\n"
          + "with stage_span(sys.argv[2], 'python_child'): pass";
        for (const extra of [{}, { SNIPER_TIMING_HOST_TURN_ID: "bad turn" }] as Record<string, string>[]) {
          const closed: Record<string, string> = { ...env, ...extra }; // exactly these names, nothing inherited
          const result = childProcess.spawnSync(path.resolve(".venv/bin/python3"), ["-c", script, producer, dir], { env: closed as unknown as NodeJS.ProcessEnv, encoding: "utf8" });
          assert.equal(result.status, 0, result.stderr);
        }
      }));
    const found = rows(dir);
    const parent = found.find((row) => row.stage === "ts_parent" && row.event === "start")!;
    const children = found.filter((row) => row.stage === "python_child" && row.event === "start");
    for (const child of children) {
      assert.equal(child.parentSpanId, parent.spanId);
      assert.deepEqual([child.runId, child.attemptNo, child.taskId, child.claimEpoch], ["ts-run", 2, "py-task", 0]);
    }
    assert.equal(children[0].lineageRejected, undefined);
    assert.deepEqual(children[1].lineageRejected, ["hostTurnId"]);
    assert.equal(children[1].hostTurnId, undefined);
    assert.deepEqual({ ...process.env }, initial);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
