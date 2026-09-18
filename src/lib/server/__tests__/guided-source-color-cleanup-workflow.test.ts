/** Real local orchestration/locks/records/CAS/unlink; native/source/tool admission are TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { cleanupWorkflowFixture, assertWorkflowBeforeCommit, assertWorkflowFinalRetained,
  replaceWorkflowFinalFile } from "./_guided-source-color-cleanup-workflow-fixture";

test("actual live workflow records cleanup, both CAS phases and exact retirement once under the same leases", async t => {
  const f = cleanupWorkflowFixture(t), result = await f.run();
  t.diagnostic(`actual TEST live workflow wall=${f.measuredMs().toFixed(3)}ms; native/enclosing elapsed remain TEST leaves`);
  assert.equal(result.claimHash, f.input.held.claimHash); assert.equal(result.claimRetained, false);
  assert.equal(result.resourceCleanup, "verified"); assert.equal(result.mediaSelected, false);
  assert.equal(result.openingApproved, false); assert.equal(result.deliveryApproved, false);
  assert.equal(f.counts.run, 1); assertWorkflowFinalRetained(f); f.assertLeases();
});

test("a retained current attempt cannot be recreated or replayed", async t => {
  const f = cleanupWorkflowFixture(t); fs.mkdirSync(f.directory, { mode: 0o700 });
  await assert.rejects(f.run(), { code: "EEXIST" }); assert.equal(f.counts.run, 0); assertWorkflowBeforeCommit(f);
});

test("expired original allowance refuses before an attempt directory or native work", async t => {
  const f = cleanupWorkflowFixture(t); f.timing.elapsed = 300_000;
  await assert.rejects(f.run(), /original protected remainder/); assert.equal(f.counts.run, 0);
  assert(!fs.existsSync(f.directory)); assertWorkflowBeforeCommit(f);
});

test("the workflow retains actual failed native evidence without retirement or another attempt", async t => {
  const f = cleanupWorkflowFixture(t), error = new Error("TEST original cleanup child failed");
  f.dependencies.invoke = async () => { throw error; };
  await assert.rejects(f.run(), failure => failure === error);
  assert(fs.existsSync(path.join(f.directory, "start.json"))); assert(fs.existsSync(path.join(f.directory, "invocation.json")));
  assert(!fs.existsSync(path.join(f.directory, "output.json"))); assertWorkflowBeforeCommit(f);
  await assert.rejects(f.run(), { code: "EEXIST" }); assert.equal(f.counts.run, 1);
});

for (const lease of ["project", "resource"] as const) test(`missing actual ${lease} lease prevents a native workflow`, async t => {
  const f = cleanupWorkflowFixture(t);
  if (lease === "project") f.projectLease.release(); else f.staging.resource.lease.release();
  await assert.rejects(f.run(), /ENOENT|lease/); assert.equal(f.counts.run, 0); assertWorkflowBeforeCommit(f);
});

test("replacing the original caller clock in its callback cannot renew the workflow", async t => {
  const f = cleanupWorkflowFixture(t);
  f.clockCallbacks.remaining = () => { f.workflowInput.clock = { ...f.workflowInput.clock }; };
  await assert.rejects(f.run(), /original caller metadata changed/); assert.equal(f.counts.run, 0); assertWorkflowBeforeCommit(f);
});

test("a workspace callback cannot redirect the original live resource", async t => {
  const f = cleanupWorkflowFixture(t); f.workflowControls.workspace = () => f.staging.producerDir;
  await assert.rejects(f.run(), /original V2 global resource/); assert.equal(f.counts.run, 0); assertWorkflowBeforeCommit(f);
});

test("clock expiry at the workflow return retains a possibly committed final cleanup", async t => {
  const f = cleanupWorkflowFixture(t); let expired = false;
  f.clockCallbacks.remaining = () => {
    const current = observeHumanCutJob(f.before.job.ctx.dir);
    if (!current.job.guidedHandoffV2!.openingExecutionClaimHash) { expired = true; f.timing.elapsed = 300_000; }
  };
  await assert.rejects(f.run(), /original protected remainder/); assert(expired);
  assertWorkflowFinalRetained(f); f.assertLeases();
});

test("blind retry after final cleanup cannot invoke cleanup again or alter retained evidence", async t => {
  const f = cleanupWorkflowFixture(t); await f.run();
  const before = observeHumanCutJob(f.before.job.ctx.dir).sha256;
  await assert.rejects(f.run(), /original precleanup journal changed/);
  assert.equal(observeHumanCutJob(f.before.job.ctx.dir).sha256, before); assertWorkflowFinalRetained(f);
});

for (const file of ["journal", "ack"] as const) test(`final workflow clock callback cannot replace the committed ${file}`, async t => {
  const f = cleanupWorkflowFixture(t); let replaced = false;
  f.clockCallbacks.remaining = () => {
    const current = observeHumanCutJob(f.before.job.ctx.dir);
    if (!replaced && !current.job.guidedHandoffV2!.openingExecutionClaimHash) {
      replaced = true; replaceWorkflowFinalFile(f, file);
    }
  };
  await assert.rejects(f.run(), /identity changed|bytes or identity changed/);
  assert(replaced); assertWorkflowFinalRetained(f); f.assertLeases();
});
