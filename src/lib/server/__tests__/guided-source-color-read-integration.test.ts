/** Actual metadata readers, leases and two CASes; no media, source, runtime or executable qualification. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import childProcess from "node:child_process";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import test from "node:test";
import { assertOpeningCleanupMetadata } from "../guided-opening-cleanup-store";
import { assertSourceColorOpeningResultMetadata } from "../guided-source-color-opening-result";
import { assertSourceColorReadInvocation } from "../guided-source-color-read-transport";
import { invokeOpeningChild } from "../guided-opening-process";
import { replaceReadIntegrationArchive, sourceColorReadIntegrationFixture } from "./_guided-source-color-read-integration-fixture";

test("actual SAME-held final cleanup and result create an exact metadata-only cold invocation", async t => {
  const f = await sourceColorReadIntegrationFixture(t);
  assert.equal(f.cleanup.receipt.claimRetained, false); assert.equal(f.cleanup.receipt.phase, "retired");
  assert.equal(f.calls.length, 1); assert.equal(f.selected.sourceBytesObserved, false); assert.equal(f.selected.mediaBytesObserved, false);
  assert.equal(f.selected.mediaSelected, false); assert.equal(f.selected.completion.deliveryApproved, false);
  assert(Object.isFrozen(f.invocation)); assert(Object.isFrozen(f.invocation.args)); assert(Object.isFrozen(f.invocation.environment));
  assert.deepEqual(f.invocation.args, ["--receipt-sha256", f.selected.record.sha256, "--receipt-hash", f.selected.completion.receiptHash,
    "--source-color-input", f.staged.input.path, "--source-color-input-sha256", f.staged.input.sha256,
    "--source-color-reservation-archive", f.recorded.fact.archive.path,
    "--source-color-reservation-archive-sha256", f.recorded.fact.archive.sha256]);
  assert.equal(f.invocation.environment.PATH, path.dirname(f.media.tools.tools.python.path));
  for (const [name, value] of Object.entries(f.invocation.environment)) if (name !== "PATH") assert.equal(value, undefined);
  assert(!fs.existsSync(f.staged.reservation.path));
  assert.doesNotThrow(() => assertOpeningCleanupMetadata(f.cleanup));
  assert.doesNotThrow(() => assertSourceColorOpeningResultMetadata(f.selected, f.cleanup.held));
  assert.doesNotThrow(() => assertSourceColorReadInvocation(f.invocation, f.cleanup.held));
  assert.throws(() => assertSourceColorReadInvocation({ ...f.invocation }, f.cleanup.held), /actual original/);
  assert.throws(() => assertSourceColorReadInvocation(f.invocation, { ...f.cleanup.held }), /actual original/);
});

test("actual transport retains its original raw result Buffer after the hold returns", async t => {
  const f = await sourceColorReadIntegrationFixture(t), bytes = fs.readFileSync(f.media.file);
  assert(Buffer.isBuffer(f.selected.record.bytes)); f.selected.record.bytes[0] ^= 1;
  assert.deepEqual(fs.readFileSync(f.media.file), bytes);
  assert.throws(() => assertSourceColorReadInvocation(f.invocation, f.cleanup.held), /metadata|bytes/);
});

test("actual transport refuses same-byte replacement of the final reservation archive", async t => {
  const f = await sourceColorReadIntegrationFixture(t), file = f.recorded.fact.archive.path, bytes = fs.readFileSync(file);
  replaceReadIntegrationArchive(f); assert.deepEqual(fs.readFileSync(file), bytes);
  assert.throws(() => assertSourceColorReadInvocation(f.invocation, f.cleanup.held), /identity|metadata|changed/);
});

test("genuine read transport cannot select its differently pinned media worker before any child", async t => {
  const f = await sourceColorReadIntegrationFixture(t); let native = 0, remaining = 0;
  t.mock.method(childProcess, "spawn", () => { native++; throw new Error("TEST forbidden child frontier"); });
  await assert.rejects(async () => invokeOpeningChild({ held: f.cleanup.held, sourceColorRead: f.invocation, kind: "read",
    tools: f.media.tools.process, remainingMs: () => { remaining++; return 1000; } }), /read.*(worker|script|pin|tools)|exact.*read|original.*tool/i);
  assert.equal(native, 0); assert.equal(remaining, 0);
  assert.doesNotThrow(() => assertSourceColorReadInvocation(f.invocation, f.cleanup.held));
});

for (const extra of [false, true]) {
  test(`genuine read refuses ${extra ? "extra tool keys" : "a different interpreter with its matching inert file hash"}`, async t => {
    const f = await sourceColorReadIntegrationFixture(t); let native = 0, remaining = 0;
    t.mock.method(childProcess, "spawn", () => { native++; throw new Error("TEST forbidden child frontier"); });
    const other = f.media.tools.tools.ffmpeg;
    const tools = extra ? { ...f.media.tools.read, TEST_extra: true }
      : { ...f.media.tools.read, python: other.path, pythonResolved: other.path, pythonHash: other.sha256 };
    await assert.rejects(async () => invokeOpeningChild({ held: f.cleanup.held, sourceColorRead: f.invocation, kind: "read",
      tools, remainingMs: () => { remaining++; return 1000; } }), /read.*tools|original.*tool/i);
    assert.equal(native, 0); assert.equal(remaining, 0);
  });
}

test("genuine transport reaches only the exact pinned read argv with no Docker environment using a pid-less TEST child", async t => {
  const f = await sourceColorReadIntegrationFixture(t), calls: unknown[][] = [];
  t.mock.method(childProcess, "spawn", (...args: unknown[]) => {
    calls.push(args);
    const child = Object.assign(new EventEmitter(), { stdout: new PassThrough(), stderr: new PassThrough() });
    queueMicrotask(() => { child.stdout.write("TEST no native readback"); child.emit("close", 0, null); });
    return child as unknown as childProcess.ChildProcess;
  });
  const result = await invokeOpeningChild({ held: f.cleanup.held, sourceColorRead: f.invocation,
    kind: "read", tools: f.media.tools.read, remainingMs: () => 1000 });
  assert.equal(result.stdout, "TEST no native readback"); assert.equal(calls.length, 1);
  assert.equal(calls[0][0], f.media.tools.read.python);
  assert.deepEqual(calls[0][1], [f.media.tools.read.script, f.cleanup.held.claim.inputPath, f.cleanup.held.claim.outputRoot,
    "--input-sha256", f.cleanup.held.claim.inputSha256, "--execution-claim", f.cleanup.held.claimPath,
    "--execution-claim-sha256", f.cleanup.held.claimSha256, ...f.invocation.args, "--timeout-seconds", "0.75"]);
  const env = (calls[0][2] as childProcess.SpawnOptions).env!;
  assert.equal(env.PATH, f.invocation.environment.PATH); assert.equal(env.SNIPER_DOCKER_SOCKET, undefined);
  assert.equal(env.DOCKER_HOST, undefined); assert.equal(env.DOCKER_CONFIG, undefined);
});
