import assert from "node:assert/strict";
import { test } from "node:test";
import { proposalDeadlineAdmission } from "../generation-deadline";
import { generationChildTimeout } from "../generation-attempt-clock";
import { assertProposalReadinessDeadlineProof, PROPOSAL_READINESS_DEADLINE_POLICY,
  proposalReadinessDeadlineAdmission, startProposalReadinessDeadline } from "../proposal-readiness-deadline";

const MINUTE = 60_000;
const origin = { clockHash: "a".repeat(64), startedAt: "2026-09-06T07:00:00.000Z" };
const start = Date.parse(origin.startedAt);

test("advisor and source-verification children inherit the parent's remaining time without changing legacy defaults", () => {
  assert.equal(generationChildTimeout(120_000), 120_000);
  assert.equal(generationChildTimeout(30_000, () => 100_000), 30_000);
  assert.equal(generationChildTimeout(120_000, () => 370), 370);
  for (const left of [0, -1, NaN, Infinity, 1.5]) assert.throws(() => generationChildTimeout(30_000, () => left), /positive bounded/);
  assert.throws(() => generationChildTimeout(30_000, () => { throw new Error("lease or deadline expired"); }), /expired/);
});

test("readiness consumes the original proposal phase, preserving the same 80-minute required finish", () => {
  const compile = proposalDeadlineAdmission(origin, start), value = proposalReadinessDeadlineAdmission(origin, start + 10 * MINUTE);
  assert.equal(value.phaseDeadlineAt, compile.phaseDeadlineAt); assert.equal(value.requestDeadlineAt, compile.requestDeadlineAt);
  assert.equal(value.attemptDeadlineAt, "2026-09-06T07:30:00.000Z");
  assert.equal(value.remainingProposalWallMs, 30 * MINUTE); assert.equal(value.elapsedRequestWallMs, 10 * MINUTE);
  assert.equal(value.policy.cleanProposalTargetMs, 10 * MINUTE); assert.equal(value.policy.wholeAttemptMs, 20 * MINUTE);
  assert.equal(value.excludedUserWaitMs, null); assert.match(value.scope, /not-plan-or-complete/);
  assert.ok(Object.isFrozen(value) && Object.isFrozen(PROPOSAL_READINESS_DEADLINE_POLICY));
});

test("late readiness cannot purchase another local deadline or spend required downstream reserve", () => {
  assert.equal(proposalReadinessDeadlineAdmission(origin, start + 20 * MINUTE).admitted, true);
  for (const elapsed of [20 * MINUTE + 1, 40 * MINUTE, 120 * MINUTE]) {
    const denied = proposalReadinessDeadlineAdmission(origin, start + elapsed);
    assert.equal(denied.admitted, false); assert.equal(denied.attemptDeadlineAt, null);
    const clock = startProposalReadinessDeadline(origin, { wall: () => start + elapsed, monotonic: () => 0 });
    assert.throws(clock.remainingMs, /not-admitted/);
  }
});

test("both critics, source revalidation and final persistence share one wall/monotonic ceiling", () => {
  let wall = start, mono = 100;
  const clock = startProposalReadinessDeadline(origin, { wall: () => wall, monotonic: () => mono });
  wall += 3 * MINUTE; mono += 2 * MINUTE; assert.equal(clock.remainingMs(), 17 * MINUTE);
  mono += 10 * MINUTE; assert.equal(clock.remainingMs(), 8 * MINUTE);
  wall -= 1; assert.throws(clock.remainingMs, /clock-invalid/);
  wall += MINUTE; assert.throws(clock.remainingMs, /clock-invalid/);
  const suspended = startProposalReadinessDeadline(origin, { wall: () => wall, monotonic: () => mono });
  wall += 20 * MINUTE; assert.throws(suspended.remainingMs, /deadline-exceeded/);
});

test("receipt proof cannot relabel compile timing, erase elapsed time, expand policy or commit at the deadline", () => {
  let wall = start, mono = 0;
  const clock = startProposalReadinessDeadline(origin, { wall: () => wall, monotonic: () => mono });
  wall += MINUTE; mono += MINUTE;
  const values = { admission: clock.admission, precommit: clock.observe() };
  const binding = { origin, executionStartedAt: origin.startedAt, createdAt: new Date(wall).toISOString() };
  assert.doesNotThrow(() => assertProposalReadinessDeadlineProof(values, binding));
  for (const patch of [{ kind: "guided-proposal-deadline-observation" }, { elapsedMs: 0 },
    { remainingMs: 20 * MINUTE }, { excludedUserWaitMs: 0 }, { state: "deadline-exceeded" }]) {
    assert.throws(() => assertProposalReadinessDeadlineProof({ ...values, precommit: { ...values.precommit, ...patch } }, binding));
  }
  assert.throws(() => assertProposalReadinessDeadlineProof({ ...values, admission: { ...values.admission,
    policy: { ...values.admission.policy, wholeAttemptMs: 30 * MINUTE } } }, binding));
  assert.throws(() => assertProposalReadinessDeadlineProof(values, { ...binding, createdAt: "2026-09-06T07:20:00.000Z" }));
  assert.throws(() => assertProposalReadinessDeadlineProof(values, { ...binding, executionStartedAt: "2026-09-06T07:00:00.001Z" }));
});
