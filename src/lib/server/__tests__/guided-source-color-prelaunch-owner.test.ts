/** Preparatory live gates only: no cancellation unlink/ack/CAS, native child, resource release or media qualification. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { holdSourceColorPrelaunch, enterSourceColorPrelaunchDispatch, enterSourceColorPrelaunchCancel,
  readSourceColorPrelaunchMetadata, beginSourceColorPrelaunchStaging } from "../guided-source-color-prelaunch-owner";
import { releaseOpeningControllerLease } from "../guided-opening-controller-lifecycle";
import { stageGuidedSourceColor } from "../guided-source-color-staging";
import { holdOpeningSourceColorProcess } from "../guided-source-color-process-binding";
import { prelaunchFixture, prelaunchJobs, replacePrelaunchFile, assertPrelaunchRetained } from "./_guided-source-color-prelaunch-fixture";

test("actual original owner retains ordered successful staging references without granting dispatch", t => {
  const f = prelaunchFixture(t), owner = f.hold(); assert(Object.isFrozen(owner));
  assert.equal(readSourceColorPrelaunchMetadata(owner).phase, "held");
  const staged = f.stage(owner), record = readSourceColorPrelaunchMetadata(owner);
  assert.equal(record.phase, "staged"); assert.equal(record.publications.length, 8);
  assert.deepEqual(record.publications, [staged.reservation, ...staged.jobs.flatMap(row => [row.implementation, row.input, row.launchClaim]), staged.input]);
  assert.deepEqual(record.reservation!.reference, staged.reservation);
  assert.equal(record.cleanupVerified, false); assert.equal(record.cancellationComplete, false); assert.equal(record.dispatchAuthorized, false);
  assertPrelaunchRetained(f, fs.readFileSync(f.active)); assert.equal(releaseOpeningControllerLease(f.parent.lifecycle), false);
});

test("owner DTOs and reusing the same actual claim are refused", t => {
  const f = prelaunchFixture(t), owner = f.hold();
  for (const dto of [{ ...owner }, JSON.parse(JSON.stringify(owner))]) {
    assert.throws(() => readSourceColorPrelaunchMetadata(dto), /actual live owner/);
    assert.throws(() => enterSourceColorPrelaunchCancel(dto), /actual live owner/);
    assert.throws(() => f.stage(dto), /actual live owner/);
  }
  assert.throws(f.hold, /already consumed/); f.assertLeases(); assert(!fs.existsSync(f.active));
});

for (const field of ["controller", "claim", "projectLease"] as const) test(`a copied ${field} cannot establish a live owner`, t => {
  const f = prelaunchFixture(t); f.input[field] = { ...f.input[field] } as never;
  assert.throws(() => holdSourceColorPrelaunch(f.input), /actual|original|same/); f.assertLeases(); assert(!fs.existsSync(f.active));
});

test("first work callback failure preserves a known staging phase and no invented reservation", t => {
  const f = prelaunchFixture(t), owner = f.hold(), failure = new Error("TEST original work expired");
  f.staging.onGuard(() => { throw failure; }); assert.throws(() => f.stage(owner), error => error === failure);
  const record = readSourceColorPrelaunchMetadata(owner); assert.equal(record.phase, "staging"); assert.equal(record.reservation, null);
  enterSourceColorPrelaunchCancel(owner); assert.equal(readSourceColorPrelaunchMetadata(owner).phase, "cancel-entered");
  assert(!fs.existsSync(f.active)); f.assertLeases();
});

test("the original reservation is retained before its first post-publication work callback", t => {
  const f = prelaunchFixture(t), owner = f.hold(), failure = new Error("TEST after actual reservation publication");
  f.staging.onGuard(() => { if (fs.existsSync(f.active)) throw failure; });
  assert.throws(() => f.stage(owner), error => error === failure);
  const record = readSourceColorPrelaunchMetadata(owner);
  assert.equal(record.publications.length, 1); assert.equal(record.reservation!.reference.path, f.active);
  assert.deepEqual(record.reservation!.value, JSON.parse(fs.readFileSync(f.active, "utf8")));
  assert.equal((record.reservation!.value as { jobs: unknown[] }).jobs.length, 2);
  enterSourceColorPrelaunchCancel(owner); assertPrelaunchRetained(f, fs.readFileSync(f.active));
});

test("a later job publication remains retained when its post-write guard throws", t => {
  const f = prelaunchFixture(t), owner = f.hold(), failure = new Error("TEST after first input publication");
  f.staging.onGuard(() => {
    if (fs.existsSync(f.active) && fs.existsSync(prelaunchJobs(f)[0].inputPath)) throw failure;
  });
  assert.throws(() => f.stage(owner), error => error === failure);
  const record = readSourceColorPrelaunchMetadata(owner);
  assert.equal(record.publications.length, 3); assert.equal(record.publications.at(-1)!.path, prelaunchJobs(f)[0].inputPath);
  assert.equal(record.cancellationComplete, false); enterSourceColorPrelaunchCancel(owner);
  assertPrelaunchRetained(f, fs.readFileSync(f.active));
});

test("cancel entry from an original staging callback stops the outer stage before publication", t => {
  const f = prelaunchFixture(t), owner = f.hold(); let entered = false;
  f.staging.onGuard(() => { if (!entered) { entered = true; enterSourceColorPrelaunchCancel(owner); } });
  assert.throws(() => f.stage(owner), /no longer permits staging/);
  assert.equal(readSourceColorPrelaunchMetadata(owner).phase, "cancel-entered"); assert(!fs.existsSync(f.active)); f.assertLeases();
});

test("dispatch entry is irreversible even when the original work callback then expires", t => {
  const f = prelaunchFixture(t), owner = f.hold(), staged = f.stage(owner), failure = new Error("TEST original dispatch expiry");
  f.staging.onGuard(() => { throw failure; });
  assert.throws(() => enterSourceColorPrelaunchDispatch(owner, staged), error => error === failure);
  assert.equal(readSourceColorPrelaunchMetadata(owner).phase, "dispatch-entered");
  assert.throws(() => enterSourceColorPrelaunchCancel(owner), /cannot replay or follow dispatch/);
  assert.throws(() => enterSourceColorPrelaunchDispatch(owner, staged)); assertPrelaunchRetained(f, fs.readFileSync(f.active));
});

test("dispatch guards cannot reenter cancel or dispatch transitions", t => {
  const f = prelaunchFixture(t), owner = f.hold(), staged = f.stage(owner); let observed = false;
  f.staging.onGuard(() => {
    observed = true; assert.throws(() => enterSourceColorPrelaunchCancel(owner));
    assert.throws(() => enterSourceColorPrelaunchDispatch(owner, staged));
  });
  enterSourceColorPrelaunchDispatch(owner, staged); assert(observed);
  assert.equal(readSourceColorPrelaunchMetadata(owner).phase, "dispatch-entered"); f.assertLeases();
});

test("copied staging and a second staging entry cannot advance the owner", t => {
  const f = prelaunchFixture(t), owner = f.hold(), staged = f.stage(owner);
  assert.throws(() => enterSourceColorPrelaunchDispatch(owner, { ...staged }), /same actual/);
  assert.throws(() => stageGuidedSourceColor(f.staging, owner), /cannot replay/);
  enterSourceColorPrelaunchCancel(owner); assert.throws(() => enterSourceColorPrelaunchCancel(owner), /cannot replay/);
  assert.throws(() => enterSourceColorPrelaunchDispatch(owner, staged)); assertPrelaunchRetained(f, fs.readFileSync(f.active));
});

for (const role of ["claim", "input", "journal"] as const) test(`original ${role} identity precedes the first work callback`, t => {
  const f = prelaunchFixture(t), owner = f.hold(); let changed = false;
  f.staging.onGuard(() => { if (!changed) { changed = true; replacePrelaunchFile(f, role); } });
  assert.throws(() => f.stage(owner)); assert(changed); assert.throws(() => readSourceColorPrelaunchMetadata(owner));
  f.assertLeases(); assert(!fs.existsSync(f.active));
});

test("same-byte reservation replacement cannot rebaseline retained publication metadata", t => {
  const f = prelaunchFixture(t), owner = f.hold(); f.stage(owner); replacePrelaunchFile(f, "reservation");
  assert.throws(() => readSourceColorPrelaunchMetadata(owner), /staging metadata changed/);
  assert.throws(() => enterSourceColorPrelaunchCancel(owner)); f.assertLeases();
});

test("first work callback cannot substitute the original project lease", t => {
  const f = prelaunchFixture(t), owner = f.hold(); f.staging.onGuard(() => { f.input.projectLease = { ...f.parent.lease }; });
  assert.throws(() => f.stage(owner), /original caller or lease/); f.assertLeases(); assert(!fs.existsSync(f.active));
});

test("final owner callback cannot release the resource and return a usable cancel-entry result", t => {
  const f = prelaunchFixture(t), original = f.staging.resource.assertResource; let release = false;
  f.staging.resource.assertResource = () => { original(); if (release) f.staging.resource.lease.release(); };
  const owner = f.hold(); release = true;
  assert.throws(() => enterSourceColorPrelaunchCancel(owner)); f.parent.guard();
  assert.throws(() => readSourceColorPrelaunchMetadata(owner)); assert(!fs.existsSync(f.active));
});

test("final resource callback cannot release the original project lease and accept cancel entry", t => {
  const f = prelaunchFixture(t), original = f.staging.resource.assertResource; let release = false;
  f.staging.resource.assertResource = () => { original(); if (release) f.parent.lease.release(); };
  const owner = f.hold(); release = true;
  assert.throws(() => enterSourceColorPrelaunchCancel(owner)); assert.throws(f.parent.guard);
  original(); assert.throws(() => readSourceColorPrelaunchMetadata(owner));
  assert.throws(() => enterSourceColorPrelaunchCancel(owner), /cannot replay/); assert(!fs.existsSync(f.active));
});

test("detached metadata cannot change original publications or impersonate cancellation completion", t => {
  const f = prelaunchFixture(t), owner = f.hold(); f.stage(owner);
  const record = readSourceColorPrelaunchMetadata(owner), changed = JSON.parse(JSON.stringify(record));
  changed.publications.length = 0; changed.cancellationComplete = true;
  assert.equal(readSourceColorPrelaunchMetadata(owner).publications.length, 8);
  assert.equal(readSourceColorPrelaunchMetadata(owner).cancellationComplete, false);
  assert.throws(() => enterSourceColorPrelaunchCancel(changed), /actual live owner/); f.assertLeases();
});

test("a retained internal reader alias cannot clear the original file inventory", t => {
  const f = prelaunchFixture(t), owner = f.hold(), reader = beginSourceColorPrelaunchStaging(owner, f.staging);
  Object.assign(reader, { files: new Map(), directories: new Map() });
  replacePrelaunchFile(f, "claim");
  assert.throws(() => readSourceColorPrelaunchMetadata(owner), /staging metadata changed/); f.assertLeases();
});

test("owned staged metadata remains usable by the actual existing process binder before and after dispatch entry", t => {
  const f = prelaunchFixture(t), owner = f.hold(), staged = f.stage(owner), submission = f.parent.records.held.intent.submission;
  assert(submission.schemaVersion === 2); staged.assertCurrent(); staged.assertUnstarted();
  const binding = holdOpeningSourceColorProcess({ staging: f.staging, staged, submission });
  binding.assertCurrent(); enterSourceColorPrelaunchDispatch(owner, staged); binding.assertCurrent(); binding.assertUnstarted();
  assertPrelaunchRetained(f, fs.readFileSync(f.active));
});

test("a retained reader alias cannot recapture an original file after same-byte replacement", t => {
  const f = prelaunchFixture(t), owner = f.hold(), reader = beginSourceColorPrelaunchStaging(owner, f.staging);
  replacePrelaunchFile(f, "claim");
  const alias = reader as unknown as { capture(file: string, hash: string): void };
  assert.throws(() => alias.capture(f.entered.bound.claimPath, f.entered.bound.claimSha256), /metadata reference changed/);
  assert.throws(() => readSourceColorPrelaunchMetadata(owner)); f.assertLeases();
});
