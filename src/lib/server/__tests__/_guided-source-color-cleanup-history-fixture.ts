/** Actual TEMP records/reads; media admission and original native outcomes are explicit TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { createOpeningRecord } from "../guided-opening-process-activation";
import { readSourceColorCleanupHistory, type SourceColorCleanupHistoryInput } from "../guided-source-color-cleanup-history";
import { cleanupAttemptWriterFixture, writerRawRecord } from "./_guided-source-color-cleanup-attempt-fixture";

const NAMES = ["prepared.json", "start.json", "invocation.json", "output.json", "reservation.json", "owned-process-ledger.cleanup.jsonl"];
type OriginalFixture = Awaited<ReturnType<typeof completedFixture>>;

/** The first prepared.json comes from the actual writer after its actual independent attempt read. */
async function completedFixture(t: TestContext) {
  const f = cleanupAttemptWriterFixture(t), recorded = await f.write();
  const start = writerRawRecord(f, "start"), output = writerRawRecord(f, "output");
  return { ...f, recorded, fact: recorded.fact, start: { value: start.value }, output: { value: output.value },
    process: { invocation: { value: recorded.evidence.invocation }, ledger: output.value.ledger as { path: string; sha256: string } } };
}

/** Additional history is explicitly synthetic TEST metadata; the native singleton is never bypassed or called. */
function additionalAttempt(f: OriginalFixture, attemptId: string): void {
  const directory = path.join(path.dirname(f.directory), attemptId);
  assert(directory.startsWith(f.staging.root + path.sep)); fs.mkdirSync(directory, { mode: 0o700 });
  const archive = { ...f.fact.archive, path: path.join(directory, "reservation.json") };
  fs.writeFileSync(archive.path, fs.readFileSync(f.fact.archive.path), { flag: "wx", mode: 0o600 });
  const start = createOpeningRecord(path.join(directory, "start.json"), { ...f.start.value, cleanupAttemptId: attemptId, archive });
  const invocation = createOpeningRecord(path.join(directory, "invocation.json"), { ...f.process.invocation.value, attemptId });
  const ledger = { ...f.process.ledger, path: path.join(directory, "owned-process-ledger.cleanup.jsonl") };
  fs.writeFileSync(ledger.path, fs.readFileSync(f.process.ledger.path), { flag: "wx", mode: 0o600 });
  const output = createOpeningRecord(path.join(directory, "output.json"), { ...f.output.value, invocationSha256: invocation.sha256, ledger });
  createOpeningRecord(path.join(directory, "prepared.json"), { ...f.fact, cleanupAttemptId: attemptId,
    archive, cleanupStartSha256: start.sha256, cleanupInvocationSha256: invocation.sha256, cleanupOutputSha256: output.sha256 });
}

/** Start the read-only test clock after setup, with actual monotonic decreasing remainder. */
export async function cleanupHistoryFixture(t: TestContext, count = 1) {
  const f = await completedFixture(t);
  for (let index = 1; index < count; index++) additionalAttempt(f, randomUUID());
  const root = path.dirname(f.directory), ids = fs.readdirSync(root).sort(), started = performance.now();
  const calls = { guard: 0, remaining: 0 }, callbacks = { guard: () => {}, remaining: () => {} };
  const budget = { allowance: 300_000 };
  const input: SourceColorCleanupHistoryInput = { held: f.input.held,
    guard: () => { calls.guard++; callbacks.guard(); },
    remainingMs: () => { calls.remaining++; callbacks.remaining(); return budget.allowance - (performance.now() - started); } };
  const activeBytes = fs.readFileSync(f.staged.reservation.path);
  return { ...f, root, ids, historyInput: input, historyCalls: calls, historyCallbacks: callbacks, budget, activeBytes,
    readHistory: () => readSourceColorCleanupHistory(input, f.readerDependencies) };
}
export type CleanupHistoryFixture = Awaited<ReturnType<typeof cleanupHistoryFixture>>;

/** Exact original attempt-file allowlist only, never an installed or arbitrary dependency. */
export function historyFile(f: CleanupHistoryFixture, name: string, attemptId = f.ids[0]): string {
  assert(NAMES.includes(name)); assert(f.ids.includes(attemptId));
  const file = path.join(f.root, attemptId, name);
  assert(file.startsWith(fs.realpathSync(f.staging.root) + path.sep)); assert.equal(fs.realpathSync(file), file);
  const row = fs.lstatSync(file); assert(row.isFile()); assert.equal(row.nlink, 1); assert.equal(row.uid, process.getuid!());
  return file;
}

/** Same-byte replacement is a real inode change; all written targets stay within the exact TEST attempt. */
export function replaceHistoryFile(f: CleanupHistoryFixture, name: string, attemptId = f.ids[0]): void {
  const file = historyFile(f, name, attemptId), temporary = path.join(path.dirname(file), `TEST-replacement-${randomUUID()}`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

/** Rebind only prepared JSON for malformed-data tests; production historical references are never changed. */
export function alterPrepared(f: CleanupHistoryFixture, change: (row: Record<string, unknown>) => void): void {
  const file = historyFile(f, "prepared.json"), row = JSON.parse(fs.readFileSync(file, "utf8")); change(row);
  fs.chmodSync(file, 0o600); fs.writeFileSync(file, JSON.stringify(row), { flag: "w" });
}
