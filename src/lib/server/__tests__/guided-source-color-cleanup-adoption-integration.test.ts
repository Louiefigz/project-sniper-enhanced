/** Complete metadata lifecycle on TEMP leases; no second native invocation, renderer, approval or real admission. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { assertSourceColorFinalCleanupMetadata } from "../guided-source-color-cleanup-final-read";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { cleanupAdoptionIntegrationFixture } from "./_guided-source-color-cleanup-adoption-integration-fixture";
import { replaceAdoptionFile } from "./_guided-source-color-cleanup-adoption-fixture";

test("actual historical adoption reaches pending, exact retirement, final CAS and final read on one original recovery clock", async t => {
  const f = await cleanupAdoptionIntegrationFixture(t), clock = f.clock, originalCalls = f.calls.length;
  f.timing.elapsed = 300_000; // The old native-attempt allowance expired; its historical completion is not rerun.
  const committed = f.commit(), pending = f.pending(), retired = f.retire(pending), final = f.finalize(retired), proof = f.read();
  assert.equal(f.adoptionInput.clock, clock); assert.equal(pending.pendingJournalHash, committed.pendingJournalHash);
  assert.equal(proof.cleanupHash, final.cleanupHash); assert.equal(proof.receipt.kind, "guided-opening-source-color-cleanup-commit");
  assert.equal(proof.receipt.preparedFactHash, f.recorded.factHash); assert.equal(proof.receipt.pendingJournalHash, pending.pendingJournalHash);
  assert.deepEqual(proof.evidence.result, pending.result); assert.deepEqual(proof.retirementAck, retired.ack);
  assert.equal(proof.mediaSelected, false); assert.equal(proof.openingApproved, false); assert.equal(proof.deliveryApproved, false);
  assert.equal(f.calls.length, originalCalls); assert.equal(originalCalls, 1); f.assertLeases();
  assert(!fs.existsSync(f.files.active)); assert(fs.existsSync(f.files.ack)); assert(fs.existsSync(f.files.archive));
  assert(!fs.existsSync(f.files.failure)); assert.throws(pending.assertCurrent, /journal|identity/);
  f.staging.resource.lease.release(); f.projectLease.release(); assertSourceColorFinalCleanupMetadata(proof);
  assert(!fs.existsSync(f.files.projectLock)); assert(!fs.existsSync(f.files.resourceLock));
});

test("lost response after adopted first CAS is recovered by the actual pending service without replay, renewing time or leaking leases", async t => {
  const f = await cleanupAdoptionIntegrationFixture(t), lost = new Error("TEST lost first-CAS response"), clock = f.clock;
  assert.throws(() => f.commit({ afterCas: () => { throw lost; } }), error => error === lost);
  const pendingHash = observeHumanCutJob(f.before.job.ctx.dir).sha256; assert.notEqual(pendingHash, f.before.sha256);
  assert(fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack)); assert.throws(f.adopt, /journal|pending/);
  f.staging.resource.lease.release(); f.projectLease.release(); const final = await f.recover();
  assert.equal(f.adoptionInput.clock, clock); assert.equal(final.journalHash, observeHumanCutJob(f.before.job.ctx.dir).sha256);
  assert.equal(final.claimRetained, false); assert.equal(final.mediaSelected, false); assert.equal(final.openingApproved, false);
  assert.equal(f.projects.length, 1); assert.equal(f.resources.length, 1); assert.equal(f.calls.length, 1);
  assert(!fs.existsSync(f.files.projectLock)); assert(!fs.existsSync(f.files.resourceLock));
  assert(!fs.existsSync(f.files.active)); assert(fs.existsSync(f.files.ack)); assert(!fs.existsSync(f.files.failure));
  await assert.rejects(f.recover(), /stale|changed/); assert.equal(f.projects.length, 1); assert.equal(f.calls.length, 1);
});

test("same original recovery expiry after adopted pending CAS prevents retirement and retains both original owners", async t => {
  const f = await cleanupAdoptionIntegrationFixture(t); const committed = f.commit(); f.allowance.ms = 0;
  assert.throws(f.pending, /remainder|expired/); assert.equal(observeHumanCutJob(f.before.job.ctx.dir).sha256, committed.pendingJournalHash);
  f.assertLeases(); assert(fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack)); assert.equal(f.calls.length, 1);
});

test("adopted pending proof does not survive original completion-output replacement before retirement", async t => {
  const f = await cleanupAdoptionIntegrationFixture(t); f.commit(); const pending = f.pending(); replaceAdoptionFile(f, "output");
  assert.throws(() => f.retire(pending), /identity|changed/); f.assertLeases();
  assert(fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack)); assert.equal(f.calls.length, 1);
});

test("final read on the same recovery clock refuses post-final-CAS expiry without undoing committed evidence", async t => {
  const f = await cleanupAdoptionIntegrationFixture(t); f.commit(); const final = f.finalize(f.retire(f.pending()));
  f.allowance.ms = 0; assert.throws(f.read, /remainder|expired/); f.assertLeases();
  assert.equal(observeHumanCutJob(f.before.job.ctx.dir).sha256, final.journalHash);
  assert(!fs.existsSync(f.files.active)); assert(fs.existsSync(f.files.ack)); assert(!fs.existsSync(f.files.failure));
});

test("lost-response recovery expiry inside global acquisition releases only its partial owners and retains original pending metadata", async t => {
  const f = await cleanupAdoptionIntegrationFixture(t); f.commit(); const pendingHash = observeHumanCutJob(f.before.job.ctx.dir).sha256;
  f.staging.resource.lease.release(); f.projectLease.release(); f.integrationCallbacks.recoveredResource = () => { f.allowance.ms = 0; };
  await assert.rejects(f.recover(), /allowance|remainder|expired/);
  assert.equal(observeHumanCutJob(f.before.job.ctx.dir).sha256, pendingHash); assert.equal(f.calls.length, 1);
  assert.equal(f.projects.length, 1); assert.equal(f.resources.length, 1);
  assert(!fs.existsSync(f.files.projectLock)); assert(!fs.existsSync(f.files.resourceLock));
  assert(fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack)); assert(!fs.existsSync(f.files.failure));
});

test("last final-read owner callback cannot substitute original adopted output after final CAS", async t => {
  const f = await cleanupAdoptionIntegrationFixture(t); f.commit(); const final = f.finalize(f.retire(f.pending()));
  f.integrationCallbacks.finalRead = () => replaceAdoptionFile(f, "output");
  assert.throws(f.read, /identity|changed/); f.assertLeases(); assert.equal(f.calls.length, 1);
  assert.equal(observeHumanCutJob(f.before.job.ctx.dir).sha256, final.journalHash);
  assert(fs.existsSync(f.files.ack)); assert(!fs.existsSync(f.files.failure));
});

test("final proof requires the original actual lease even after both adopted journal CAS edges committed", async t => {
  const f = await cleanupAdoptionIntegrationFixture(t); f.commit(); const final = f.finalize(f.retire(f.pending()));
  f.integrationCallbacks.finalRead = () => f.projectLease.release();
  assert.throws(f.read, /ENOENT|lease/); assert.equal(f.calls.length, 1);
  assert.equal(observeHumanCutJob(f.before.job.ctx.dir).sha256, final.journalHash);
  assert(fs.existsSync(f.files.resourceLock)); assert(fs.existsSync(f.files.ack)); assert(!fs.existsSync(f.files.failure));
});
