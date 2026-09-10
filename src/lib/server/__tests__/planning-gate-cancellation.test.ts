import assert from "node:assert/strict";
import { test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { runPlanningGateBundle, type GateBundleInput, type PlanningGateRunner } from "@/app/api/producer/auto-edit/planning-gates";
import { spawnPlanningGate } from "@/app/api/producer/auto-edit/planning-gate-runner";
import { executeReadinessGates, readinessGatesClean, assertCurrentReadinessGateExecution,
  assertReadinessCleanupSettled } from "../readiness-gate-execution";
import { stubGateBundle } from "./_readiness-gate-stub";

const INPUT: GateBundleInput = { planPath: "/TEST/plan", manifestPath: "/TEST/manifest", transcriptsDir: "/TEST/transcripts",
  cutApprovalPath: "/TEST/cut", templateUsagePath: "/TEST/usage", templateUsageDigest: "a".repeat(64),
  operatorIntent: { mode: "longform", scope: "produced", lanes: { broll: "off" } } };
const success = () => ({ stdout: JSON.stringify({ ok: true, errors: [], warnings: [] }), stderr: "", exit: 0,
  processGroupStopped: true, forcedStop: false });
const liveTree = `import subprocess,sys,os,signal,time,json
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(10)'])
print(json.dumps({'parent':os.getpid(),'child':child.pid}),flush=True)
time.sleep(10)`;

function assertAbsent(pid: number): void {
  assert.throws(() => process.kill(pid, 0), (error: NodeJS.ErrnoException) => error.code === "ESRCH");
}

for (const cancelled of [false, true]) test(`actual planning ${cancelled ? "cancellation" : "timeout"} waits for owned parent and grandchild absence`, async () => {
  const controller = new AbortController(), began = performance.now();
  const timer = cancelled ? setTimeout(() => controller.abort(), 350) : undefined;
  try {
    const result = await spawnPlanningGate({ gate: "comp_size", script: "-c", args: [liveTree] },
      { timeoutMs: cancelled ? 3000 : 350, signal: controller.signal });
    assert.equal(result.exit, cancelled ? 130 : 124);
    assert.equal(result.processGroupStopped, true); assert.equal(result.forcedStop, true);
    assert.equal(result.timedOut, !cancelled);
    const pids = JSON.parse(result.stdout) as { parent: number; child: number };
    assertAbsent(pids.parent); assertAbsent(pids.child);
    assert.ok(performance.now() - began < 4000);
  } finally { clearTimeout(timer); }
});

test("pre-cancelled planning call never spawns; clean nonzero preserves complete JSON diagnostic and exit code", async () => {
  const controller = new AbortController(); controller.abort();
  const cancelled = await spawnPlanningGate({ gate: "comp_size", script: "/MUST/NOT/SPAWN", args: [] }, { signal: controller.signal });
  assert.equal(cancelled.exit, 130); assert.equal(cancelled.processGroupStopped, true); assert.equal(cancelled.forcedStop, false);
  const result = await spawnPlanningGate({ gate: "plan_lint", script: "-c",
    args: ["import json,sys; print(json.dumps({'ok':False,'errors':['x'*100000],'warnings':[]})); sys.exit(7)"] });
  assert.equal(result.exit, 7); assert.equal(result.spawnError, undefined); assert.equal(result.processGroupStopped, true);
  assert.equal(JSON.parse(result.stdout).errors[0].length, 100000);
});

test("unknown signal permission is not absence, and output overflow still proves owned child stopped", async (context) => {
  const realKill = process.kill.bind(process);
  const observer = context.mock.method(process, "kill", (pid: number, signal?: number | NodeJS.Signals) => {
    if (pid < 0 && signal === 0) throw Object.assign(new Error("TEST observation denied"), { code: "EPERM" });
    return realKill(pid, signal);
  });
  let pid = 0;
  try {
    const unknown = await spawnPlanningGate({ gate: "comp_size", script: "-c", args: ["import os; print(os.getpid())"] });
    pid = Number(unknown.stdout.trim()); assert.equal(unknown.processGroupStopped, false); assert.ok(unknown.spawnError);
  } finally { observer.mock.restore(); }
  assertAbsent(pid);
  const overflow = await spawnPlanningGate({ gate: "comp_size", script: "-c",
    args: ["import os,time; print(os.getpid(),flush=True); print('x'*3000000,flush=True); time.sleep(10)"] }, { timeoutMs: 2000 });
  assert.match(overflow.spawnError!, /output bound/); assert.equal(overflow.processGroupStopped, true);
  assert.ok(Buffer.byteLength(overflow.stdout) <= 2 * 1024 * 1024);
  assertAbsent(Number(overflow.stdout.split("\n")[0]));
});

test("thrown runner cancels siblings but bundle waits for their final stop observation", async () => {
  const order: string[] = [];
  const run: PlanningGateRunner = async (command, options) => {
    if (command.gate === "operator_intent") { await delay(15); order.push("throw"); throw new Error("TEST unknown process outcome"); }
    assert.equal(command.gate, "transcript_cut");
    await new Promise<void>((resolve) => options!.signal!.addEventListener("abort", () => resolve(), { once: true }));
    await delay(30); order.push("sibling-stopped"); return success();
  };
  const verdict = await runPlanningGateBundle(INPUT, { run }); order.push("bundle-returned");
  assert.deepEqual(order, ["throw", "sibling-stopped", "bundle-returned"]);
  assert.equal(verdict.ok, false); assert.equal(verdict.processesStopped, false);
});

test("preflight consumes the same decreasing budget and expired/cancelled waves never spawn downstream", async () => {
  const budgets: number[] = [];
  const run: PlanningGateRunner = async (_command, options) => { budgets.push(options!.timeoutMs!); await delay(40); return success(); };
  const verdict = await runPlanningGateBundle(INPUT, { run, timeoutMs: 1000 });
  assert.equal(verdict.ok, true); assert.equal(verdict.processesStopped, true);
  assert.equal(budgets.length, 8); assert.ok(Math.max(...budgets.slice(2)) <= Math.min(...budgets.slice(0, 2)) - 25);
  let calls = 0;
  const expired = await runPlanningGateBundle(INPUT, { timeoutMs: 20,
    run: async () => { calls += 1; await delay(40); return success(); } });
  assert.equal(calls, 2); assert.equal(expired.ok, false); assert.equal(expired.processesStopped, true);
  const controller = new AbortController(); controller.abort(); calls = 0;
  const cancelled = await runPlanningGateBundle(INPUT, { signal: controller.signal, run: async () => { calls += 1; return success(); } });
  assert.equal(calls, 0); assert.equal(cancelled.ok, false); assert.equal(cancelled.processesStopped, true);
});

test("cleanup finally runs after known stopped failure, never after unknown stop or unstructured exception", async () => {
  let reconciliations = 0;
  const renderer = { env: () => ({}), reconcile: () => { reconciliations += 1;
    return { containerNames: [], present: [], removed: [], verifiedAbsent: true, detail: "TEST absence only" }; } };
  const failed = stubGateBundle({ failures: { comp_size: ["TEST timed out after proved stop"] } });
  const result = await executeReadinessGates({ run: () => failed.run(INPUT), renderer });
  assert.equal(reconciliations, 1); assert.equal(result.cleanup, "verified-absence"); assert.equal(readinessGatesClean(result), false);
  for (const run of [async () => { throw new Error("TEST unknown child"); }, async () => ({ ...(await stubGateBundle().run(INPUT)), processesStopped: false })]) {
    const unknown = await executeReadinessGates({ run, renderer });
    assert.equal(unknown.cleanup, "not-run-process-stop-unknown"); assert.equal(readinessGatesClean(unknown), false);
    assert.throws(() => assertReadinessCleanupSettled(unknown), /cleanup is unverified/);
  }
  assert.equal(reconciliations, 1);
  const cleanupFailure = await executeReadinessGates({ run: () => stubGateBundle().run(INPUT),
    renderer: { ...renderer, reconcile: () => { throw new Error("TEST unreachable daemon"); } } });
  assert.equal(cleanupFailure.cleanup, "unverified-absence"); assert.match(cleanupFailure.error!, /unreachable daemon/);
  assert.equal(readinessGatesClean(cleanupFailure), false);
  assert.throws(() => assertReadinessCleanupSettled(cleanupFailure), /unreachable daemon/);
});

test("actual timed-out gate siblings are absent before configured reconciliation begins", async () => {
  const pids: number[] = [], sequence: string[] = [];
  const run: PlanningGateRunner = async (command, options) => {
    const result = await spawnPlanningGate({ ...command, script: "-c", args: [liveTree] }, options);
    const value = JSON.parse(result.stdout) as { parent: number; child: number };
    pids.push(value.parent, value.child); sequence.push("stopped"); return result;
  };
  const execution = await executeReadinessGates({ run: () => runPlanningGateBundle(INPUT, { run, timeoutMs: 350 }),
    renderer: { reconcile: () => {
      assert.equal(pids.length, 4); pids.forEach(assertAbsent); sequence.push("reconcile");
      return { containerNames: [], present: [], removed: [], verifiedAbsent: true, detail: "TEST exact-name adapter only" };
    } } });
  assert.deepEqual(sequence, ["stopped", "stopped", "reconcile"]);
  assert.equal(execution.verdict.ok, false); assert.equal(execution.verdict.processesStopped, true);
  assert.equal(execution.cleanup, "verified-absence"); assert.equal(readinessGatesClean(execution), false);
});

test("schema1 historical gate bundles cannot qualify current readiness; stopped metadata cannot disagree", async () => {
  const execution = await executeReadinessGates({ run: () => stubGateBundle().run(INPUT), renderer: null });
  const bundle = { schemaVersion: 2, ok: true, verdict: execution.verdict, renderer: null,
    cleanup: execution.cleanup, executionError: execution.error };
  assertCurrentReadinessGateExecution(bundle);
  assert.throws(() => assertCurrentReadinessGateExecution({ ...bundle, schemaVersion: 1 }), /predates owned-process stop proof/);
  assert.throws(() => assertCurrentReadinessGateExecution({ ...bundle, verdict: { ...bundle.verdict, processesStopped: false } }), /all owned gate groups/);
  assert.throws(() => assertCurrentReadinessGateExecution({ ...bundle, cleanup: "unverified-absence" }), /all owned gate groups/);
  const contradictory = structuredClone(bundle); contradictory.verdict.gates.compSize.processGroupStopped = false;
  assert.throws(() => assertCurrentReadinessGateExecution(contradictory), /all owned gate groups/);
});
