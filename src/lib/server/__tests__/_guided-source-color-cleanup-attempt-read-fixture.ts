/** Actual TEMP staging/records/archive/ledger; journal settlement and native tools are TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { createOpeningRecord } from "../guided-opening-process-activation";
import { runSourceColorCleanupProcess } from "../guided-source-color-cleanup-process";
import { writeSourceColorReservationArchive } from "../guided-source-color-reservation-archive";
import { parsePreparedSourceColorCleanupFact } from "../../producer/contracts/guided-source-color-cleanup-facts";
import { readSourceColorCleanupAttempt, sourceColorCleanupAttemptReadDependencies,
  type SourceColorCleanupAttemptReadInput } from "../guided-source-color-cleanup-attempt-read";
import { sourceColorCleanupProcessFixture } from "./_guided-source-color-cleanup-process-fixture";
import { cleanupAttemptMediaFixture } from "./_guided-source-color-cleanup-attempt-media-fixture";
import { observeRecoveryFixtureJob } from "./_guided-source-color-resource-recovery-fixture";

/** Before any attempt records: matching historical pipeline metadata, not installed executable authority. */
export function cleanupAttemptPreRecordFixture(t: TestContext, f = sourceColorCleanupProcessFixture(t)) {
  const { held } = f.input;
  const snapshotRoot = path.join(f.staging.root, "TEST-original-pipeline");
  const script = "scripts/producer/guided_opening_cleanup.py", runner = "scripts/producer/headless/process_runner.py";
  held.job.ctx.pipeline = { snapshotRoot, files: [{ path: script, hash: f.tools.scriptHash },
    { path: runner, hash: f.tools.runnerScriptHash }] } as typeof held.job.ctx.pipeline;
  Object.assign(f.tools, { script: path.join(snapshotRoot, script), runnerScript: path.join(snapshotRoot, runner),
    python: "/TEST/venv/bin/python", pythonResolved: "/TEST/runtime/python", venvRoot: "/TEST/venv", venvConfig: "/TEST/venv/pyvenv.cfg" });
  const media = cleanupAttemptMediaFixture(f);
  observeRecoveryFixtureJob(f.staging.root, held, "attempt");
  const readerDependencies = { ...sourceColorCleanupAttemptReadDependencies, stopped: f.dependencies.stopped, media: media.provider };
  const receivedAt = new Date().toISOString();
  return { ...f, readerDependencies, receivedAt, media };
}

/** Independently publish read fixtures; the writer under test is not used to mint expectations. */
export async function cleanupAttemptReadFixture(t: TestContext) {
  const f = cleanupAttemptPreRecordFixture(t), { held, attemptId } = f.input;
  const archived = writeSourceColorReservationArchive({ ...f.input });
  const start = createOpeningRecord(path.join(f.directory, "start.json"), { schemaVersion: 2, kind: "guided-opening-cleanup-start",
    cleanupAttemptId: attemptId, claimHash: held.claimHash, processOutcomeSha256: f.actual.receiptSha256, beforeJournalHash: held.sha256,
    clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt, receivedAt: f.receivedAt,
    startedAt: new Date().toISOString(), budgetScope: "separate-protected-cleanup-not-render-allowance",
    sourceColor: f.actual.sourceColor, archive: archived.archive });
  const process = await runSourceColorCleanupProcess(f.input, f.dependencies);
  const output = createOpeningRecord(path.join(f.directory, "output.json"), { schemaVersion: 2, kind: "guided-opening-cleanup-owned-output",
    stdout: process.stdout, stderr: process.stderr, mediaProcessGroupStopped: true, cleanupProcessGroupStopped: true,
    cleanupNestedOwnership: "resolved-by-normal-return", observedAt: new Date().toISOString(),
    elapsedMs: 4100, invocationSha256: process.invocation.sha256, ledger: process.ledger });
  const fact = parsePreparedSourceColorCleanupFact({ schemaVersion: 2, kind: "guided-opening-source-color-cleanup-prepared",
    scope: "exact-owned-resource-cleanup-awaiting-reservation-retirement-not-approval", phase: "awaiting-retirement", claimRetained: true,
    claimHash: held.claimHash, executionId: held.claim.executionId, cleanupAttemptId: attemptId, beforeJournalHash: held.sha256,
    processOutcomeSha256: f.actual.receiptSha256, cleanupStartSha256: start.sha256, cleanupOutputSha256: output.sha256,
    cleanupResultHash: canonicalJsonSha256(process.result), cleanupInvocationSha256: process.invocation.sha256,
    reservation: f.actual.sourceColor.reservation, archive: archived.archive, sourceColorHash: f.actual.sourceColor.sourceColorHash,
    clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt, createdAt: new Date().toISOString(),
    mediaSelected: false, openingApproved: false, deliveryApproved: false });
  const callbacks = { guard: () => {}, remaining: () => 300_000 }, checks = { guard: 0, remaining: 0 };
  const readInput: SourceColorCleanupAttemptReadInput = { held, fact, guard: () => { checks.guard++; callbacks.guard(); },
    remainingMs: () => { checks.remaining++; return callbacks.remaining(); } };
  return { ...f, archived, start, output, process, fact, readInput, callbacks, checks,
    read: () => readSourceColorCleanupAttempt(readInput, f.readerDependencies) };
}

/** Mutation authority is an exact allowlist of original canonical TEMP regular single-link files. */
export function attemptFaultFile(f: Awaited<ReturnType<typeof cleanupAttemptReadFixture>>, name: string): string {
  assert(["start.json", "invocation.json", "output.json", "reservation.json", "owned-process-ledger.cleanup.jsonl"].includes(name));
  const file = path.join(f.directory, name);
  assert(file.startsWith(f.staging.root + path.sep)); assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  return file;
}

/** Same-byte replacement can be requested; optional TEST rebind models a separately forged prepared fact. */
export function replaceAttemptFile(f: Awaited<ReturnType<typeof cleanupAttemptReadFixture>>, name: string, bytes?: Buffer): string {
  const file = attemptFaultFile(f, name), raw = bytes ?? fs.readFileSync(file);
  const temporary = path.join(f.directory, `TEST-replacement-${randomUUID()}.json`);
  fs.writeFileSync(temporary, raw, { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
  return createHash("sha256").update(raw).digest("hex");
}

/** Faulted record bytes may carry a matching TEST raw reference but must still fail semantic joins. */
export function mutateAttemptRecord(f: Awaited<ReturnType<typeof cleanupAttemptReadFixture>>, name: "start" | "invocation" | "output",
  mutate: (row: Record<string, unknown>) => void): void {
  const row = JSON.parse(fs.readFileSync(attemptFaultFile(f, `${name}.json`), "utf8")); mutate(row);
  const key = { start: "cleanupStartSha256", invocation: "cleanupInvocationSha256", output: "cleanupOutputSha256" } as const;
  f.fact[key[name]] = replaceAttemptFile(f, `${name}.json`, Buffer.from(JSON.stringify(row)));
}
