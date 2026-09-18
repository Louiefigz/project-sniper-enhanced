/** Actual owned-runner/deadline/hook control flow, with EventEmitter child leaves only: no process or media is spawned. */
import assert from "node:assert/strict";
import childProcess from "node:child_process";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import fs from "node:fs";
import path from "node:path";
import test, { type TestContext } from "node:test";
import { CutPreviewProcessError, runCutPreviewProcess } from "@/app/api/producer/auto-edit/cut-preview-process";
import { withCallerProcessDeadline } from "../caller-process-deadline";
import { sourceColorMediaFixture, replaceMediaFixtureFile } from "./_guided-source-color-media-process-fixture";

/** No pid means this explicit fake never asks the OS to observe/kill a group. */
function fakeChild(t: TestContext, onSpawn = () => {}, exitCode = 0) {
  let count = 0; const args: unknown[][] = [];
  t.mock.method(childProcess, "spawn", (...actual: unknown[]) => {
    count++; args.push(actual); onSpawn();
    const child = Object.assign(new EventEmitter(), { stdout: new PassThrough(), stderr: new PassThrough() });
    queueMicrotask(() => { child.stdout.write("TEST fake child output"); child.emit("close", exitCode, null); });
    return child as unknown as childProcess.ChildProcess;
  });
  return { count: () => count, args };
}
const command = { command: "/TEST/never-executed", args: ["TEST literal"], cwd: "/private/tmp",
  env: { NODE_ENV: "test" as const }, timeoutMs: 500 };

test("absent hooks preserve actual owned-runner arguments and normal return", async t => {
  const child = fakeChild(t), result = await runCutPreviewProcess(command);
  assert.deepEqual(result, { stdout: "TEST fake child output", stderr: "" }); assert.equal(child.count(), 1);
  assert.equal(child.args[0][0], command.command); assert.deepEqual(child.args[0][1], command.args);
});

test("pre-spawn hook is after the actual ancestor callback and charges its cost against the shorter captured scope", async t => {
  const child = fakeChild(t), delays: number[] = []; let mono = 0, calls = 0;
  t.mock.method(performance, "now", () => mono);
  const original = setTimeout;
  t.mock.method(globalThis, "setTimeout", ((run: (...args: unknown[]) => void, delay?: number, ...args: unknown[]) => {
    delays.push(Number(delay)); return original(run, delay, ...args);
  }) as typeof setTimeout);
  await withCallerProcessDeadline({ remainingMs: () => { calls++; return 50; }, maxChildMs: 50 }, () =>
    runCutPreviewProcess({ ...command, beforeSpawn: () => { assert.equal(calls, 2); mono += 12; } }));
  assert.equal(child.count(), 1); assert.deepEqual(delays, [38]);
});

test("slow pre-spawn metadata cannot refund the original ancestor timeout or reach the fake native leaf", async t => {
  const child = fakeChild(t); let mono = 0; t.mock.method(performance, "now", () => mono);
  await assert.rejects(withCallerProcessDeadline({ remainingMs: () => 50, maxChildMs: 50 }, () =>
    runCutPreviewProcess({ ...command, beforeSpawn: () => { mono += 51; } })), /original captured allowance/);
  assert.equal(child.count(), 0);
});

test("settled hook failures preserve real outer stop facts and output rather than imply no-start", async t => {
  const child = fakeChild(t);
  await assert.rejects(runCutPreviewProcess({ ...command, afterSettled: () => { throw new Error("TEST failed metadata"); } }), error => {
    assert(error instanceof CutPreviewProcessError); assert.equal(error.details.groupStopped, true);
    assert.equal(error.details.forcedStop, false); assert.equal(error.details.timedOut, false);
    assert.equal(error.details.stdout, "TEST fake child output"); return true;
  });
  assert.equal(child.count(), 1);
});

test("actual settled metadata hook precedes expired ancestor enforcement without skipping it", async t => {
  const child = fakeChild(t); let observed = false, calls = 0;
  await assert.rejects(withCallerProcessDeadline({ remainingMs: () => ++calls < 3 ? 50 : 0, maxChildMs: 50 }, () =>
    runCutPreviewProcess({ ...command, afterSettled: details => { observed = true; assert.equal(calls, 2); assert(details.groupStopped); } })), error => {
    assert(error instanceof CutPreviewProcessError); assert.equal(error.details.groupStopped, true);
    assert.equal(error.details.forcedStop, false); assert.equal(error.details.timedOut, true); return true;
  });
  assert(observed); assert.equal(child.count(), 1);
});

test("settled nonzero exit keeps its actual error facts when its metadata hook also fails", async t => {
  const child = fakeChild(t, () => {}, 7); let calls = 0;
  await assert.rejects(runCutPreviewProcess({ ...command, afterSettled: details => {
    calls++; assert.equal(details.groupStopped, true); throw new Error("TEST metadata failure after exit seven");
  } }), error => {
    assert(error instanceof CutPreviewProcessError); assert.equal(error.exitCode, 7);
    assert.equal(error.details.groupStopped, true); assert.equal(error.details.forcedStop, false);
    assert.equal(error.details.timedOut, false); return true;
  });
  assert.equal(calls, 1); assert.equal(child.count(), 1);
});

/** Forward both actual guarded frontiers; runtime/admission translation is the explicit TEST-only invoke leaf. */
function runnerLeaf(f: ReturnType<typeof sourceColorMediaFixture>) {
  f.dependencies.invoke = input => runCutPreviewProcess({ ...command, timeoutMs: Math.floor(input.remainingMs()), purpose: "guided-opening",
    beforeSpawn: input.beforeSpawn, afterSettled: input.afterSettled });
}

/** New-only bytes in the exact canonical TEST execution root; an existing or linked destination is never opened. */
function createFixtureLedger(f: ReturnType<typeof sourceColorMediaFixture>, bytes: string): void {
  assert(f.root.startsWith(f.staging.root + path.sep)); assert.equal(fs.realpathSync(f.root), f.root);
  const parent = fs.lstatSync(f.root); assert(parent.isDirectory()); assert.equal(parent.uid, process.getuid!());
  fs.writeFileSync(path.join(f.root, "owned-process-ledger.media.jsonl"), bytes, { flag: "wx", mode: 0o600 });
}

test("ancestor mutation after invoker remainder samples cannot create a ledger and still reach native spawn", async t => {
  const f = sourceColorMediaFixture(t), child = fakeChild(t); runnerLeaf(f); let calls = 0;
  const result = await withCallerProcessDeadline({ remainingMs: () => {
    if (++calls === 2) createFixtureLedger(f, "TEST premature ledger\n");
    return 60_000;
  }, maxChildMs: 60_000 }, f.run);
  assert.equal(child.count(), 0); assert.equal(result.receipt.status, "failed"); assert.equal(result.stopped, null);
});

test("post-settlement ancestor callback cannot erase an original nested intent before the writer holds its ledger", async t => {
  const f = sourceColorMediaFixture(t); runnerLeaf(f); let calls = 0;
  const script = f.tools.script, rows = [
    { event: "worker-started", pid: 123456, argv0: script, at: 100 },
    { event: "intent", pid: null, argv0: "/TEST/unspawned-child", at: 100.5 },
    { event: "worker-finished", pid: 123456, argv0: script, at: 101 }];
  const child = fakeChild(t, () => createFixtureLedger(f, rows.map(row => JSON.stringify(row)).join("\n") + "\n"));
  await assert.rejects(withCallerProcessDeadline({ remainingMs: () => {
    if (++calls === 3) replaceMediaFixtureFile(f, "ledger", [rows[0], rows[2]].map(row => JSON.stringify(row)).join("\n") + "\n");
    return 60_000;
  }, maxChildMs: 60_000 }, f.run), /changed/);
  assert.equal(child.count(), 1); assert.equal(fs.existsSync(path.join(f.root, "media-process-result.json")), false);
});
