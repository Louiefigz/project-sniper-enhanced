import assert from "node:assert/strict";
import { test } from "node:test";
import { currentCallerProcessDeadline, withCallerProcessDeadline } from "../caller-process-deadline";

test("absent scope is unchanged; each declared ceiling and live ancestor only tightens", async () => {
  assert.equal(currentCallerProcessDeadline(), null);
  let left = 500;
  await withCallerProcessDeadline({ remainingMs: () => left, maxChildMs: 400 }, async () => {
    assert.equal(currentCallerProcessDeadline()!.timeoutMs, 400);
    await withCallerProcessDeadline({ remainingMs: () => 900, maxChildMs: 800 }, async () => {
      assert.equal(currentCallerProcessDeadline()!.timeoutMs, 400);
      left = 120;
      assert.equal(currentCallerProcessDeadline()!.timeoutMs, 120);
    });
    await withCallerProcessDeadline({ remainingMs: () => 100, maxChildMs: 50 }, async () => {
      assert.equal(currentCallerProcessDeadline()!.timeoutMs, 50);
    });
  });
  assert.equal(currentCallerProcessDeadline(), null);
});

test("invalid/increasing/expired clocks poison rather than regain credit", async () => {
  for (const value of [0, -1, NaN, Infinity, 0.1]) {
    await assert.rejects(withCallerProcessDeadline({ remainingMs: () => value, maxChildMs: 100 }, async () => undefined), /expired or invalid/);
  }
  let left = 100;
  await assert.rejects(withCallerProcessDeadline({ remainingMs: () => left, maxChildMs: 100 }, async () => {
    left = 101;
    assert.throws(currentCallerProcessDeadline, /regain/);
    left = 90;
    assert.throws(currentCallerProcessDeadline, /failed/);
  }), /failed/);
});

test("a stale handed child remainder cannot replace or extend the original parent", async () => {
  let left = 1000;
  await assert.rejects(withCallerProcessDeadline({ remainingMs: () => left, maxChildMs: 60000 }, async () => {
    const handed = currentCallerProcessDeadline()!.timeoutMs;
    left = 25;
    assert.equal(Math.min(handed, currentCallerProcessDeadline()!.timeoutMs), 25);
    left = 0;
    assert.throws(currentCallerProcessDeadline, /expired/);
  }), /failed/);
});

test("cancelled ancestors remain cancelled in nested scopes", async () => {
  const controller = new AbortController();
  await assert.rejects(withCallerProcessDeadline({ remainingMs: () => 100, maxChildMs: 100, signal: controller.signal }, async () => {
    await withCallerProcessDeadline({ remainingMs: () => 100, maxChildMs: 100 }, async () => {
      const observed = currentCallerProcessDeadline()!;
      controller.abort();
      assert.equal(observed.signal.aborted, true);
      assert.throws(currentCallerProcessDeadline, /cancelled/);
    });
  }), /failed|cancelled/);
});

test("closed scopes reject escaped callbacks and final expiry rejects a successful value", async () => {
  let escaped!: Promise<void>;
  await withCallerProcessDeadline({ remainingMs: () => 100, maxChildMs: 100 }, async () => {
    escaped = new Promise((resolve) => setImmediate(() => {
      assert.throws(currentCallerProcessDeadline, /closed/); resolve();
    }));
  });
  await escaped;
  let left = 100;
  await assert.rejects(withCallerProcessDeadline({ remainingMs: () => left, maxChildMs: 100 }, async () => {
    left = 0; return "not-a-success";
  }), /expired/);
});
