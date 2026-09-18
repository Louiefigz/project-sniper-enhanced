/** Actual existing recovery dispatcher with only original native/claim/tool leaves overridden; no service-success override. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test, { type TestContext } from "node:test";
import { reconcileGuidedOpeningExecution } from "../guided-opening-cleanup";
import { sourceColorCleanupRecoveryDependencies } from "../guided-source-color-cleanup-recovery";
import { canonicalJson } from "../auto-edit-hash";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { cleanupRecoveryFixture, cleanupRecoveryDependencies, replaceRecoveryFile,
  type CleanupRecoveryFixture } from "./_guided-source-color-cleanup-recovery-fixture";

/** Temporary dependency overrides keep all whole readers, retire/CAS operations and checkpoint acquisition actual. */
function routeLeaves(t: TestContext, f: CleanupRecoveryFixture): void {
  const actual = sourceColorCleanupRecoveryDependencies, leaves = cleanupRecoveryDependencies(f);
  t.mock.method(actual, "acquireProject", leaves.acquireProject);
  t.mock.method(actual.pending, "claim", leaves.pending.claim); t.mock.method(actual.pending, "attempt", leaves.pending.attempt);
  t.mock.method(actual.resource, "workspace", leaves.resource.workspace); t.mock.method(actual.resource, "acquire", leaves.resource.acquire);
  t.mock.method(actual.final, "history", leaves.final.history); t.mock.method(actual.read, "history", leaves.read.history);
}

/** The public request has no clock, stop flag, journal observation or alternate cleanup implementation. */
function routeInput(f: CleanupRecoveryFixture) {
  return { dir: f.input.dir, expectedToken: f.input.expectedToken,
    expectedJournalHash: f.input.expectedJournalHash, claimHash: f.input.expectedClaimHash };
}

test("actual dispatcher recognizes prepared current journal and completes exact pending retirement", async t => {
  const f = await cleanupRecoveryFixture(t); routeLeaves(t, f);
  const result = await reconcileGuidedOpeningExecution(routeInput(f));
  assert.equal(result.cleanupHash, observeHumanCutJob(f.input.dir).job.guidedHandoffV2!.openingCleanupHash);
  assert.equal(result.claimRetained, false); assert.equal(result.mediaSelected, false); assert.equal(result.openingApproved, false);
  assert.equal(f.events.project, 1); assert.equal(f.events.resource, 1); assert.equal(f.base.calls.length, 1);
  assert(!fs.existsSync(f.projectLock)); assert(!fs.existsSync(f.resourceLock));
  await assert.rejects(reconcileGuidedOpeningExecution({ ...routeInput(f), expectedJournalHash: observeHumanCutJob(f.input.dir).sha256 }));
  assert.equal(f.events.project, 1); assert.equal(f.events.resource, 1);
});

for (const key of ["expectedToken", "expectedJournalHash", "claimHash"] as const) test(`dispatcher rejects stale ${key} without new ownership`, async t => {
  const f = await cleanupRecoveryFixture(t); routeLeaves(t, f);
  const input = { ...routeInput(f), [key]: key === "expectedToken" ? "TEST-stale-token" : "f".repeat(64) };
  await assert.rejects(reconcileGuidedOpeningExecution(input), /stale|changed/);
  assert.equal(f.events.project, 0); assert.equal(f.events.resource, 0); assert(fs.existsSync(f.files.active));
});

for (const kind of ["malformed-prepared", "unknown-v2", "legacy"] as const) test(`${kind} never borrows pending-retirement success`, async t => {
  const f = await cleanupRecoveryFixture(t); routeLeaves(t, f);
  const fact = kind === "legacy" ? { schemaVersion: 1, kind: "guided-opening-cleanup-commit", TEST: "invalid legacy" }
    : { ...f.base.recorded.fact, ...(kind === "malformed-prepared" ? { claimRetained: false }
      : { kind: "guided-opening-source-color-cleanup-prepared-unknown" }) };
  const job = structuredClone(f.current.job); job.guidedHandoffV2!.openingCleanupHash = writeGuidedObject(f.input.dir, fact);
  replaceRecoveryFile(f, "journal", Buffer.from(canonicalJson(job)));
  await assert.rejects(reconcileGuidedOpeningExecution({ ...routeInput(f), expectedJournalHash: observeHumanCutJob(f.input.dir).sha256 }));
  assert.equal(f.events.project, 0); assert.equal(f.events.resource, 0); assert.equal(f.base.calls.length, 1);
});

test("the dispatcher protected clock starts before directory parsing and is not replaced on pending dispatch", async t => {
  const f = await cleanupRecoveryFixture(t); routeLeaves(t, f);
  const actualNow = performance.now.bind(performance), realpath = fs.realpathSync; let advance = 0, fired = false;
  t.mock.method(performance, "now", () => actualNow() + advance);
  t.mock.method(fs, "realpathSync", (...args: Parameters<typeof fs.realpathSync>) => {
    const value = realpath(...args);
    if (!fired && args[0] === f.input.dir) { fired = true; advance = 300_001; }
    return value;
  });
  await assert.rejects(reconcileGuidedOpeningExecution(routeInput(f)), /protected cleanup deadline exceeded|allowance/);
  assert(fired); assert.equal(f.events.project, 0); assert.equal(f.events.resource, 0); assert(fs.existsSync(f.files.active));
});
