/** Pure deferred callback sequencing; no files, native tools, resource ownership or valid cleanup evidence. */
import assert from "node:assert/strict";
import test from "node:test";
import { CleanupPendingReadHold } from "../guided-source-color-cleanup-pending-hold";

test("deferred admission calls original guard/remainder only after complete child capture, exactly once", () => {
  const events: string[] = [];
  const hold = new CleanupPendingReadHold({ dir: "/TEST/producer", guard: () => { events.push("guard"); },
    remainingMs: () => { events.push("remaining"); return 1000; } });
  const result = hold.runAfterCapture(() => {
    events.push("child-captured"); hold.enterAfterCapture(); hold.enterAfterCapture();
    assert(hold.remaining() > 0); events.push("child-finished"); return "TEST data only";
  });
  assert.equal(result, "TEST data only"); assert.deepEqual(events, ["child-captured", "guard", "remaining", "child-finished"]);
  assert.throws(hold.enterAfterCapture, /no original active capture/); assert.throws(hold.remaining, /no original active remainder/);
});

test("deferred omission and recursive initial admission fail instead of minting an unheld child baseline", () => {
  let guards = 0;
  const hold = new CleanupPendingReadHold({ dir: "/TEST/producer", guard: () => { guards++; }, remainingMs: () => 1000 });
  assert.throws(() => hold.runAfterCapture(() => "TEST omitted child guard"), /no original active remainder/);
  assert.equal(guards, 0);
  assert.throws(() => hold.runAfterCapture(() => hold.runAfterCapture(() => "TEST nested")), /cannot reenter/);
  assert.throws(() => hold.runAfterCapture(() => hold.run(() => "TEST nested")), /cannot reenter/);
  assert.equal(guards, 0);
  hold.runAfterCapture(() => { hold.enterAfterCapture(); }); assert.equal(guards, 1);
});

test("recursive caller guard cannot readmit before the first original remainder exists", () => {
  const hold: CleanupPendingReadHold = new CleanupPendingReadHold({ dir: "/TEST/producer", guard: () => { hold.enterAfterCapture(); }, remainingMs: () => 1000 });
  assert.throws(() => hold.runAfterCapture(() => hold.enterAfterCapture()), /original protected deadline expired/);
  assert.throws(hold.remaining, /no original active remainder/);
});

test("both original callback failures clear deferred state without skipping or retrying callbacks", () => {
  for (const field of ["guard", "remaining"] as const) {
    let guards = 0, remaining = 0;
    const hold = new CleanupPendingReadHold({ dir: "/TEST/producer", guard: () => { guards++; if (field === "guard") throw new Error("TEST guard"); },
      remainingMs: () => { remaining++; throw new Error("TEST remaining"); } });
    assert.throws(() => hold.runAfterCapture(() => hold.enterAfterCapture()), /TEST/);
    assert.equal(guards, 1); assert.equal(remaining, field === "guard" ? 0 : 1);
    assert.throws(hold.enterAfterCapture, /no original active capture/);
  }
});

test("subsequent retained revalidation uses original run semantics without an independent child clock", () => {
  let guards = 0, remaining = 0;
  const hold = new CleanupPendingReadHold({ dir: "/TEST/producer", guard: () => { guards++; },
    remainingMs: () => { remaining++; return 1000; } });
  hold.runAfterCapture(() => hold.enterAfterCapture());
  hold.run(() => { hold.enterAfterCapture(); hold.check(); });
  assert.equal(guards, 2); assert.equal(remaining, 2);
});

test("original absolute remainder rejects expiry during child capture and final bookkeeping", t => {
  let now = 1000;
  t.mock.method(performance, "now", () => now);
  const hold = new CleanupPendingReadHold({ dir: "/TEST/producer", guard: () => {}, remainingMs: () => 2000 - now });
  assert.throws(() => hold.runAfterCapture(() => { now = 2001; hold.enterAfterCapture(); }), /remainder is invalid/);
  now = 1000;
  assert.throws(() => hold.runAfterCapture(() => { hold.enterAfterCapture(); now = 2001; }), /original protected deadline expired/);
});
