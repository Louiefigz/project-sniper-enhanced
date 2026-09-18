import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import type { ChildProcessWithoutNullStreams } from "node:child_process";
import test from "node:test";
import { privateStderr, watchGradeProcess, type GradeProcessControls } from "../grade-observation-process";

function fixture(identity = true) {
  const child = Object.assign(new EventEmitter(), { stdin: new PassThrough(), stdout: new PassThrough(), stderr: new PassThrough() });
  let now = BigInt(10_000_000_000), valid = identity;
  const timers: { callback: () => void; ms: number; cleared: boolean }[] = [], signals: string[] = [];
  const controls: GradeProcessControls = { identity: () => valid, now: () => now,
    signal: value => { signals.push(value); }, groupAlive: () => false,
    timer: (callback, ms) => { const timer = { callback, ms, cleared: false }; timers.push(timer); return timer as never; },
    clear: value => { (value as unknown as typeof timers[number]).cleared = true; } };
  const promise = watchGradeProcess({ root: "/unused", directory: "/unused", inputHash: "a".repeat(64),
    deadline: BigInt(120_000_000_000) }, child as unknown as ChildProcessWithoutNullStreams, controls);
  const ready = () => child.stdout.emit("data", Buffer.from('{"readyMonotonicNs":"8000000000000"}\n'));
  const close = (status = "complete") => {
    child.stdout.emit("data", Buffer.from(JSON.stringify({ resultSha256: "a".repeat(64), status, cleanupVerified: true })));
    child.emit("close", 0, null);
  };
  return { child, promise, timers, signals, ready, close, setIdentity: (value: boolean) => { valid = value; },
    setNow: (value: bigint) => { now = value; } };
}

test("missing exact process identity settles even if child never closes, without handshake or kill", async () => {
  const f = fixture(false);
  const result = await f.promise;
  assert.equal(result.status, "interrupted"); assert.equal(result.cleanupVerified, false);
  assert.equal(result.failure?.reason, "identity-unavailable-before-handshake");
  assert.equal(result.handshake, null); assert.deepEqual(f.signals, []);
  assert(f.child.stdin.destroyed); assert(f.child.stdout.destroyed);
});
test("original remaining work and cleanup reserve are independent timers, not a fresh lifecycle", async () => {
  const f = fixture(); f.ready();
  assert.deepEqual(f.timers.map(timer => timer.ms), [5000, 110_000, 210_000]);
  f.setNow(BigInt(120_000_000_000)); f.timers[1].callback();
  assert.deepEqual(f.signals, ["SIGUSR1"]);
  f.close("failed");
  const result = await f.promise;
  assert.equal(result.status, "failed"); assert.equal(result.cleanupVerified, true);
  assert(f.timers.every(timer => timer.cleared));
});
test("late complete output is rejected even when child claims clean completion", async () => {
  const f = fixture(); f.ready(); f.setNow(BigInt(121_000_000_000)); f.close();
  const result = await f.promise;
  assert.equal(result.status, "interrupted"); assert.equal(result.resultSha256, null);
});
test("lifecycle ceiling settles an unresponsive child with lost identity and retains uncertainty", async () => {
  const f = fixture(); f.ready(); f.setIdentity(false);
  f.timers[2].callback();
  const result = await f.promise;
  assert.equal(result.status, "interrupted"); assert.equal(result.cleanupVerified, false);
  assert.equal(result.failure?.reason, "lifecycle-deadline");
  assert.deepEqual(f.signals, []); assert(f.child.stderr.destroyed);
});
test("oversize stdout invalidates before retaining bytes and ignores all later output", async () => {
  const f = fixture(); f.ready(); f.setIdentity(false);
  f.child.stdout.emit("data", Buffer.alloc(128 * 1024));
  const result = await f.promise;
  for (let index = 0; index < 1000; index++) f.child.stdout.emit("data", Buffer.alloc(1024));
  assert.equal(result.status, "interrupted"); assert.equal(f.child.stdout.listenerCount("data"), 0);
  assert.equal(result.failure?.reason, "output-limit");
  assert.deepEqual(f.signals, []); assert(f.child.stdout.destroyed);
});
test("private stderr is terminal-safe and byte-bounded without changing failure or cleanup state", async () => {
  const f = fixture(); f.ready();
  const raw = Buffer.from("\u001b[31mdecoder failed\u001b[0m\u0000\n" + "界".repeat(8000));
  f.child.stderr.emit("data", raw); f.child.emit("close", 7, null);
  const result = await f.promise, failure = result.failure;
  assert(failure); assert.equal(failure.reason, "worker-exit"); assert.equal(failure.exitCode, 7);
  assert.equal(failure.cleanupState, "unverified"); assert.equal(result.cleanupVerified, false);
  assert.equal(failure.stderrTruncated, true); assert(Buffer.byteLength(failure.stderr) <= 4096);
  assert(failure.stderr.startsWith("decoder failed\n")); assert(!failure.stderr.includes("\u001b"));
  assert(!failure.stderr.includes("\u0000")); assert(Buffer.byteLength(privateStderr(raw)) <= 4096);
});
test("identity loss at handshake never authorizes a decoder launch", async () => {
  const f = fixture(); f.setIdentity(false); f.ready();
  const result = await f.promise;
  assert.equal(result.handshake, null); assert.equal(result.cleanupVerified, false); assert.deepEqual(f.signals, []);
});
test("successful live return is selectable only before original work deadline", async () => {
  const f = fixture(); f.ready(); f.close();
  const result = await f.promise;
  assert.equal(result.status, "complete"); assert.equal(result.resultSha256, "a".repeat(64));
  assert.equal(result.handshake?.remainingMs, 110_000); assert.deepEqual(f.signals, []);
});
