/** Finite clock checkpoints and TEST-only scheduling files; no generation or provider work. */
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import test, { type TestContext } from "node:test";
import { startProposalDeadline, type DeadlineClocks } from "../generation-deadline";
import { captureOpeningAttemptStart } from "../opening-deadline";
import { startHandedOffOpeningAttempt } from "../opening-handoff-clock";
import { guardGenerationAttempt, startGuardedProposalDeadline } from "../generation-clock-watermark";

const origin = { clockHash: "a".repeat(64), startedAt: "2026-09-08T00:00:00.000Z" };
const start = Date.parse(origin.startedAt), stamp = (offset: number) => new Date(start + offset).toISOString();
const factories = {
  proposal: (clocks: DeadlineClocks) => startProposalDeadline(origin, clocks),
  handoff: (clocks: DeadlineClocks) => {
    const captured = captureOpeningAttemptStart({ wall: () => start, monotonic: () => 0 });
    const parent = captured.start(origin);
    return startHandedOffOpeningAttempt({ origin, startupElapsedMs: 0,
      handoff: { receivedAt: captured.receivedAt, admission: parent.admission, observation: parent.observe() } }, clocks);
  },
};
function fixture(t: TestContext) {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sniper-checkpoint-unit-")));
  t.after(() => {
    assert.equal(fs.realpathSync(dir), dir); assert.equal(path.dirname(dir), fs.realpathSync(os.tmpdir()));
    fs.rmSync(dir, { recursive: true, force: true });
  });
  const executionId = randomUUID(), file = path.join(dir, "generation-clock-observations", origin.clockHash, `${executionId}.json`);
  return { dir, executionId, file, retained: () => JSON.parse(fs.readFileSync(file, "utf8")).observedAt };
}

test("both original clock kinds keep no-argument sampling unchanged", () => {
  for (const create of Object.values(factories)) {
    let walls = 0, monos = 0;
    const budget = create({ wall: () => { walls++; return start; }, monotonic: () => { monos++; return 0; } });
    budget.observe(); assert.equal(walls, 2); assert.equal(monos, 2);
  }
});

test("both clock kinds charge persistence after wall-dominated elapsed and never refund its floor", () => {
  for (const create of Object.values(factories)) {
    let wall = start, mono = 0; const stamps: string[] = [];
    const budget = create({ wall: () => wall, monotonic: () => mono });
    wall += 1000; mono = 10;
    const first = budget.observe(at => { stamps.push(at); mono += 25; });
    assert.equal(first.elapsedMs, 1025); assert.deepEqual(stamps, [stamp(1000)]);
    assert.equal(budget.observe().elapsedMs, 1025);
    mono += 5; assert.equal(budget.observe().elapsedMs, 1030);
    const next = budget.observe(() => { mono += 10; });
    assert.equal(next.elapsedMs, 1040); assert.equal(next.remainingMs, first.remainingMs - 15);
  }
});

test("stalled wall charges original monotonic work and postwrite rollback poisons both kinds", () => {
  for (const create of Object.values(factories)) {
    let mono = 0; const budget = create({ wall: () => start, monotonic: () => mono });
    assert.equal(budget.observe(() => { mono += 40; }).elapsedMs, 40);
    assert.equal(budget.observe(() => { mono = 39; }).state, "clock-invalid");
    mono = 50; assert.equal(budget.observe().state, "clock-invalid");
  }
});

test("failed persistence still charges its wall-dominated monotonic cost without a new wall sample", () => {
  for (const create of Object.values(factories)) {
    let wall = start, mono = 0, samples = 0;
    const budget = create({ wall: () => { samples++; return wall; }, monotonic: () => mono });
    wall += 1000; mono = 10; const failure = new Error("TEST checkpoint failed");
    assert.throws(() => budget.observe(() => { mono += 25; throw failure; }), error => error === failure);
    assert.equal(samples, 2); assert.equal(budget.observe().elapsedMs, 1025);
  }
});

test("an actually observed rollback during failed persistence permanently poisons both clocks", () => {
  for (const create of Object.values(factories)) {
    let mono = 0, wallSamples = 0;
    const budget = create({ wall: () => { wallSamples++; return start; }, monotonic: () => mono });
    const failure = new Error("TEST persistence failure after actual monotonic rollback"); mono = 80;
    assert.throws(() => budget.observe(() => { mono = 50; throw failure; }), error => error === failure);
    assert.equal(wallSamples, 2, "failed checkpoint must not introduce another wall sample");
    mono = 100; const later = budget.observe();
    assert.equal(later.state, "clock-invalid"); assert.equal(later.remainingMs, 0);
    mono = 200; assert.throws(budget.remainingMs, /clock-invalid/);
  }
});

test("original wall and monotonic functions cannot be replaced before or inside a checkpoint", () => {
  for (const create of Object.values(factories)) {
    for (const field of ["wall", "monotonic"] as const) {
      const clocks = { wall: () => start, monotonic: () => 0 }, budget = create(clocks);
      let replacementCalls = 0;
      const replace = () => { clocks[field] = () => { replacementCalls++; return 0; }; };
      assert.throws(() => budget.observe(replace), /original clock callbacks changed/);
      assert.equal(replacementCalls, 0); assert.throws(() => budget.observe(), /original clock callbacks changed/);
    }
  }
});

test("expiry during persistence never introduces an unretained second wall sample", t => {
  const f = fixture(t), samples: number[] = []; let wall = start, mono = 0, guards = 0;
  const budget = startGuardedProposalDeadline({ ...f, origin,
    guard: () => { if (++guards === 3) { wall = start + 11 * 60_000; mono = 11 * 60_000; } } },
  { wall: () => { samples.push(wall); return wall; }, monotonic: () => mono });
  wall = start + 60_000; mono = 60_000;
  assert.throws(budget.remainingMs, /deadline-exceeded/);
  assert.deepEqual(samples, [start, start + 60_000]); assert.equal(f.retained(), stamp(60_000));
  const earlier = startGuardedProposalDeadline({ ...f, origin, executionId: randomUUID(), guard: () => undefined },
    { wall: () => start + 59_999, monotonic: () => 0 });
  assert.throws(earlier.remainingMs, /backwards across attempts/);
});

test("successful checkpoint retains every sampled wall and charges postwrite time without resampling", t => {
  const f = fixture(t), samples: number[] = []; let wall = start, mono = 0, guards = 0;
  const budget = startGuardedProposalDeadline({ ...f, origin,
    guard: () => { if (++guards === 3) { wall += 100; mono += 100; } } },
  { wall: () => { samples.push(wall); return wall; }, monotonic: () => mono });
  wall += 1000; mono = 1000;
  assert.equal(budget.remainingMs(), 598_900);
  assert.deepEqual(samples, [start, start + 1000]); assert.equal(f.retained(), stamp(1000));
  const retry = startGuardedProposalDeadline({ ...f, origin, executionId: randomUUID(), guard: () => undefined },
    { wall: () => start + 999, monotonic: () => 0 });
  assert.throws(retry.remainingMs, /backwards across attempts/);
});

test("final publication failure retains the sampled wall without a second sample or renewed clock", t => {
  const f = fixture(t), samples: number[] = []; let wall = start, mono = 0, guards = 0;
  const failure = new Error("TEST final publication guard failed");
  const clock = startProposalDeadline(origin, { wall: () => { samples.push(wall); return wall; }, monotonic: () => mono });
  const budget = guardGenerationAttempt({ ...f, origin, guard: () => {
    if (++guards === 3) { wall += 100; mono += 100; throw failure; }
  } }, clock);
  wall += 1000; mono = 1000;
  assert.throws(budget.remainingMs, error => error === failure);
  assert.deepEqual(samples, [start, start + 1000]); assert.equal(f.retained(), stamp(1000));
  assert.equal(clock.observe().elapsedMs, 1100);
});
