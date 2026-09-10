import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test, type TestContext } from "node:test";
import { bodyReadbackGuards } from "../guided-body-readback";
import { bodyClockObservation } from "../guided-body-process";
import { captureBodyAttemptStart } from "../guided-body-deadline";
import { guardGenerationAttempt } from "../generation-clock-watermark";

const ORIGINAL_MS = Date.parse("2026-09-07T08:39:00.000Z");
const OBSERVED_MS = Date.parse("2026-09-07T08:59:57.981Z");

/** TEST metadata only: actual durable clock files, no fabricated lease, media or approval. */
function fixture(context: TestContext) {
  const dir = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-body-readback-clock-")));
  context.after(() => rmSync(dir, { recursive: true, force: true }));
  context.mock.timers.enable({ apis: ["Date"], now: OBSERVED_MS });
  const origin = { clockHash: "a".repeat(64), startedAt: new Date(ORIGINAL_MS).toISOString() }, executionId = randomUUID();
  let mono = 0, ownershipCalls = 0, live = true;
  const ownership = () => { ownershipCalls += 1; if (!live) throw new Error("TEST ownership lost"); };
  const budget = guardGenerationAttempt({ dir, origin, executionId, guard: ownership },
    captureBodyAttemptStart({ wall: () => Date.now(), monotonic: () => mono }).start(origin));
  const remaining: number[] = [], remainingMs = () => {
    context.mock.timers.tick(1); mono += 1;
    const value = budget.remainingMs(); remaining.push(value); return value;
  };
  const held = { controlJob: { ctx: { dir } }, activation: { clockHash: origin.clockHash,
    generationStartedAt: origin.startedAt, executionId } } as Parameters<typeof bodyReadbackGuards>[0];
  const observations = () => {
    const root = path.join(dir, "generation-clock-observations", origin.clockHash);
    return readdirSync(root).map((name) => JSON.parse(readFileSync(path.join(root, name), "utf8")) as {
      observedAt: string; clockHash: string; generationStartedAt: string; executionId: string;
    }).sort((left, right) => left.observedAt.localeCompare(right.observedAt));
  };
  return { dir, held, origin, executionId, budget, ownership, remainingMs, remaining, observations,
    calls: () => ownershipCalls, loseOwnership: () => { live = false; },
    advance: (amount: number) => { context.mock.timers.tick(amount); mono += amount; } };
}

test("readback's production guards retain increasing real wall stamps without recursive budget observation", (context) => {
  const f = fixture(context), guards = bodyReadbackGuards(f.held, f.ownership, f.remainingMs);
  const admission = structuredClone(f.budget.admission);
  for (let index = 0; index < 4; index += 1) {
    guards.guard();
    f.advance(63); // Synchronous candidate/source/CAS reads consume the SAME attempt.
    guards.observeClock();
    guards.guard();
  }
  const rows = f.observations();
  assert.equal(rows.length, 1, "every check advances one durable scheduling watermark, not a per-check event file");
  assert.ok(f.calls() > 8);
  assert.equal(rows.at(-1)?.observedAt, new Date().toISOString());
  assert.ok(rows.every((row) => row.clockHash === f.origin.clockHash && row.generationStartedAt === f.origin.startedAt
    && row.executionId === f.executionId));
  assert.deepEqual(f.budget.admission, admission);
  assert.equal(f.remaining.length, 8, "only the before/after budget guards may observe the live allowance");
  assert.ok(f.remaining.every((value, index) => index === 0 || value < f.remaining[index - 1]));
});

test("the original nested callback reproduces false rollback with strictly increasing Date and actual durable files", (context) => {
  const f = fixture(context), combined = () => { f.ownership(); f.remainingMs(); };
  combined();
  const captured = new Date().toISOString();
  assert.throws(() => bodyClockObservation(f.held, combined), /clock-invalid: wall clock moved backwards across attempts/);
  assert.ok(f.observations().at(-1)!.observedAt > captured);
});

test("a genuinely backward wall still fails even with the corrected ownership-only observation", (context) => {
  const f = fixture(context), guards = bodyReadbackGuards(f.held, f.ownership, f.remainingMs);
  guards.guard(); guards.observeClock();
  const before = f.observations();
  context.mock.timers.setTime(Date.now() - 1);
  assert.throws(guards.observeClock, /clock-invalid: wall clock moved backwards across attempts/);
  assert.deepEqual(f.observations(), before);
});

test("post-read expiry and lost ownership still block the final guards without renewed allowance", (context) => {
  const f = fixture(context), guards = bodyReadbackGuards(f.held, f.ownership, f.remainingMs);
  guards.guard(); f.advance(55 * 60_000);
  guards.observeClock(); // Scheduling evidence only; not permission to finish after expiry.
  assert.throws(guards.guard, /deadline-exceeded/);
  const before = f.observations();
  f.loseOwnership();
  assert.throws(guards.observeClock, /ownership lost/);
  assert.throws(guards.guard, /ownership lost/);
  assert.deepEqual(f.observations(), before);
});
