/** Actual CLI status/request/recovery/readback over TEMP records and leases; original native/claim admission are TEST-only leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test, { type TestContext } from "node:test";
import { executeOpeningCommand, openingCommandServices } from "../../../../scripts/producer/guided-opening";
import { parseRecoverGuidedOpeningCleanup } from "../../producer/contracts/guided-opening-v1";
import { sourceColorCleanupPendingReadDependencies } from "../guided-source-color-cleanup-pending-read";
import { sourceColorCleanupRecoveryDependencies, reconcilePendingSourceColorCleanup } from "../guided-source-color-cleanup-recovery";
import { openingCleanupStoreDependencies, readPendingOpeningCleanup, readCommittedOpeningCleanup } from "../guided-opening-cleanup-store";
import { readFinalSourceColorCleanupForJournal } from "../guided-source-color-cleanup-final-read";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { canonicalJson } from "../auto-edit-hash";
import { cleanupRecoveryFixture, replaceRecoveryFile, type CleanupRecoveryFixture } from "./_guided-source-color-cleanup-recovery-fixture";

/** Every whole pending/recovery/retirement/CAS/final reader stays at its actual default implementation. */
async function fixture(t: TestContext) {
  const f = await cleanupRecoveryFixture(t);
  t.mock.method(sourceColorCleanupPendingReadDependencies, "claim", f.readers.claim);
  t.mock.method(sourceColorCleanupPendingReadDependencies, "attempt", f.readers.attempt);
  t.mock.method(sourceColorCleanupRecoveryDependencies, "acquireProject", f.acquireProject);
  t.mock.method(sourceColorCleanupRecoveryDependencies.resource, "acquire", f.acquireResource);
  return f;
}

/** Persist literal status-provided request data, new-only, without overwriting another request or changing its identity. */
function persistRequest(f: CleanupRecoveryFixture, value: unknown): { file: string; bytes: Buffer } {
  const file = path.join(f.base.staging.root, "TEST CLI recovery request's.json"), bytes = Buffer.from(JSON.stringify(value));
  assert.equal(fs.realpathSync(path.dirname(file)), f.base.staging.root);
  fs.writeFileSync(file, bytes, { flag: "wx", mode: 0o600 });
  return { file, bytes };
}

test("CLI cleanup services remain actual private-capability readers and pending-only recovery", () => {
  assert.equal(openingCommandServices.pendingCleanup, readPendingOpeningCleanup);
  assert.equal(openingCommandServices.recoverCleanup, reconcilePendingSourceColorCleanup);
  assert.equal(openingCleanupStoreDependencies.final, readFinalSourceColorCleanupForJournal);
});

test("actual cleanup-status to literal wx request to CLI recovery preserves complete identity and false approval flags", async t => {
  const f = await fixture(t), status = await executeOpeningCommand(["cleanup-status", f.input.dir]);
  assert("request" in status); assert.equal(status.state, "pending-retirement");
  assert.equal(status.scope, "pending-reservation-retirement-not-native-cleanup-render-or-approval");
  const request = parseRecoverGuidedOpeningCleanup(status.request);
  assert.deepEqual(request, { schemaVersion: 1, operation: "recover-guided-opening-cleanup", expectedToken: f.current.job.token,
    expectedJournalHash: f.current.sha256, claimHash: f.base.input.held.claimHash });
  assert.equal(status.mediaSelected, false); assert.equal(status.openingApproved, false); assert.equal(status.deliveryApproved, false);
  assert.equal(f.events.project, 0); assert.equal(f.events.resource, 0); assert(fs.existsSync(f.files.active));
  const saved = persistRequest(f, request), result = await executeOpeningCommand(["recover-cleanup", f.input.dir, saved.file]);
  assert("claimRetained" in result); assert.equal(result.claimRetained, false);
  assert.equal(result.mediaSelected, false); assert.equal(result.openingApproved, false); assert.equal(result.deliveryApproved, false);
  const final = readCommittedOpeningCleanup(f.input.dir);
  assert.equal(final.receipt.schemaVersion, 2); assert.equal(final.receipt.kind, "guided-opening-source-color-cleanup-commit");
  assert.equal(final.cleanupHash, result.cleanupHash); assert.deepEqual(final.evidence.stop, f.base.actual);
  assert.equal(final.held.claimHash, request.claimHash); assert.equal(final.mediaSelected, false);
  assert.equal(f.events.project, 1); assert.equal(f.events.resource, 1); assert.equal(f.base.calls.length, 1);
  assert(!fs.existsSync(f.projectLock)); assert(!fs.existsSync(f.resourceLock)); assert(!fs.existsSync(f.files.active));
  assert.deepEqual(fs.readFileSync(saved.file), saved.bytes);
  await assert.rejects(executeOpeningCommand(["recover-cleanup", f.input.dir, saved.file]), /stale|changed/);
  await assert.rejects(executeOpeningCommand(["cleanup-status", f.input.dir]));
  assert.equal(f.events.project, 1); assert.equal(f.events.resource, 1); assert.equal(f.base.calls.length, 1);
  assert.deepEqual(fs.readFileSync(saved.file), saved.bytes); assert(!fs.existsSync(path.join(f.base.directory, "failure.json")));
});

for (const key of ["expectedToken", "expectedJournalHash", "claimHash"] as const) test(`actual CLI refuses stale persisted ${key} without refreshing it`, async t => {
  const f = await fixture(t), status = await executeOpeningCommand(["cleanup-status", f.input.dir]); assert("request" in status);
  const original = parseRecoverGuidedOpeningCleanup(status.request);
  const saved = persistRequest(f, { ...original, [key]: key === "expectedToken" ? "TEST-stale" : "f".repeat(64) });
  await assert.rejects(executeOpeningCommand(["recover-cleanup", f.input.dir, saved.file]), /stale|changed/);
  assert.equal(f.events.project, 0); assert.equal(f.events.resource, 0); assert(fs.existsSync(f.files.active));
  assert.equal(observeHumanCutJob(f.input.dir).sha256, original.expectedJournalHash); assert.deepEqual(fs.readFileSync(saved.file), saved.bytes);
});

for (const kind of ["legacy", "unknown", "malformed-prepared"] as const) test(`cleanup-status refuses ${kind} instead of manufacturing a recovery request`, async t => {
  const f = await fixture(t), row = kind === "legacy" ? { schemaVersion: 1, kind: "guided-opening-cleanup-commit", TEST: "legacy" }
    : { ...f.base.recorded.fact, ...(kind === "unknown" ? { kind: "TEST-unknown" } : { claimRetained: false }) };
  const job = structuredClone(f.current.job); job.guidedHandoffV2!.openingCleanupHash = writeGuidedObject(f.input.dir, row);
  replaceRecoveryFile(f, "journal", Buffer.from(canonicalJson(job)));
  await assert.rejects(executeOpeningCommand(["cleanup-status", f.input.dir]));
  assert.equal(f.events.project, 0); assert.equal(f.events.resource, 0); assert.equal(f.base.calls.length, 1);
  assert(fs.existsSync(f.files.active)); assert(!fs.existsSync(path.join(f.base.staging.root, "TEST CLI recovery request's.json")));
});

test("cleanup-status rejects an actual late held media-record replacement without producing a request", async t => {
  const f = await fixture(t); f.callbacks.stopped = () => { f.callbacks.stopped = () => {}; replaceRecoveryFile(f, "media"); };
  await assert.rejects(executeOpeningCommand(["cleanup-status", f.input.dir]), /original|changed/);
  assert.equal(f.events.project, 0); assert.equal(f.events.resource, 0); assert.equal(f.base.calls.length, 1);
});

for (const boundary of ["canonical", "request"] as const) test(`actual CLI recovery clock charges ${boundary} reading before service entry`, async t => {
  const f = await fixture(t), status = await executeOpeningCommand(["cleanup-status", f.input.dir]); assert("request" in status);
  const saved = persistRequest(f, status.request), actualNow = performance.now.bind(performance), realpath = fs.realpathSync, open = fs.openSync;
  let advance = 0, fired = false;
  t.mock.method(performance, "now", () => actualNow() + advance);
  t.mock.method(fs, "realpathSync", (...args: Parameters<typeof fs.realpathSync>) => {
    const value = realpath(...args);
    if (!fired && boundary === "canonical" && args[0] === f.input.dir) { fired = true; advance = 300_001; }
    return value;
  });
  t.mock.method(fs, "openSync", (...args: Parameters<typeof fs.openSync>) => {
    const value = open(...args);
    if (!fired && boundary === "request" && args[0] === saved.file) { fired = true; advance = 300_001; }
    return value;
  });
  await assert.rejects(executeOpeningCommand(["recover-cleanup", f.input.dir, saved.file]), /protected cleanup deadline exceeded|allowance/);
  assert(fired); assert.equal(f.events.project, 0); assert.equal(f.events.resource, 0); assert(fs.existsSync(f.files.active));
  assert.deepEqual(fs.readFileSync(saved.file), saved.bytes);
});
