/** No native cleanup: actual staged/raw records and parsers, explicit TEST admission/timing leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { assertRecordedSourceColorCleanupAttempt, sourceColorCleanupAttemptDependencies } from "../guided-source-color-cleanup-attempt";
import { readStoppedOpeningProcess } from "../guided-opening-process";
import { runSourceColorCleanupProcess } from "../guided-source-color-cleanup-process";
import { readSourceColorCleanupAttempt } from "../guided-source-color-cleanup-attempt-read";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { cleanupAttemptWriterFixture, assertWriterRetained, replaceWriterOutput, writerRawRecord } from "./_guided-source-color-cleanup-attempt-fixture";

test("writer defaults retain actual process and historical reader boundaries", () => {
  assert.equal(sourceColorCleanupAttemptDependencies.stopped, readStoppedOpeningProcess);
  assert.equal(sourceColorCleanupAttemptDependencies.run, runSourceColorCleanupProcess);
  assert.equal(sourceColorCleanupAttemptDependencies.read, readSourceColorCleanupAttempt);
});

test("actual writer and reader join exact raw start, invocation, output, archive and prepared fact", async t => {
  const f = cleanupAttemptWriterFixture(t), result = await f.write();
  const start = writerRawRecord(f, "start"), invocation = writerRawRecord(f, "invocation"), output = writerRawRecord(f, "output");
  assert.equal(f.calls.length, 1); assert.equal(f.counts.read, 1);
  assert.equal(result.fact.cleanupStartSha256, start.sha256); assert.equal(result.fact.cleanupInvocationSha256, invocation.sha256);
  assert.equal(result.fact.cleanupOutputSha256, output.sha256); assert.equal(result.factHash, canonicalJsonSha256(result.fact));
  assert.equal(result.fact.cleanupResultHash, canonicalJsonSha256(f.result));
  assert.equal(start.value.processOutcomeSha256, f.actual.receiptSha256); assert.equal(start.value.beforeJournalHash, f.input.held.sha256);
  assert.deepEqual(invocation.value.sourceColor, f.actual.sourceColor); assert.deepEqual(invocation.value.tools, f.tools);
  assert.equal(output.value.invocationSha256, invocation.sha256); assert.equal(output.value.elapsedMs, 4100);
  assert.deepEqual(result.evidence.result, f.result); assert.deepEqual(result.evidence.containerNames, f.input.reservation.containerNames);
  assert.deepEqual(fs.readFileSync(result.fact.archive.path), f.activeBytes); assert.deepEqual(result.fact.reservation, f.staged.reservation);
  assert.equal(result.fact.phase, "awaiting-retirement"); assert.equal(result.fact.claimRetained, true);
  assert.equal(result.evidence.retirementObserved, false); assert.equal(result.fact.mediaSelected, false);
  assert.equal(result.fact.openingApproved, false); assert.equal(result.fact.deliveryApproved, false);
  assert(Object.isFrozen(result.fact)); result.evidence.assertCurrent(); assertWriterRetained(f);
  assert.deepEqual(fs.readdirSync(f.directory).sort(), ["invocation.json", "output.json", "owned-process-ledger.cleanup.jsonl", "prepared.json", "reservation.json", "start.json"]);
});

test("original clock is handed through every process boundary without a new allowance", async t => {
  const f = cleanupAttemptWriterFixture(t); await f.write();
  assert(f.counts.remaining > 10); assert.equal(f.counts.elapsed, 1);
  assert.equal(f.calls[0].held, f.input.held); assert(f.calls[0].remainingMs() <= 295_900);
  assert.equal(writerRawRecord(f, "start").value.receivedAt, f.writerInput.clock.receivedAt);
  assertWriterRetained(f);
});

test("only the actual live recording can be checked for its first journal handoff", async t => {
  const f = cleanupAttemptWriterFixture(t), recorded = await f.write();
  assertRecordedSourceColorCleanupAttempt(recorded);
  assert.throws(() => assertRecordedSourceColorCleanupAttempt({ ...recorded }), /actual live recorded attempt/);
  assert.throws(() => assertRecordedSourceColorCleanupAttempt(JSON.parse(JSON.stringify(recorded))), /actual live recorded attempt/);
  assert.equal(f.calls.length, 1); assertWriterRetained(f);
});

test("a live recording cannot conceal a changed output at journal handoff", async t => {
  const f = cleanupAttemptWriterFixture(t), recorded = await f.write();
  replaceWriterOutput(f);
  assert.throws(() => assertRecordedSourceColorCleanupAttempt(recorded), /original file identity changed/);
  assert.equal(f.calls.length, 1); assertWriterRetained(f);
});

test("a live recording cannot renew the original caller allowance at journal handoff", async t => {
  const f = cleanupAttemptWriterFixture(t), recorded = await f.write();
  f.timing.elapsed = 300_000;
  assert.throws(() => assertRecordedSourceColorCleanupAttempt(recorded), /original protected remainder/);
  assert.equal(f.calls.length, 1); assertWriterRetained(f);
});

test("changed stopped return refuses before start publication and process invocation", async t => {
  const f = cleanupAttemptWriterFixture(t); let observed: typeof f.actual | undefined;
  f.writerDependencies.stopped = () => { observed = structuredClone(f.actual); return observed; };
  f.clockCallbacks.guard = () => { if (observed) observed.receiptSha256 = "0".repeat(64); };
  await assert.rejects(f.write(), /original stopped observation changed/);
  assert.equal(f.counts.run, 0); assert(!fs.existsSync(path.join(f.directory, "start.json"))); assertWriterRetained(f);
});

test("changed stopped return during archive callbacks cannot mint a changed start", async t => {
  const f = cleanupAttemptWriterFixture(t); let observed: typeof f.actual | undefined, afterRead = 0;
  f.writerDependencies.stopped = () => { observed = structuredClone(f.actual); return observed; };
  f.clockCallbacks.guard = () => { if (observed && ++afterRead === 3) observed.receiptSha256 = "0".repeat(64); };
  await assert.rejects(f.write(), /original stopped observation changed/);
  assert(afterRead >= 3); assert.equal(f.counts.run, 0); assert(!fs.existsSync(path.join(f.directory, "start.json"))); assertWriterRetained(f);
});

test("original guard and clock identities cannot be replaced by remaining callbacks", async t => {
  const f = cleanupAttemptWriterFixture(t), input = f.writerInput, clock = input.clock, original = { ...clock }, guard = input.guard;
  const changes = [() => { input.guard = () => {}; }, () => { input.clock = { ...clock }; },
    () => { clock.remainingMs = () => 300_000; }, () => { clock.elapsedMs = () => 4100; },
    () => { clock.receivedAt = "2026-09-08T00:00:03.000Z"; }];
  for (const change of changes) {
    input.clock = clock; input.guard = guard; Object.assign(clock, original); f.clockCallbacks.remaining = change;
    await assert.rejects(f.write(), /original caller metadata changed/);
  }
  assert.equal(f.calls.length, 0); assert.equal(f.counts.run, 0); assertWriterRetained(f);
});

test("invalid original remaining values fail before records and native work", async t => {
  const f = cleanupAttemptWriterFixture(t);
  for (const value of [0, -1, NaN, Infinity, 300_001]) {
    f.writerInput.clock.remainingMs = () => value;
    await assert.rejects(f.write(), /original protected remainder/);
  }
  assert.equal(f.counts.run, 0); assert.deepEqual(fs.readdirSync(f.directory), []); assertWriterRetained(f);
});

test("elapsed callback cannot change original caller after process normal return", async t => {
  const f = cleanupAttemptWriterFixture(t); f.clockCallbacks.elapsed = () => { f.writerInput.guard = () => {}; };
  await assert.rejects(f.write(), /original caller metadata changed/);
  assert.equal(f.calls.length, 1); assert(fs.existsSync(path.join(f.directory, "invocation.json")));
  assert(!fs.existsSync(path.join(f.directory, "output.json"))); assert.equal(f.counts.read, 0); assertWriterRetained(f);
});

test("child elapsed cannot exceed actual enclosing elapsed and leaves partial records intact", async t => {
  const f = cleanupAttemptWriterFixture(t); f.timing.completed = 3998;
  await assert.rejects(f.write(), /child timing exceeds its original enclosing attempt/);
  assert.equal(f.calls.length, 1); assert.equal(f.counts.read, 0); assertWriterRetained(f);
  assert.deepEqual(fs.readdirSync(f.directory).sort(), ["invocation.json", "owned-process-ledger.cleanup.jsonl", "reservation.json", "start.json"]);
});

test("invalid elapsed clock never becomes an owned output", async t => {
  const f = cleanupAttemptWriterFixture(t); f.writerInput.clock.elapsedMs = () => NaN;
  await assert.rejects(f.write(), /elapsed clock is invalid/); assert.equal(f.calls.length, 1);
  assert(!fs.existsSync(path.join(f.directory, "output.json"))); assertWriterRetained(f);
});

test("native-leaf failure retains original error, start, archive, invocation and live lease", async t => {
  const f = cleanupAttemptWriterFixture(t), failure = new CutPreviewProcessError("TEST unknown cleanup settlement", {
    timedOut: true, groupStopped: false, forcedStop: true, stdout: "TEST partial", stderr: "TEST failed" });
  f.dependencies.invoke = async () => { throw failure; };
  await assert.rejects(f.write(), error => error === failure); assert.equal(f.counts.read, 0); assertWriterRetained(f);
  assert.deepEqual(fs.readdirSync(f.directory).sort(), ["invocation.json", "reservation.json", "start.json"]);
});

test("final reader callback cannot substitute already written output with identical bytes", async t => {
  const f = cleanupAttemptWriterFixture(t); let reading = false, callbacks = 0;
  const read = f.writerDependencies.read;
  f.writerDependencies.read = input => { reading = true; return read(input); };
  f.clockCallbacks.guard = () => { if (reading && ++callbacks === 2) replaceWriterOutput(f); };
  await assert.rejects(f.write(), /original file identity changed/); assert.equal(callbacks, 2);
  assert.equal(f.calls.length, 1); assert.equal(f.counts.read, 1); assertWriterRetained(f);
});

test("final reader callback cannot replace held claim metadata after successful process work", async t => {
  const f = cleanupAttemptWriterFixture(t); let reading = false;
  const read = f.writerDependencies.read;
  f.writerDependencies.read = input => { reading = true; return read(input); };
  f.clockCallbacks.guard = () => { if (reading) f.writerInput.held.claimSha256 = "0".repeat(64); };
  await assert.rejects(f.write(), /original caller metadata changed/);
  assert.equal(f.calls.length, 1); assertWriterRetained(f);
});

test("same completed attempt does not replay a second native cleanup", async t => {
  const f = cleanupAttemptWriterFixture(t); await f.write();
  await assert.rejects(f.write(), /exist|already/i); assert.equal(f.calls.length, 1); assertWriterRetained(f);
});
