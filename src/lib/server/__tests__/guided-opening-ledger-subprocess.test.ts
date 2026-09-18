import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test, type TestContext } from "node:test";
import { createRequire } from "node:module";
import type { HeldOpeningClaim } from "../guided-opening-process";
import { liveRecordedDescendants, ownedProcessLedgerPath, readOwnedProcessLedger } from "../guided-opening-process-ledger";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";

// Actual venv + owned TS subprocess, no media, Docker, provider or approved output.
const require = createRequire(import.meta.url);
const runtimePath = require.resolve("../guided-opening-runtime-control");
const originalRuntime = require(runtimePath);
require.cache[runtimePath]!.exports = { ...originalRuntime, openingRuntimeEnvironment: () => ({}) };
const { invokeOpeningChild, openingPythonIdentity } = require("../guided-opening-process") as typeof import("../guided-opening-process");
require.cache[runtimePath]!.exports = originalRuntime;

async function smoke(_t: TestContext, body: string, timeoutMs = 10_000, cleanupAttemptId?: string) {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-ledger-subprocess-")));
  const producer = path.join(process.cwd(), "scripts/producer"), script = path.join(root, "worker.py");
  writeFileSync(script, `import os, sys\nsys.path.insert(0, ${JSON.stringify(producer)})\n${body}\n`);
  const tools = { ...openingPythonIdentity(), script, scriptHash: "a".repeat(64),
    runnerScript: path.join(producer, "headless/process_runner.py"), runnerScriptHash: "a".repeat(64) };
  const held = { claimPath: path.join(root, "execution-claim.json"), claimSha256: "a".repeat(64),
    claim: { runtime: {}, inputPath: path.join(root, "input.json"), outputRoot: path.join(root, "output"), inputSha256: "a".repeat(64) },
    job: { ctx: { pipeline: { snapshotRoot: process.cwd() } } } } as unknown as HeldOpeningClaim;
  const kind = cleanupAttemptId ? "cleanup" : "media";
  const ledgerRoot = cleanupAttemptId ? path.join(root, "cleanup-attempts", cleanupAttemptId) : root;
  if (cleanupAttemptId) mkdirSync(ledgerRoot, { recursive: true, mode: 0o700 });
  const deadline = performance.now() + timeoutMs;
  try {
    const result = await invokeOpeningChild({ held, tools, kind, cleanupAttemptId, remainingMs: () => Math.floor(deadline - performance.now()) });
    const file = ownedProcessLedgerPath(ledgerRoot, kind);
    return { result, rows: readOwnedProcessLedger(ledgerRoot, kind), bytes: readFileSync(file),
      observed: liveRecordedDescendants(ledgerRoot, kind) };
  } finally { rmSync(root, { recursive: true, force: true }); }
}

test("actual owned worker with zero detached helpers records a complete lifecycle", async (t) => {
  const run = await smoke(t, "print(os.environ['SNIPER_OWNED_PROCESS_LEDGER'])");
  assert.match(run.result.stdout, /owned-process-ledger\.media\.jsonl/);
  assert.deepEqual(run.rows.map((row) => row.event), ["worker-started", "worker-finished"]);
  assert.deepEqual(run.observed, { live: [], unknown: [], unrecordedSpawns: [] });
});

test("actual additive cleanup wrapper records its lifecycle inside the exact private attempt", async t => {
  const id = "00000000-0000-4000-8000-000000000001";
  const run = await smoke(t, "print(os.environ['SNIPER_OWNED_PROCESS_LEDGER'])", 10_000, id);
  assert(run.result.stdout.trim().endsWith(`/cleanup-attempts/${id}/owned-process-ledger.cleanup.jsonl`));
  assert.deepEqual(run.rows.map(row => row.event), ["worker-started", "worker-finished"]);
  assert.deepEqual(run.observed, { live: [], unknown: [], unrecordedSpawns: [] });
});

test("actual cleanup abrupt zero-exit is not a complete attempt lifecycle", async t => {
  await assert.rejects(smoke(t, "os._exit(0)", 10_000, "00000000-0000-4000-8000-000000000002"), /lifecycle is missing, incomplete/);
});

test("actual owned worker propagates ledger into the detached helper lifecycle", async (t) => {
  const run = await smoke(t, `from headless.process_runner import ProcessRequest, run_text
r = run_text(ProcessRequest((sys.executable, '-c', "print('nested-ok')"), '', os.getcwd(), {}, 3))
print(r.stdout, end='')`);
  assert.equal(run.result.stdout, "nested-ok\n");
  assert.deepEqual(run.rows.map((row) => row.event), ["worker-started", "intent", "spawned", "reaped", "worker-finished"]);
  assert.equal(run.rows[2].pid, run.rows[3].pid);
  assert.deepEqual(run.observed, { live: [], unknown: [], unrecordedSpawns: [] });
});

test("actual abrupt zero-exit before lifecycle finish is unproved, never an empty success", async (t) => {
  await assert.rejects(smoke(t, "os._exit(0)"), /lifecycle is missing, incomplete or changed/);
});

test("actual timeout-reaped nested helper leaves complete lifecycle and exact child rows", async (t) => {
  const run = await smoke(t, `from headless.process_runner import ProcessRequest, ProcessDeadlineError, run_text
try:
    run_text(ProcessRequest((sys.executable, '-c', 'import time; time.sleep(30)'), '', os.getcwd(), {}, 0.1))
except ProcessDeadlineError:
    print('deadline-reaped')`);
  assert.equal(run.result.stdout, "deadline-reaped\n");
  assert.deepEqual(run.rows.map((row) => row.event), ["worker-started", "intent", "spawned", "reaped", "worker-finished"]);
  assert.deepEqual(run.observed, { live: [], unknown: [], unrecordedSpawns: [] });
});

test("actual outer cancellation stays a forced stop, never a normally finished lifecycle", async (t) => {
  await assert.rejects(smoke(t, "import time; time.sleep(30)", 200), (error: unknown) => {
    assert.ok(error instanceof CutPreviewProcessError);
    assert.equal(error.details.groupStopped, true);
    assert.equal(error.details.forcedStop, true);
    assert.equal(error.details.timedOut, true);
    return true;
  });
});
