/** TEMP protocol qualification only: explicit TEST attestation and native/readiness stubs, no real human or media approval. */
import assert from "node:assert/strict";
import test from "node:test";
import { readGuidedObject } from "../guided-cut-v2-store";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { sourceColorApprovalFixture, replaceApprovalFixtureFile } from "./_guided-source-color-approval-fixture";

test("actual schema2 selection and owned requalification commit only the explicitly submitted TEST decision", async t => {
  const f = await sourceColorApprovalFixture(t), result = await f.approve();
  const current = observeHumanCutJob(f.input.dir), fact = readGuidedObject(f.input.dir, result.approvalHash);
  assert.equal(current.job.guidedHandoffV2!.openingApprovalHash, result.approvalHash);
  assert.equal(current.job.guidedHandoffV2!.openingMediaSelectionHash, f.selected.selectionHash);
  assert.equal(fact.schemaVersion, 2); assert.deepEqual(fact.decision, f.input.submission);
  assert.equal(fact.beforeJournalHash, f.selected.observed.sha256);
  assert.equal(fact.openingApproved, true); assert.equal(fact.bodyGenerated, false); assert.equal(fact.deliveryApproved, false);
  assert.equal(f.calls.verifier, 1); assert.equal(f.calls.native, 1); f.assertProject();
});

test("missing explicit listening attestation refuses before requalification or approval publication", async t => {
  const f = await sourceColorApprovalFixture(t);
  Object.assign(f.input.submission.attestation, { listened: false });
  await assert.rejects(f.approve(), /attestation/); assert.equal(f.calls.verifier, 0);
  assert(!observeHumanCutJob(f.input.dir).job.guidedHandoffV2!.openingApprovalHash);
});

test("replacement of the original protected callback cannot buy a new approval allowance", async t => {
  const f = await sourceColorApprovalFixture(t);
  f.callbacks.beforeVerify = () => { f.input.remainingMs = () => 600_000; };
  await assert.rejects(f.approve(), /original caller/);
  assert(!observeHumanCutJob(f.input.dir).job.guidedHandoffV2!.openingApprovalHash);
});

test("a same-byte media replacement after actual requalification cannot reach approval CAS", async t => {
  const f = await sourceColorApprovalFixture(t);
  f.callbacks.afterVerify = () => replaceApprovalFixtureFile(f, "core");
  await assert.rejects(f.approve());
  assert(!observeHumanCutJob(f.input.dir).job.guidedHandoffV2!.openingApprovalHash); f.assertProject();
});

test("a copied selection DTO cannot authorize an explicit schema2 decision", async t => {
  const f = await sourceColorApprovalFixture(t); f.input.selected = { ...f.selected };
  await assert.rejects(f.approve(), /actual|original/); assert.equal(f.calls.verifier, 0);
  assert(!observeHumanCutJob(f.input.dir).job.guidedHandoffV2!.openingApprovalHash);
});
