/** Live protocol regression only: actual TEMP lease/journal/launch, no native execution or media qualification. */
import assert from "node:assert/strict";
import test from "node:test";
import { beginOpeningControllerClaim, bindOpeningControllerClaim, observeOpeningControllerCleanup,
  releaseOpeningControllerLease } from "../guided-opening-controller-lifecycle";
import { executeGuidedOpeningUnderLease, openingExecutionDependencies } from "../guided-opening-execution";
import { openingControllerLifecycleFixture, replaceLifecycleJournal } from "./_guided-opening-controller-lifecycle-fixture";

test("untouched actual original preclaim lifecycle releases only its own TEMP lease", t => {
  const f = openingControllerLifecycleFixture(t); assert(Object.isFrozen(f.lifecycle)); f.guard();
  assert.equal(releaseOpeningControllerLease(f.lifecycle), true); assert.equal(f.releases(), 1);
  assert.throws(f.guard); assert.throws(() => releaseOpeningControllerLease(f.lifecycle), /cannot replay/);
});

test("copied lifecycle metadata cannot release a live lease", t => {
  const f = openingControllerLifecycleFixture(t);
  for (const value of [{ ...f.lifecycle }, JSON.parse(JSON.stringify(f.lifecycle))]) {
    assert.throws(() => releaseOpeningControllerLease(value), /actual original live/);
  }
  f.guard(); assert.equal(f.releases(), 0);
});

test("same-byte original journal substitution retains the actual lease", t => {
  const f = openingControllerLifecycleFixture(t); replaceLifecycleJournal(f);
  assert.throws(() => releaseOpeningControllerLease(f.lifecycle), /publication original/); f.guard(); assert.equal(f.releases(), 0);
});

for (const field of ["launch", "activation", "lease"] as const) {
  test(`changed original ${field} handle cannot authorize preclaim release`, t => {
    const f = openingControllerLifecycleFixture(t);
    Object.assign(f.owner, { [field]: { ...f.owner[field] } });
    assert.throws(() => releaseOpeningControllerLease(f.lifecycle), /original lifecycle/); f.guard(); assert.equal(f.releases(), 0);
  });
}

for (const mode of ["noop", "throw"] as const) {
  test(`original ${mode} release never reports confirmed release`, t => {
    const f = openingControllerLifecycleFixture(t, mode);
    assert.throws(() => releaseOpeningControllerLease(f.lifecycle), /unverified|uncertainty/); f.guard(); assert.equal(f.releases(), 1);
  });
}

test("entering claim publication retains ownership even when claim throws before a return", async t => {
  const f = openingControllerLifecycleFixture(t); let claims = 0, native = 0;
  await assert.rejects(executeGuidedOpeningUnderLease(f.input, {
    claim: () => { claims++; throw new Error("TEST claim publication failed"); },
    run: async () => { native++; throw new Error("TEST native forbidden"); },
  }, f.lifecycle), /TEST claim publication failed/);
  assert.equal(claims, 1); assert.equal(native, 0); assert.equal(releaseOpeningControllerLease(f.lifecycle), false);
  f.guard(); assert.equal(f.releases(), 0);
});

test("expired original allowance before claim leaves an untouched releasable phase", async t => {
  const f = openingControllerLifecycleFixture(t); let claims = 0;
  f.input.remainingMs = () => { throw new Error("TEST original deadline expired"); };
  await assert.rejects(executeGuidedOpeningUnderLease(f.input, { claim: () => { claims++; throw new Error("forbidden"); } }, f.lifecycle), /original deadline/);
  assert.equal(claims, 0); assert.equal(releaseOpeningControllerLease(f.lifecycle), true);
});

test("claim phase and cleanup terminal cannot be fabricated or replayed", t => {
  const f = openingControllerLifecycleFixture(t);
  assert.throws(() => observeOpeningControllerCleanup(f.lifecycle, { claimHash: "a".repeat(64), cleanupHash: "b".repeat(64) }), /no original claim/);
  beginOpeningControllerClaim(f.lifecycle, f.input);
  assert.throws(() => beginOpeningControllerClaim(f.lifecycle, f.input), /cannot replay/);
  assert.throws(() => bindOpeningControllerClaim(f.lifecycle, {} as ReturnType<typeof openingExecutionDependencies.claim>));
  assert.equal(releaseOpeningControllerLease(f.lifecycle), false); f.guard(); assert.equal(f.releases(), 0);
});

test("existing V2 preclaim fence cannot acquire claim or native authority through the live handle", async t => {
  const f = openingControllerLifecycleFixture(t), record = f.input.operation.record; let claims = 0;
  record.submission = { ...record.submission as object, schemaVersion: 2, sourceColor: { schemaVersion: 1, declarations: { test: {
    profile: null, declaration: { schemaVersion: 1, sourceId: "test", sourceProfile: "bt709-sdr", cameraProfile: null,
      historyState: "known", transformHistory: [], lightingGroups: [{ id: "whole", startFrame: 0, endFrame: 24, intent: "neutral", description: "TEST" }] } } } } };
  await assert.rejects(executeGuidedOpeningUnderLease(f.input, { claim: () => { claims++; throw new Error("forbidden"); } }, f.lifecycle), /full-reservation cleanup/);
  assert.equal(claims, 0); assert.equal(releaseOpeningControllerLease(f.lifecycle), true);
});
