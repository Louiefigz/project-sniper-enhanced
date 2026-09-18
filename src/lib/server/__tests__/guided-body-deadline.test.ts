import assert from "node:assert/strict";
import { test } from "node:test";
import { bodyDeadlineAdmission, captureBodyAttemptStart, captureBodyVerifierRemainder,
  assertBodyDeadlineProof, assertBodyVerifierRemainderCurrent, BODY_DEADLINE_POLICY } from "../guided-body-deadline";

const origin = { clockHash: "a".repeat(64), startedAt: "2026-09-07T12:00:00.000Z" };
const began = Date.parse(origin.startedAt), minute = 60_000;

test("body verifier captures one25minute ceiling and floors the actual remaining milliseconds", () => {
  let mono = 100;
  const remaining = captureBodyVerifierRemainder(() => 55 * minute, () => mono);
  assert.equal(remaining(), 25 * minute);
  mono += 10 * minute + 0.25;
  assert.equal(remaining(), 15 * minute - 1);
  mono += 15 * minute;
  assert.throws(remaining, /subdeadline/);
  mono = 100;
  assert.throws(remaining, /subdeadline/, "expired verifier cannot reset on a later call");
});

test("body verifier never enlarges a smaller initial parent remainder or ignores parent expiry", () => {
  let parent = 5000.75, mono = 100;
  const remaining = captureBodyVerifierRemainder(() => parent, () => mono);
  parent = 55 * minute; mono += 1000;
  assert.equal(remaining(), 4000);
  parent = 900.25;
  assert.equal(remaining(), 900);
  parent = 0;
  assert.throws(remaining, /subdeadline/);
  parent = 55 * minute;
  assert.throws(remaining, /subdeadline/);
});

test("body verifier fails closed for malformed clocks, thrown parent probes and rollback", () => {
  for (const bad of [NaN, Infinity, -1, Number.MAX_SAFE_INTEGER + 1, 0, 0.5]) {
    assert.throws(() => captureBodyVerifierRemainder(() => bad, () => 100));
  }
  let parent = 55 * minute, mono = 100;
  const remaining = captureBodyVerifierRemainder(() => parent, () => mono);
  parent = NaN; assert.throws(remaining); parent = 55 * minute;
  assert.throws(remaining, /subdeadline/);
  const rollback = captureBodyVerifierRemainder(() => parent, () => mono);
  mono -= 1; assert.throws(rollback, /subdeadline/); mono += 2;
  assert.throws(rollback, /subdeadline/);
  let fail = false;
  const throwing = captureBodyVerifierRemainder(() => { if (fail) throw new Error("TEST parent expired"); return parent; });
  fail = true; assert.throws(throwing, /parent expired/); fail = false;
  assert.throws(throwing, /subdeadline/);
});

test("body verifier counts time consumed by parent checks, not only time between calls", () => {
  let mono = 100;
  const remaining = captureBodyVerifierRemainder(() => { mono += 1000; return 55 * minute; }, () => mono);
  assert.equal(remaining(), 25 * minute - 2000);
});

test("body finite tail never reenters the original parent callback", () => {
  let mono = 100, calls = 0;
  const remaining = captureBodyVerifierRemainder(() => { calls++; return 1000; }, () => mono);
  remaining(); const before = calls;
  mono += 10; assertBodyVerifierRemainderCurrent(remaining); assert.equal(calls, before);
  mono = 1100; assert.throws(() => assertBodyVerifierRemainderCurrent(remaining), /exhausted/);
  assert.equal(calls, before);
});

test("body finite tail retains the earliest lower parent sample even after a larger later sample", () => {
  let mono = 100, parent = 5000;
  const remaining = captureBodyVerifierRemainder(() => parent, () => mono);
  mono = 200; parent = 500; assert.equal(remaining(), 500);
  mono = 300; parent = 5000; assert.equal(remaining(), 400);
  mono = 700; assert.throws(() => assertBodyVerifierRemainderCurrent(remaining), /exhausted/);
});

test("body finite tail rollback remains poisoned when the monotonic clock recovers", () => {
  let mono = 100;
  const remaining = captureBodyVerifierRemainder(() => 1000, () => mono);
  mono = 200; assertBodyVerifierRemainderCurrent(remaining);
  mono = 199; assert.throws(() => assertBodyVerifierRemainderCurrent(remaining), /exhausted/);
  mono = 201; assert.throws(() => assertBodyVerifierRemainderCurrent(remaining), /exhausted/);
  assert.throws(remaining, /exhausted/);
});

test("body finite tail authenticates the exact original closure without invoking copies", () => {
  let calls = 0;
  const remaining = captureBodyVerifierRemainder(() => { calls++; return 1000; }, () => 100);
  const copied = () => remaining(), bound = remaining.bind(null), before = calls;
  for (const candidate of [copied, bound, () => 1000]) {
    assert.throws(() => assertBodyVerifierRemainderCurrent(candidate), /actual original/);
  }
  assert.equal(calls, before); assertBodyVerifierRemainderCurrent(remaining); assert.equal(calls, before);
});

test("body admission reserves all finish work inside original120, with no asset or human-wait credit", () => {
  const at40 = bodyDeadlineAdmission(origin, began + 40 * minute);
  assert.equal(at40.admitted, true); assert.equal(at40.attemptDeadlineAt, "2026-09-07T13:35:00.000Z");
  assert.equal(at40.requestDeadlineAt, "2026-09-07T14:00:00.000Z");
  assert.equal(at40.excludedUserWaitMs, null); assert.equal(at40.policy.preparedAssetCreditMs, 0);
  assert.equal(bodyDeadlineAdmission(origin, began + 40 * minute + 1).admitted, false);
  assert.equal(bodyDeadlineAdmission(origin, began + 121 * minute).admitted, false);
  for (const at of [began - 1, NaN, Infinity, began + 0.5]) assert.throws(() => bodyDeadlineAdmission(origin, at));
});

test("body parse-time wall and monotonic origins are consumed before binding and cannot reset", () => {
  let wall = began, mono = 100;
  const capture = captureBodyAttemptStart({ wall: () => wall, monotonic: () => mono });
  wall += 3 * minute; mono += 3 * minute;
  const budget = capture.start(origin);
  assert.equal(budget.remainingMs(), BODY_DEADLINE_POLICY.wholeAttemptMs - 3 * minute);
  assert.throws(() => capture.start(origin), /cannot renew/);
  mono += 55 * minute;
  assert.throws(budget.remainingMs, /deadline-exceeded/);
});

test("body rollback poisons attempt even if wall time subsequently recovers", () => {
  let wall = began; const mono = 100;
  const budget = captureBodyAttemptStart({ wall: () => wall, monotonic: () => mono }).start(origin);
  budget.remainingMs(); wall -= 1;
  assert.throws(budget.remainingMs, /clock-invalid/); wall += minute;
  assert.throws(budget.remainingMs, /clock-invalid/);
});

test("retained body budget proves exact receive/start/commit and rejects expiry or opening-policy substitution", () => {
  let wall = began, mono = 100;
  const captured = captureBodyAttemptStart({ wall: () => wall, monotonic: () => mono }), budget = captured.start(origin);
  wall += 1_000; mono += 1_000;
  const values = { admission: budget.admission, precommit: budget.observe() };
  const binding = { origin, executionReceivedAt: captured.receivedAt,
    executionStartedAt: captured.receivedAt, createdAt: new Date(wall).toISOString() };
  assert.doesNotThrow(() => assertBodyDeadlineProof(values, binding));
  for (const patch of [{ createdAt: "2026-09-07T12:55:00.000Z" }, { executionReceivedAt: "2026-09-07T12:00:00.001Z" },
    { executionStartedAt: "2026-09-07T12:01:00.000Z" }, { origin: { ...origin, clockHash: "b".repeat(64) } }]) {
    assert.throws(() => assertBodyDeadlineProof(values, { ...binding, ...patch }));
  }
  assert.throws(() => assertBodyDeadlineProof({ ...values, admission: { ...values.admission, excludedUserWaitMs: minute } }, binding));
});
