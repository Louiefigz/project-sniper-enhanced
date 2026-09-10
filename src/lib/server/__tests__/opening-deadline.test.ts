import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { assertOpeningDeadlineProof, captureOpeningAttemptStart, OPENING_DEADLINE_POLICY,
  openingDeadlineAdmission } from "../opening-deadline";
import { generationChildTimeout } from "../generation-attempt-clock";
import { guardGenerationAttempt, startGuardedProposalDeadline } from "../generation-clock-watermark";

const MINUTE = 60_000;
const origin = { clockHash: "a".repeat(64), startedAt: "2026-09-06T07:00:00.000Z" };
const start = Date.parse(origin.startedAt);

test("opening preserves all body assets and quality allowances without credit for unproved work", () => {
  const value = openingDeadlineAdmission(origin, start + 15 * MINUTE);
  assert.equal(value.admitted, true); assert.equal(value.phaseDeadlineAt, "2026-09-06T07:40:00.000Z");
  assert.equal(value.attemptDeadlineAt, value.phaseDeadlineAt);
  assert.equal(value.requestDeadlineAt, "2026-09-06T09:00:00.000Z");
  assert.equal(value.policy.requiredDownstreamReserveMs, (15 + 25 + 15 + 15 + 5 + 5) * MINUTE);
  assert.equal(value.policy.preparedAssetCreditMs, 0); assert.equal(value.excludedUserWaitMs, null);
  assert.ok(Object.isFrozen(value) && Object.isFrozen(OPENING_DEADLINE_POLICY));
  for (const elapsed of [15 * MINUTE + 1, 40 * MINUTE, 120 * MINUTE]) {
    const denied = openingDeadlineAdmission(origin, start + elapsed);
    assert.equal(denied.admitted, false); assert.equal(denied.attemptDeadlineAt, null);
  }
});

test("metadata reads and lease waiting spend the captured attempt before its original clock is known", () => {
  let wall = start, mono = 0;
  const captured = captureOpeningAttemptStart({ wall: () => wall, monotonic: () => mono });
  wall += 4 * MINUTE; mono += 3 * MINUTE;
  const clock = captured.start(origin);
  assert.equal(clock.admission.observedAt, captured.receivedAt);
  assert.equal(clock.remainingMs(), 21 * MINUTE);
  assert.equal(generationChildTimeout(25 * MINUTE, clock.remainingMs), 21 * MINUTE);
  assert.throws(() => captured.start(origin), /cannot be renewed/);
  mono += 22 * MINUTE;
  assert.throws(clock.remainingMs, /deadline-exceeded/);
});

test("exhaustion before binding, clock rollback and malformed clocks cannot start the renderer", () => {
  let wall = start;
  const mono = 0;
  const captured = captureOpeningAttemptStart({ wall: () => wall, monotonic: () => mono });
  wall += 25 * MINUTE;
  assert.throws(captured.start(origin).remainingMs, /deadline-exceeded/);
  const rollback = captureOpeningAttemptStart({ wall: () => wall, monotonic: () => mono }).start(origin);
  wall -= 1; assert.throws(rollback.remainingMs, /clock-invalid/);
  wall += MINUTE; assert.throws(rollback.remainingMs, /clock-invalid/);
  for (const value of [NaN, Infinity, -1, 1.5]) {
    assert.throws(() => captureOpeningAttemptStart({ wall: () => value, monotonic: () => 0 }));
  }
});

test("proof binds this execution's receipt time, preserves prep elapsed, and rejects late publication", () => {
  let wall = start, mono = 0;
  const captured = captureOpeningAttemptStart({ wall: () => wall, monotonic: () => mono });
  wall += MINUTE; mono += MINUTE;
  const executionStartedAt = new Date(wall).toISOString(), clock = captured.start(origin);
  wall += MINUTE; mono += MINUTE;
  const values = { admission: clock.admission, precommit: clock.observe() };
  const binding = { origin, executionReceivedAt: captured.receivedAt, executionStartedAt, createdAt: new Date(wall).toISOString() };
  assert.doesNotThrow(() => assertOpeningDeadlineProof(values, binding));
  for (const change of [{ elapsedMs: 0 }, { remainingMs: 25 * MINUTE }, { state: "deadline-exceeded" },
    { kind: "guided-proposal-deadline-observation" }, { excludedUserWaitMs: 0 }]) {
    assert.throws(() => assertOpeningDeadlineProof({ ...values, precommit: { ...values.precommit, ...change } }, binding));
  }
  assert.throws(() => assertOpeningDeadlineProof(values, { ...binding, executionReceivedAt: executionStartedAt }));
  assert.throws(() => assertOpeningDeadlineProof(values, { ...binding, createdAt: "2026-09-06T07:25:00.000Z" }));
  assert.throws(() => assertOpeningDeadlineProof({ ...values, admission: { ...values.admission,
    policy: { ...values.admission.policy, requiredDownstreamReserveMs: 55 * MINUTE } } }, binding));
});

test("cross-stage and failed opening retries retain the same durable high-water clock", () => {
  const dir = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-opening-clock-"))), guard = () => {};
  try {
    let wall = start;
    const compile = startGuardedProposalDeadline({ dir, origin, executionId: randomUUID(), guard },
      { wall: () => wall, monotonic: () => wall - start });
    wall += 9 * MINUTE; compile.observe();
    const opening = (at: number) => guardGenerationAttempt({ dir, origin, executionId: randomUUID(), guard },
      captureOpeningAttemptStart({ wall: () => at, monotonic: () => 0 }).start(origin));
    assert.throws(opening(start + 8 * MINUTE).remainingMs, /across attempts/);
    assert.equal(opening(start + 10 * MINUTE).remainingMs(), 25 * MINUTE);
    assert.throws(opening(start + 9 * MINUTE).remainingMs, /across attempts/);
    assert.throws(opening(start + 16 * MINUTE).remainingMs, /not-admitted/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
