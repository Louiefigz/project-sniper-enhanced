import assert from "node:assert/strict";
import test from "node:test";
import { captureOpeningAttemptStart, OPENING_DEADLINE_POLICY } from "../opening-deadline";
import { parseOpeningClockHandoff, startHandedOffOpeningAttempt } from "../opening-handoff-clock";

const origin = { clockHash: "a".repeat(64), startedAt: "2026-09-07T03:00:00.000Z" };
const start = Date.parse(origin.startedAt), maximum = OPENING_DEADLINE_POLICY.wholeAttemptMs;

function parentHandoff(wallSpent = 2000, monoSpent = 3000) {
  let wall = start, mono = 4000;
  const captured = captureOpeningAttemptStart({ wall: () => wall, monotonic: () => mono });
  const budget = captured.start(origin);
  wall += wallSpent; mono += monoSpent;
  return { receivedAt: captured.receivedAt, admission: budget.admission, observation: budget.observe() };
}

test("child budget preserves original admission and parent's greater measured elapsed floor", () => {
  let wall = start + 2500, mono = 900_000;
  const handoff = parentHandoff(), budget = startHandedOffOpeningAttempt({ origin, handoff, startupElapsedMs: 200 },
    { wall: () => wall, monotonic: () => mono });
  assert.deepEqual(budget.admission, handoff.admission);
  assert.equal(budget.remainingMs(), maximum - 3500);
  wall += 500; mono += 900;
  assert.equal(budget.remainingMs(), maximum - 4400);
  assert.equal(budget.admission.attemptDeadlineAt, "2026-09-07T03:25:00.000Z");
});

test("a stalled wall cannot make child startup or handoff wait free", () => {
  const handoff = parentHandoff(), budget = startHandedOffOpeningAttempt({ origin, handoff, startupElapsedMs: 10_000 },
    { wall: () => start + 2000, monotonic: () => 700_000 });
  assert.equal(budget.remainingMs(), maximum - 13_000);
});

test("startup, queue and controller delay can exhaust but never renew the same allocation", () => {
  const handoff = parentHandoff();
  for (const delay of [maximum, maximum + 10_000]) {
    const clock = startHandedOffOpeningAttempt({ origin, handoff, startupElapsedMs: delay },
      { wall: () => start + 2000, monotonic: () => 1 });
    assert.throws(clock.remainingMs, /deadline-exceeded/);
  }
  const expired = startHandedOffOpeningAttempt({ origin, handoff, startupElapsedMs: 1 },
    { wall: () => start + maximum, monotonic: () => 100 });
  assert.throws(expired.remainingMs, /deadline-exceeded/);
});

test("wall or monotonic rollback poisons the continued clock permanently", () => {
  for (const kind of ["startup-wall", "wall", "mono"]) {
    let wall = start + (kind === "startup-wall" ? 1999 : 2500), mono = 100;
    const budget = startHandedOffOpeningAttempt({ origin, handoff: parentHandoff(), startupElapsedMs: 0 },
      { wall: () => wall, monotonic: () => mono });
    if (kind === "wall") wall -= 1;
    if (kind === "mono") mono -= 1;
    assert.throws(budget.remainingMs, /clock-invalid/);
    wall += 1000; mono += 1000;
    assert.throws(budget.remainingMs, /clock-invalid/);
  }
});

test("forged floors, clock origins, policy changes and extra fields cannot grant time", () => {
  const handoff = parentHandoff();
  const invalid = [
    { ...handoff, receivedAt: new Date(start + 1).toISOString() },
    { ...handoff, extra: true },
    { ...handoff, observation: { ...handoff.observation, elapsedMs: 0 } },
    { ...handoff, observation: { ...handoff.observation, remainingMs: maximum } },
    { ...handoff, observation: { ...handoff.observation, clockHash: "b".repeat(64) } },
    { ...handoff, observation: { ...handoff.observation, state: "deadline-exceeded" } },
    { ...handoff, admission: { ...handoff.admission, excludedUserWaitMs: 0 } },
  ];
  for (const value of invalid) assert.throws(() => parseOpeningClockHandoff(value, origin));
  for (const startupElapsedMs of [-1, NaN, Infinity]) {
    assert.throws(() => startHandedOffOpeningAttempt({ origin, handoff, startupElapsedMs }));
  }
});
