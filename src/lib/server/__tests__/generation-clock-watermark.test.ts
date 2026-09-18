import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { guardGenerationAttempt, retainGenerationClockObservation, startGuardedProposalDeadline } from "../generation-clock-watermark";
import { startProposalReadinessDeadline } from "../proposal-readiness-deadline";

const origin = { clockHash: "a".repeat(64), startedAt: "2026-09-06T07:00:00.000Z" };
const start = Date.parse(origin.startedAt);
const guard = () => {};
const temporary = () => realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-clock-watermark-")));

test("a fresh process or new attempt ID cannot recover time by moving the wall clock backwards", () => {
  const dir = temporary();
  try {
    const first = startGuardedProposalDeadline({ dir, origin, executionId: randomUUID(), guard },
      { wall: () => start + 5 * 60_000, monotonic: () => 0 });
    assert.equal(first.remainingMs(), 600_000);
    const retry = startGuardedProposalDeadline({ dir, origin, executionId: randomUUID(), guard },
      { wall: () => start + 4 * 60_000, monotonic: () => 0 });
    assert.throws(retry.remainingMs, /clock-invalid.*across attempts/);
    const later = startGuardedProposalDeadline({ dir, origin, executionId: randomUUID(), guard },
      { wall: () => start + 6 * 60_000, monotonic: () => 0 });
    assert.equal(later.remainingMs(), 600_000);
    assert.equal(later.admission.elapsedRequestWallMs, 6 * 60_000);
    assert.equal(later.admission.requestDeadlineAt, first.admission.requestDeadlineAt);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("observations are immutable, clock-bound, lease-guarded and reject poisoned or linked history", () => {
  const dir = temporary();
  try {
    const input = { dir, origin, executionId: randomUUID(), observedAt: new Date(start).toISOString() };
    assert.throws(() => retainGenerationClockObservation(input, () => { throw new Error("lease lost"); }), /lease lost/);
    assert.deepEqual(readdirSync(dir), []);
    retainGenerationClockObservation(input, guard); retainGenerationClockObservation(input, guard);
    const folder = path.join(dir, "generation-clock-observations", origin.clockHash), names = readdirSync(folder);
    assert.equal(names.length, 1);
    const file = path.join(folder, names[0]), original = readFileSync(file);
    writeFileSync(file, "{}");
    assert.throws(() => retainGenerationClockObservation(input, guard), /missing|changed/);
    writeFileSync(file, original); rmSync(file); symlinkSync(path.join(dir, "elsewhere"), file);
    assert.throws(() => retainGenerationClockObservation(input, guard));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("an expired attempt's later wall observation survives and is never converted to fresh allowance", () => {
  const dir = temporary();
  try {
    let wall = start, mono = 0;
    const budget = startGuardedProposalDeadline({ dir, origin, executionId: randomUUID(), guard },
      { wall: () => wall, monotonic: () => mono });
    budget.remainingMs(); wall += 11 * 60_000; mono += 11 * 60_000;
    assert.throws(budget.remainingMs, /deadline-exceeded/);
    const retry = startGuardedProposalDeadline({ dir, origin, executionId: randomUUID(), guard },
      { wall: () => start + 10 * 60_000, monotonic: () => 0 });
    assert.throws(retry.remainingMs, /across attempts/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("a healthy-lease failure outcome advances durable high-water even when no remaining check follows", () => {
  const dir = temporary();
  try {
    let wall = start;
    const first = startGuardedProposalDeadline({ dir, origin, executionId: randomUUID(), guard },
      { wall: () => wall, monotonic: () => wall - start });
    first.remainingMs(); wall += 9 * 60_000;
    assert.equal(first.observe().elapsedMs, 9 * 60_000, "catch/finally observation must persist too");
    const retry = startGuardedProposalDeadline({ dir, origin, executionId: randomUUID(), guard },
      { wall: () => start + 2 * 60_000, monotonic: () => 0 });
    assert.throws(retry.remainingMs, /across attempts/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("switching from compiler to readiness cannot reset the original request observation history", () => {
  const dir = temporary();
  try {
    let wall = start;
    const compile = startGuardedProposalDeadline({ dir, origin, executionId: randomUUID(), guard },
      { wall: () => wall, monotonic: () => wall - start });
    wall += 9 * 60_000; compile.observe();
    const readiness = (at: number) => guardGenerationAttempt({ dir, origin, executionId: randomUUID(), guard },
      startProposalReadinessDeadline(origin, { wall: () => at, monotonic: () => 0 }));
    assert.throws(readiness(start + 8 * 60_000).remainingMs, /across attempts/);
    assert.equal(readiness(start + 10 * 60_000).remainingMs(), 20 * 60_000);
    const secondCompile = startGuardedProposalDeadline({ dir, origin, executionId: randomUUID(), guard },
      { wall: () => start + 9 * 60_000, monotonic: () => 0 });
    assert.throws(secondCompile.remainingMs, /across attempts/);
    assert.deepEqual(readdirSync(path.join(dir, "generation-clock-observations")), [origin.clockHash]);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
