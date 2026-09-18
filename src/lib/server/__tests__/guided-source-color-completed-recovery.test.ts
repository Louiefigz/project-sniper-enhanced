/** Real cold completed-data recovery; no actual native/media qualification or extra worker invocation. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { completedRecoveryFixture } from "./_guided-source-color-completed-recovery-fixture";
import { replaceAdoptionFile, addPartialAdoptionSibling } from "./_guided-source-color-cleanup-adoption-fixture";

test("actual completed recovery acquires both owners, adopts once, commits twice, reads final evidence and releases", async t => {
  const f = await completedRecoveryFixture(t), clock = f.recoveryInput.clock, started = performance.now(), result = await f.run();
  t.diagnostic(`actual TEST completed recovery=${(performance.now() - started).toFixed(3)}ms; native/claim admission TEST leaves`);
  assert.equal(f.recoveryInput.clock, clock); assert.equal(result.claimRetained, false); assert.equal(result.resourceCleanup, "verified");
  assert.equal(result.journalHash, observeHumanCutJob(f.recoveryInput.dir).sha256);
  assert.equal(result.mediaSelected, false); assert.equal(result.openingApproved, false); assert.equal(result.deliveryApproved, false);
  assert.equal(f.projects.length, 1); assert.equal(f.resources.length, 1); assert.equal(f.calls.length, 1);
  assert(!fs.existsSync(f.files.project)); assert(!fs.existsSync(f.files.resource)); assert(!fs.existsSync(f.files.active));
  assert(fs.existsSync(f.files.ack)); assert(!fs.existsSync(f.files.failure));
  await assert.rejects(f.run(), /publication original bytes or identity changed/);
  assert.equal(f.projects.length, 1); assert.equal(f.calls.length, 1);
});

test("stale completed preparation SHA refuses before global acquisition and releases only the newly acquired project", async t => {
  const f = await completedRecoveryFixture(t); f.recoveryInput.preparedSha256 = "0".repeat(64);
  await assert.rejects(f.run(), /preparation request is stale/);
  assert.equal(f.projects.length, 1); assert.equal(f.resources.length, 0); assert.equal(f.calls.length, 1);
  assert(!fs.existsSync(f.files.project)); assert(fs.existsSync(f.files.active));
  assert.equal(observeHumanCutJob(f.recoveryInput.dir).sha256, f.before.sha256);
});

test("an incomplete older sibling blocks completed recovery without another native attempt", async t => {
  const f = await completedRecoveryFixture(t); addPartialAdoptionSibling(f);
  await assert.rejects(f.run(), /file set/); assert.equal(f.resources.length, 0); assert.equal(f.calls.length, 1);
  assert(!fs.existsSync(f.files.project)); assert(fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack));
});

test("request selector mutation inside the original clock cannot adopt a new attempt", async t => {
  const f = await completedRecoveryFixture(t);
  f.adoptionCallbacks.remaining = () => { f.recoveryInput.preparedSha256 = "0".repeat(64); };
  await assert.rejects(f.run(), /original request/); assert.equal(f.projects.length, 0); assert.equal(f.calls.length, 1);
});

test("project wait consumes the same completed-recovery allowance before global acquisition", async t => {
  const f = await completedRecoveryFixture(t); f.recoveryCallbacks.projectBefore = async () => { f.allowance.ms = 0; };
  await assert.rejects(f.run(), /allowance|remainder/); assert.equal(f.resources.length, 0);
  assert(!fs.existsSync(f.files.project)); assert(fs.existsSync(f.files.active));
});

for (const name of ["prepared", "output"] as const) {
  test(`cold global acquisition cannot rebaseline the original completed ${name}`, async t => {
    const f = await completedRecoveryFixture(t); f.recoveryCallbacks.resourceAfter = () => replaceAdoptionFile(f, name);
    await assert.rejects(f.run(), /identity/); assert.equal(f.resources.length, 1); assert.equal(f.calls.length, 1);
    assert(!fs.existsSync(f.files.project)); assert(!fs.existsSync(f.files.resource));
    assert(fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack));
  });
}

test("expired global acquisition does not retain a successfully released partial owner or touch the reservation", async t => {
  const f = await completedRecoveryFixture(t); f.recoveryCallbacks.resourceAfter = () => { f.allowance.ms = 0; };
  await assert.rejects(f.run(), /allowance|deadline|remainder/); assert.equal(f.resources.length, 1);
  assert(!fs.existsSync(f.files.project)); assert(!fs.existsSync(f.files.resource)); assert(fs.existsSync(f.files.active));
  assert.equal(observeHumanCutJob(f.recoveryInput.dir).sha256, f.before.sha256);
});

test("failure after actual adopted first CAS retains pending proof and both owners, then the pending service can resume", async t => {
  const f = await completedRecoveryFixture(t), failure = new Error("TEST interruption after adoption checkpoint");
  f.recoveryCallbacks.pending = () => { throw failure; };
  await assert.rejects(f.run(), error => error === failure);
  const current = observeHumanCutJob(f.recoveryInput.dir); assert.equal(current.job.guidedHandoffV2!.openingCleanupHash, f.recorded.factHash);
  assert(fs.existsSync(f.files.project)); assert(fs.existsSync(f.files.resource)); assert(fs.existsSync(f.files.active));
  assert(!fs.existsSync(f.files.ack)); assert(!fs.existsSync(f.files.failure)); assert.equal(f.calls.length, 1);
  f.resources[0].release(); f.projects[0].release(); f.recoveryCallbacks.pending = () => {};
  const result = await f.resumePending(); assert.equal(result.claimRetained, false); assert.equal(f.calls.length, 1);
  assert(!fs.existsSync(f.files.project)); assert(!fs.existsSync(f.files.resource)); assert(fs.existsSync(f.files.ack));
});

test("final evidence expiry preserves committed cleanup and unreleased ownership without a misleading success", async t => {
  const f = await completedRecoveryFixture(t);
  f.adoptionCallbacks.remaining = () => {
    if (!observeHumanCutJob(f.recoveryInput.dir).job.guidedHandoffV2!.openingExecutionClaimHash) f.allowance.ms = 0;
  };
  await assert.rejects(f.run(), /allowance|remainder|deadline/); assert.equal(f.calls.length, 1);
  assert(fs.existsSync(f.files.project)); assert(fs.existsSync(f.files.resource)); assert(!fs.existsSync(f.files.active));
  assert(fs.existsSync(f.files.ack)); assert(!fs.existsSync(f.files.failure));
});
