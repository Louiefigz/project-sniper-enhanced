import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import type { ChildProcess } from "node:child_process";
import {
  processTreeTarget,
  shouldDetachProcessGroup,
  terminateProcessTree,
} from "../../../app/api/_lib/child-process-lifecycle";

function fakeChild(pid = 123): ChildProcess {
  const child = new EventEmitter() as ChildProcess;
  Object.assign(child, { pid, kill: () => true });
  return child;
}

assert.equal(processTreeTarget(123, "darwin"), -123);
assert.equal(processTreeTarget(123, "linux"), -123);
assert.equal(processTreeTarget(123, "win32"), 123);
assert.throws(() => processTreeTarget(0, "linux"), /positive integer/);
assert.equal(shouldDetachProcessGroup("darwin"), true);
assert.equal(shouldDetachProcessGroup("win32"), false);

{
  const signals: Array<[number, NodeJS.Signals | 0]> = [];
  let escalation: (() => void) | undefined;
  let delay = 0;
  let unrefCalled = false;
  const result = terminateProcessTree(fakeChild(), 456, {
    platform: "linux",
    signal: (target, signal) => { signals.push([target, signal]); },
    alive: () => true,
    schedule: (callback, delayMs) => {
      escalation = callback;
      delay = delayMs;
      return { unref: () => { unrefCalled = true; } } as ReturnType<typeof setTimeout>;
    },
  });
  assert.deepEqual(result, { termSent: true, escalationScheduled: true });
  assert.equal(delay, 456);
  assert.equal(unrefCalled, true);
  assert.deepEqual(signals, [[-123, "SIGTERM"]]);
  escalation?.();
  assert.deepEqual(signals, [[-123, "SIGTERM"], [-123, "SIGKILL"]]);
}

{
  const signals: Array<[number, NodeJS.Signals | 0]> = [];
  let escalation: (() => void) | undefined;
  terminateProcessTree(fakeChild(), 10, {
    platform: "win32",
    signal: (target, signal) => { signals.push([target, signal]); },
    alive: () => false,
    schedule: (callback) => {
      escalation = callback;
      return { unref: () => {} } as ReturnType<typeof setTimeout>;
    },
  });
  escalation?.();
  assert.deepEqual(signals, [[123, "SIGTERM"]], "an exited process is not hard-killed");
}

console.log("child-process-lifecycle.test.ts: all assertions passed");
