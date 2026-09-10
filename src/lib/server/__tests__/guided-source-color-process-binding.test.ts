import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import fs from "node:fs";
import path from "node:path";
import { stageGuidedSourceColor } from "../guided-source-color-staging";
import { sourceColorStagingFixture } from "./_guided-source-color-staging-fixture";
import { holdOpeningSourceColorProcess, parseOpeningSourceColorProcessReference } from "../guided-source-color-process-binding";
import type { PrepareGuidedOpeningV2 } from "../../producer/contracts/guided-source-color-v1";

/** TEST-only actual staging files/lease; no real source, clock, proposal or daemon authority. */
function fixture(t: TestContext) {
  const staging = sourceColorStagingFixture(t);
  const fault: { action: () => void } = { action: () => {} };
  staging.guard = () => fault.action();
  const staged = stageGuidedSourceColor(staging), { claim } = staging.opening;
  const submission: PrepareGuidedOpeningV2 = { schemaVersion: 2, operation: "prepare-guided-opening",
    idempotencyKey: claim.requestId, expectedToken: "TEST-only-original-token", expectedJournalHash: claim.beforeJournalHash,
    proposalReadinessHash: "b".repeat(64), treatmentDraftRevisionHash: "c".repeat(64), sourceColor: structuredClone(staging.sourceColor) };
  const context = { staging, staged, submission };
  return { context, fault, staging, staged, hold: () => holdOpeningSourceColorProcess(context) };
}

test("complete V2 clauses and exact actual raw publications become immutable process references only", t => {
  const f = fixture(t), held = f.hold();
  assert.deepEqual(held.reference.input, f.staged.input);
  assert.deepEqual(held.reference.reservation, f.staged.reservation);
  assert.match(held.reference.scope, /not-observation-cleanup-or-approval/);
  assert(Object.isFrozen(held.reference)); assert(Object.isFrozen(held.reference.input));
  held.assertCurrent(); held.assertUnstarted();
  for (const job of f.staged.jobs) assert.equal(fs.existsSync(job.executionDir), false);
});

test("changed original source clauses, request ID and prior journal never become launch transport", t => {
  const f = fixture(t), original = structuredClone(f.context.submission);
  const sourceId = Object.keys(original.sourceColor.declarations)[0];
  for (const mutate of [
    () => { f.context.submission.idempotencyKey = "22222222-2222-4222-8222-222222222222"; },
    () => { f.context.submission.expectedJournalHash = "d".repeat(64); },
    () => { f.context.submission.sourceColor.declarations[sourceId].declaration.cameraProfile = "TEST altered statement"; },
    () => { f.context.submission.sourceColor.declarations[sourceId].declaration.transformHistory.push("TEST omitted operation"); },
  ]) {
    f.context.submission = structuredClone(original); mutate(); assert.throws(f.hold);
  }
});

test("first process callback cannot replace the request or edit nested clauses before capture", t => {
  const f = fixture(t), sourceId = Object.keys(f.context.submission.sourceColor.declarations)[0];
  f.fault.action = () => { f.context.submission.sourceColor.declarations[sourceId].declaration.cameraProfile = "TEST changed"; };
  assert.throws(f.hold, /original staging or complete request/);
});

test("same-byte replacement before process binding cannot become the original staged sidecar", t => {
  const f = fixture(t), file = f.staged.input.path, replacement = path.join(path.dirname(file), "TEST-only-replacement.json");
  assert(file.startsWith(f.staging.root + path.sep));
  fs.writeFileSync(replacement, fs.readFileSync(file), { flag: "wx", mode: 0o400 }); fs.renameSync(replacement, file);
  assert.throws(f.hold, /metadata changed/);
});

test("a successful hold keeps original files and complete submission live for later intent publication", t => {
  const f = fixture(t), held = f.hold();
  f.context.submission.proposalReadinessHash = "e".repeat(64);
  assert.throws(held.assertCurrent, /original staging or complete request/);
});

test("prospective execution checks are separate from valid later metadata lifetime", t => {
  const f = fixture(t), held = f.hold(), job = f.staged.jobs[0];
  fs.mkdirSync(job.executionDir, { mode: 0o700 });
  assert.doesNotThrow(held.assertCurrent);
  assert.throws(held.assertUnstarted, /created before its owned launch/);
});

test("last caller mutation creating an execution path is refused before handoff", t => {
  const f = fixture(t), directory = f.staged.jobs[0].executionDir;
  f.fault.action = () => { if (!fs.existsSync(directory)) fs.mkdirSync(directory, { mode: 0o700 }); };
  assert.throws(f.hold, /created before its owned launch/);
});

test("JSON copies and resource lease loss do not supply live process binding", t => {
  const f = fixture(t), original = f.context.staged;
  f.context.staged = JSON.parse(JSON.stringify(original)); assert.throws(f.hold);
  f.context.staged = original; f.staging.resource.lease.release(); assert.throws(f.hold);
});

test("recorded reference is closed, path-bound, byte-bounded and grants no new fields", t => {
  const f = fixture(t), held = f.hold(), { claim } = f.staging.opening, directory = f.staging.resource.resource;
  const parse = (value: unknown) => parseOpeningSourceColorProcessReference(value, claim, directory);
  assert.deepEqual(parse(structuredClone(held.reference)), held.reference);
  for (const value of [
    { ...held.reference, schemaVersion: 2 }, { ...held.reference, cleanupVerified: true },
    { ...held.reference, sourceColorHash: "broken" }, { ...held.reference, scope: "approved" },
    { ...held.reference, input: { ...held.reference.input, path: f.staged.jobs[0].inputPath } },
    { ...held.reference, reservation: { ...held.reference.reservation, path: path.join(directory, "other.json") } },
    { ...held.reference, input: { ...held.reference.input, executable: true } },
  ]) assert.throws(() => parse(value));
  for (const sizeBytes of [0, -1, 1.5, 8 * 1024 * 1024 + 1, "1", null]) {
    assert.throws(() => parse({ ...held.reference, input: { ...held.reference.input, sizeBytes } }));
  }
});
