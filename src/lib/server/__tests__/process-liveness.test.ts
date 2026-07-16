import assert from "node:assert/strict";
import {
  captureProcessIdentity,
  durableProcessAlive,
  durableProcessGroupAlive,
  type ProcessIdentityProbe,
} from "../process-liveness";

const NOW = Date.parse("2026-07-12T18:00:00.000Z");
const FRESH = "2026-07-12T17:59:30.000Z";

function probe(overrides: Partial<ProcessIdentityProbe> = {}): ProcessIdentityProbe {
  return {
    bootSession: () => "boot-a",
    processStart: () => "start-a",
    processAlive: () => true,
    processGroupAlive: () => true,
    ...overrides,
  };
}

const identity = captureProcessIdentity(42, probe());
assert.deepEqual(identity, { pid: 42, bootSession: "boot-a", startToken: "start-a" });
const current = captureProcessIdentity(process.pid);
assert.equal(durableProcessAlive(process.pid, current, new Date().toISOString()), true,
  "the system probe recognizes the current process identity");
assert.equal(durableProcessAlive(42, identity, FRESH, { now: NOW, probe: probe() }), true);
assert.equal(durableProcessAlive(42, identity, FRESH, {
  now: NOW,
  probe: probe({ processStart: () => "start-b" }),
}), false, "same live PID with a new start time is a different process");
assert.equal(durableProcessAlive(42, identity, FRESH, {
  now: NOW,
  probe: probe({ bootSession: () => "boot-b" }),
}), false, "a reboot invalidates every persisted PID");
assert.equal(durableProcessAlive(42, identity, FRESH, {
  now: NOW,
  probe: probe({ processStart: () => undefined }),
}), true, "a transient start-time probe failure falls back to a fresh live PID");
assert.equal(durableProcessAlive(42, identity, FRESH, {
  now: NOW,
  probe: probe({ bootSession: () => undefined }),
}), true, "a transient boot-session probe failure falls back to a fresh live PID");
assert.equal(durableProcessAlive(42, identity, "2026-07-12T16:00:00.000Z", {
  now: NOW,
  probe: probe(),
}), false, "heartbeat ceiling fences a silent live process");
assert.equal(durableProcessGroupAlive(42, identity, "2026-07-12T16:00:00.000Z", {
  now: NOW,
  probe: probe(),
}), false, "the heartbeat ceiling also prevents a same-boot group-id wedge");
assert.equal(durableProcessAlive(42, { pid: 42 }, FRESH, {
  now: NOW,
  probe: probe({ bootSession: () => undefined, processStart: () => undefined }),
}), true, "unsupported hosts retain fresh PID fallback behavior");

assert.equal(durableProcessGroupAlive(42, identity, FRESH, {
  now: NOW,
  probe: probe({ processAlive: () => false, processGroupAlive: () => true }),
}), true, "an original child may keep the recorded process group alive");
assert.equal(durableProcessGroupAlive(42, identity, FRESH, {
  now: NOW,
  probe: probe({ processAlive: () => false, bootSession: () => "boot-b" }),
}), false, "a reused group id after reboot is fenced");
assert.equal(durableProcessGroupAlive(42, identity, FRESH, {
  now: NOW,
  probe: probe({ processAlive: () => false, bootSession: () => undefined }),
}), true, "a transient boot probe failure does not orphan a fresh live process group");

console.log("process-liveness.test.ts: all assertions passed");
