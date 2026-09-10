import assert from "node:assert/strict";
import { test } from "node:test";
import { assertProposalDeadlineProof, GENERATION_DEADLINE_POLICY, proposalDeadlineAdmission, startProposalDeadline } from "../generation-deadline";

const MINUTE = 60_000;
const origin = { clockHash: "a".repeat(64), startedAt: "2026-09-06T07:00:00.000Z" };
const start = Date.parse(origin.startedAt);

test("proposal reserve is the declared remaining clean work, not a throughput prediction", () => {
  const value = proposalDeadlineAdmission(origin, start);
  assert.equal(value.remainingProposalWallMs, 40 * MINUTE);
  assert.equal(value.policy.afterProposalReserveMs, (15 + 25 + 15 + 15 + 5 + 5) * MINUTE);
  assert.equal(value.requestDeadlineAt, "2026-09-06T09:00:00.000Z");
  assert.equal(value.attemptDeadlineAt, "2026-09-06T07:10:00.000Z");
  assert.equal(value.excludedUserWaitMs, null, "unknown user wait must not be reported as measured zero");
  assert.match(value.policy.basis, /not-measured/);
  assert.ok(Object.isFrozen(value) && Object.isFrozen(GENERATION_DEADLINE_POLICY));
});

test("retries retain original request budget and require enough room for a whole existing attempt ceiling", () => {
  assert.equal(proposalDeadlineAdmission(origin, start + 30 * MINUTE).admitted, true);
  const denied = proposalDeadlineAdmission(origin, start + 30 * MINUTE + 1);
  assert.equal(denied.admitted, false);
  assert.equal(denied.attemptDeadlineAt, null);
  for (const elapsed of [40, 120, 600]) {
    const value = proposalDeadlineAdmission(origin, start + elapsed * MINUTE);
    assert.equal(value.remainingProposalWallMs, 0);
    assert.equal(value.requestDeadlineAt, denied.requestDeadlineAt);
    assert.equal(value.admitted, false);
  }
});

test("preparation and result checking consume the same ten-minute attempt as the provider", () => {
  let wall = start, mono = 100;
  const budget = startProposalDeadline(origin, { wall: () => wall, monotonic: () => mono });
  wall += 2 * MINUTE; mono += 2 * MINUTE;
  assert.equal(budget.remainingMs(), 8 * MINUTE);
  wall += 7 * MINUTE; mono += 7 * MINUTE;
  assert.equal(budget.remainingMs(), MINUTE);
  wall += MINUTE; mono += MINUTE;
  assert.throws(budget.remainingMs, /deadline-exceeded/);
  assert.equal(budget.observe().elapsedMs, 10 * MINUTE);
});

test("either wall or monotonic elapsed prevents clock/suspend undercount; rollback poisons the attempt", () => {
  let wall = start, mono = 100;
  const budget = startProposalDeadline(origin, { wall: () => wall, monotonic: () => mono });
  wall += 3 * MINUTE; mono += MINUTE;
  assert.equal(budget.remainingMs(), 7 * MINUTE);
  mono += 3 * MINUTE;
  assert.equal(budget.remainingMs(), 6 * MINUTE);
  wall -= 1;
  assert.throws(budget.remainingMs, /clock-invalid/);
  wall += 10;
  assert.throws(budget.remainingMs, /clock-invalid/, "a later good sample cannot unpoison the clock");
});

test("denied attempts and malformed/unavailable clocks cannot be used to spawn paid work", () => {
  const budget = startProposalDeadline(origin, { wall: () => start + 31 * MINUTE, monotonic: () => 0 });
  assert.throws(budget.remainingMs, /not-admitted/);
  assert.throws(() => proposalDeadlineAdmission(origin, start - 1), /backwards/);
  for (const now of [NaN, Infinity, -1]) assert.throws(() => proposalDeadlineAdmission(origin, now));
  for (const startedAt of ["yesterday", "2026-09-06", "2026-09-06T07:00:00Z"]) {
    assert.throws(() => proposalDeadlineAdmission({ ...origin, startedAt }, start));
  }
  assert.throws(() => proposalDeadlineAdmission({ ...origin, clockHash: "bad" }, start));
});

test("stored budget proof binds original clock, execution, whole-attempt elapsed and exact declared policy", () => {
  let wall = start, mono = 0;
  const budget = startProposalDeadline(origin, { wall: () => wall, monotonic: () => mono });
  wall += MINUTE; mono += MINUTE;
  const value = { admission: budget.admission, precommit: budget.observe() };
  const binding = { origin, executionStartedAt: origin.startedAt, createdAt: new Date(wall).toISOString() };
  assert.doesNotThrow(() => assertProposalDeadlineProof(value, binding));
  for (const change of [
    { elapsedMs: 0 }, { elapsedMs: 10 * MINUTE, remainingMs: 0 }, { remainingMs: 600_000 },
    { state: "deadline-exceeded" }, { clockHash: "b".repeat(64) }, { hiddenWait: MINUTE },
    { observedAt: new Date(wall + 1).toISOString() },
  ]) assert.throws(() => assertProposalDeadlineProof({ ...value, precommit: { ...value.precommit, ...change } }, binding));
  assert.throws(() => assertProposalDeadlineProof({ ...value, admission: { ...value.admission,
    policy: { ...value.admission.policy, requestMs: 240 * MINUTE } } }, binding));
  assert.throws(() => assertProposalDeadlineProof(value, { ...binding,
    origin: { ...origin, startedAt: new Date(start - MINUTE).toISOString() } }));
  assert.throws(() => assertProposalDeadlineProof(value, { ...binding,
    executionStartedAt: new Date(start + 1).toISOString() }));
  assert.throws(() => assertProposalDeadlineProof(value, { ...binding,
    createdAt: new Date(start + 10 * MINUTE).toISOString() }));
});
