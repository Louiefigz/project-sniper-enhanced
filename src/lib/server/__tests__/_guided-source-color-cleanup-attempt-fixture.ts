/** Actual writer/process/reader records; native/tool/stopped admission and elapsed time are TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { recordSourceColorCleanupAttempt, type SourceColorCleanupAttemptInput } from "../guided-source-color-cleanup-attempt";
import { runSourceColorCleanupProcess } from "../guided-source-color-cleanup-process";
import { readSourceColorCleanupAttempt } from "../guided-source-color-cleanup-attempt-read";
import { cleanupAttemptPreRecordFixture } from "./_guided-source-color-cleanup-attempt-read-fixture";

/** Start one virtual enclosing TEST clock after fixture setup; never represent its value as measured native time. */
export function cleanupAttemptWriterFixture(t: TestContext, f = cleanupAttemptPreRecordFixture(t)) {
  const timing = { elapsed: 0, completed: 4100 };
  const callbacks = { guard: () => {}, remaining: () => {}, elapsed: () => {} };
  const counts = { guard: 0, remaining: 0, elapsed: 0, run: 0, read: 0 };
  const input: SourceColorCleanupAttemptInput = { held: f.input.held, reservation: f.input.reservation,
    attemptId: f.input.attemptId, guard: () => { counts.guard++; callbacks.guard(); }, clock: {
      receivedAt: new Date().toISOString(),
      remainingMs: () => { counts.remaining++; callbacks.remaining(); return 300_000 - timing.elapsed; },
      elapsedMs: () => { counts.elapsed++; callbacks.elapsed(); return timing.elapsed; },
    } };
  f.events.afterInvoke = () => { timing.elapsed = timing.completed; };
  const dependencies = { stopped: f.dependencies.stopped,
    run: async (value: Parameters<typeof runSourceColorCleanupProcess>[0]) => {
      counts.run++; return runSourceColorCleanupProcess(value, f.dependencies);
    }, read: (value: Parameters<typeof readSourceColorCleanupAttempt>[0]) => {
      counts.read++; return readSourceColorCleanupAttempt(value, f.readerDependencies);
    } };
  const activeBytes = fs.readFileSync(f.staged.reservation.path);
  const activeIdentity = fs.lstatSync(f.staged.reservation.path, { bigint: true });
  return { ...f, writerInput: input, writerDependencies: dependencies, timing, counts, clockCallbacks: callbacks,
    activeBytes, activeIdentity, write: () => recordSourceColorCleanupAttempt(input, dependencies) };
}
export type CleanupAttemptWriterFixture = ReturnType<typeof cleanupAttemptWriterFixture>;

/** Check original active bytes/inode and actual TEMP lease, without creating retirement authority. */
export function assertWriterRetained(f: CleanupAttemptWriterFixture): void {
  assert.deepEqual(fs.readFileSync(f.staged.reservation.path), f.activeBytes);
  const actual = fs.lstatSync(f.staged.reservation.path, { bigint: true });
  assert.equal(actual.dev, f.activeIdentity.dev); assert.equal(actual.ino, f.activeIdentity.ino);
  f.staging.resource.assertResource();
  assert(!fs.existsSync(path.join(f.directory, "retirement-ack.json")));
}

/** Only the exact canonical TEST output can be replaced, even when a callback supplies the fault. */
export function replaceWriterOutput(f: CleanupAttemptWriterFixture): void {
  const file = path.join(f.directory, "output.json"), root = fs.realpathSync(f.staging.root);
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(f.directory, `TEST-output-replacement-${randomUUID()}.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

/** Raw file facts are derived from actual writer bytes, not reserialized expectations. */
export function writerRawRecord(f: CleanupAttemptWriterFixture, name: "start" | "invocation" | "output") {
  const file = path.join(f.directory, `${name}.json`), bytes = fs.readFileSync(file);
  return { file, bytes, sha256: createHash("sha256").update(bytes).digest("hex"), value: JSON.parse(bytes.toString("utf8")) };
}
