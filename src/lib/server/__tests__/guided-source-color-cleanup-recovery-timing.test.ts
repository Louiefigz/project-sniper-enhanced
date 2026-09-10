/** Original recovery/proof clocks and final append/release tails; TEMP metadata only, no native cleanup. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { reconcilePendingSourceColorCleanup } from "../guided-source-color-cleanup-recovery";
import { cleanupRecoveryFixture, cleanupRecoveryDependencies, assertRecoveryRetained,
  replaceRecoveryFile } from "./_guided-source-color-cleanup-recovery-fixture";

test("final proof gets one 30s read-only cap inside the unchanged 300s recovery clock", async t => {
  const f = await cleanupRecoveryFixture(t), deps = cleanupRecoveryDependencies(f), history = deps.read.history;
  const actualNow = performance.now.bind(performance); let advance = 0, calls = 0;
  t.mock.method(performance, "now", () => actualNow() + advance);
  deps.read.history = (input, hash) => { const value = history(input, hash); calls++; advance = 30_001; return value; };
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, deps), /Final cleanup read-only observation budget expired/);
  assert.equal(calls, 1); assert(f.input.clock.remainingMs() > 200_000);
  assertRecoveryRetained(f, { project: true, resource: true }, true);
});

test("expiry after actual resource release keeps the unreleased project lease and final proof", async t => {
  const f = await cleanupRecoveryFixture(t);
  f.callbacks.resourceAfter = () => {
    const lease = f.resources[0], release = lease.release;
    lease.release = () => { release.call(lease); f.timing.advance = 300_000; };
  };
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /allowance/);
  assertRecoveryRetained(f, { project: true, resource: false }, true);
});

test("clock callback identity replacement after final CAS never renews the original recovery allowance", async t => {
  const f = await cleanupRecoveryFixture(t), deps = cleanupRecoveryDependencies(f), history = deps.read.history;
  deps.read.history = (input, hash) => {
    const value = history(input, hash); f.input.clock.remainingMs = () => 300_000; return value;
  };
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, deps), /original request, clock/);
  assertRecoveryRetained(f, { project: true, resource: true }, true);
});

for (const fault of ["expiry", "media", "journal"] as const) test(`final awaited timing append cannot conceal ${fault} after both verified releases`, async t => {
  const f = await cleanupRecoveryFixture(t), actualWrite = fs.writeSync; let fired = false;
  t.mock.method(fs, "writeSync", (...args: Parameters<typeof fs.writeSync>) => {
    const value = actualWrite(...args), text = typeof args[1] === "string" ? args[1] : "";
    if (fired || !text.includes('"stage":"guided_opening_source_color_retirement_recovery"') || !text.includes('"event":"end"')) return value;
    fired = true; assert(!fs.existsSync(f.projectLock)); assert(!fs.existsSync(f.resourceLock));
    if (fault === "expiry") f.timing.advance = 300_000; else replaceRecoveryFile(f, fault);
    return value;
  });
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /allowance|original|changed/);
  assert(fired); assertRecoveryRetained(f, { project: false, resource: false }, true);
});

test("the recovery timing span includes failed awaited project acquisition rather than reporting completion", async t => {
  const f = await cleanupRecoveryFixture(t);
  f.callbacks.projectBefore = async () => { await Promise.resolve(); f.timing.advance = 300_000; };
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /allowance/);
  const rows = fs.readFileSync(path.join(f.input.dir, "stage_timings.jsonl"), "utf8").trim().split("\n").map(row => JSON.parse(row))
    .filter(row => row.stage === "guided_opening_source_color_retirement_recovery");
  assert.equal(rows.length, 2); assert.deepEqual(rows.map(row => row.event), ["start", "end"]);
  assert.equal(rows[1].status, "failed"); assert.equal(rows[0].spanId, rows[1].spanId); assert(rows[1].elapsedMs > 0);
  assertRecoveryRetained(f, { project: false, resource: false });
});
