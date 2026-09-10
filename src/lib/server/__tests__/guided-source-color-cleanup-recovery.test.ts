/** Actual pending checkpoint, leases, retirement, final CAS and proof read; native/admission leaves are explicit TEST records. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { acquireGuidedMutation } from "../guided-cut-v2-store";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { reconcilePendingSourceColorCleanup, sourceColorCleanupRecoveryDependencies } from "../guided-source-color-cleanup-recovery";
import { cleanupRecoveryFixture, cleanupRecoveryDependencies } from "./_guided-source-color-cleanup-recovery-fixture";

test("recovery defaults to the actual project checkpoint acquisition", () => {
  assert.equal(sourceColorCleanupRecoveryDependencies.acquireProject, acquireGuidedMutation);
});

test("the unchanged reconcile checkpoint admits the full valid pending journal with a real TEMP project lease", async t => {
  const f = await cleanupRecoveryFixture(t);
  const lease = await f.acquireProject(f.input.dir, { workflowVersion: 2, action: "reconcile-guided-opening",
    expectedStatus: "treatment_admitted", expectedToken: f.input.expectedToken, expectedJournalHash: f.input.expectedJournalHash });
  assert(fs.existsSync(f.projectLock)); assert.equal(f.events.project, 1); assert.equal(f.events.resource, 0);
  lease.release(); assert(!fs.existsSync(f.projectLock)); assert(fs.existsSync(f.files.active));
  assert.equal(observeHumanCutJob(f.input.dir).sha256, f.current.sha256);
});

for (const state of ["present", "absent", "acked"] as const) test(`recovery completes actual ${state} pending retirement without another cleanup attempt`, async t => {
  const f = await cleanupRecoveryFixture(t, state), beforeCalls = f.base.calls.length;
  const result = await reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f));
  const current = observeHumanCutJob(f.input.dir), pointers = current.job.guidedHandoffV2!;
  assert.equal(current.sha256, result.journalHash); assert.equal(pointers.openingCleanupHash, result.cleanupHash);
  assert.equal(Object.hasOwn(pointers, "openingExecutionClaimHash"), false);
  assert.equal(Object.hasOwn(pointers, "openingProcessOutcomeHash"), false);
  assert.equal(result.claimRetained, false); assert.equal(result.mediaSelected, false);
  assert.equal(result.openingApproved, false); assert.equal(result.deliveryApproved, false);
  assert.equal(f.events.project, 1); assert.equal(f.events.resource, 1); assert(f.events.stopped > 0);
  assert.equal(f.base.calls.length, beforeCalls); assert.equal(beforeCalls, 1);
  assert(!fs.existsSync(f.files.active)); assert(fs.existsSync(f.files.ack)); assert(fs.existsSync(f.files.archive));
  assert(!fs.existsSync(f.projectLock)); assert(!fs.existsSync(f.resourceLock));
  assert(!fs.existsSync(path.join(f.base.directory, "failure.json")));
  const names = fs.readdirSync(path.dirname(f.base.directory)).sort();
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /stale|changed/);
  await assert.rejects(reconcilePendingSourceColorCleanup({ ...f.input, expectedJournalHash: current.sha256 },
    cleanupRecoveryDependencies(f)), /stale|changed/);
  assert(fs.existsSync(f.files.pending)); // Retained pending history exists, but never substitutes for the final current journal.
  assert.equal(f.events.project, 1); assert.equal(f.events.resource, 1);
  assert.deepEqual(fs.readdirSync(path.dirname(f.base.directory)).sort(), names);
});

for (const key of ["expectedToken", "expectedJournalHash", "expectedClaimHash"] as const) test(`stale ${key} refuses before either acquisition`, async t => {
  const f = await cleanupRecoveryFixture(t), input = { ...f.input, [key]: key === "expectedToken" ? "TEST-stale-token" : "f".repeat(64) };
  await assert.rejects(reconcilePendingSourceColorCleanup(input, cleanupRecoveryDependencies(f)), /stale|changed/);
  assert.equal(f.events.project, 0); assert.equal(f.events.resource, 0);
  assert(!fs.existsSync(f.projectLock)); assert(!fs.existsSync(f.resourceLock)); assert(fs.existsSync(f.files.active));
});

test("expiry before any acquisition does not invent a cleanup allowance", async t => {
  const f = await cleanupRecoveryFixture(t); f.timing.advance = 300_000;
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /allowance/);
  assert.equal(f.events.project, 0); assert.equal(f.events.resource, 0); assert(fs.existsSync(f.files.active));
});

test("a live project owner is not borrowed or released by recovery", async t => {
  const f = await cleanupRecoveryFixture(t);
  const blocker = await f.acquireProject(f.input.dir, { workflowVersion: 2, action: "reconcile-guided-opening",
    expectedStatus: "treatment_admitted", expectedToken: f.input.expectedToken, expectedJournalHash: f.input.expectedJournalHash });
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /busy|running|locked|mutation|operation/i);
  assert.equal(f.projects.length, 1); assert.equal(f.resources.length, 0);
  assert(fs.existsSync(f.projectLock)); assert(fs.existsSync(f.files.active)); blocker.release();
});

test("a live global owner causes only the newly acquired project lease to release", async t => {
  const f = await cleanupRecoveryFixture(t), blocker = f.acquireResource(f.base.staging.resource.resource, "TEST unrelated live owner");
  assert(blocker.lease);
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /busy/);
  assert.equal(f.projects.length, 1); assert.equal(f.resources.length, 1);
  assert(!fs.existsSync(f.projectLock)); assert(fs.existsSync(f.resourceLock)); assert(fs.existsSync(f.files.active)); blocker.lease.release();
});
