/** Live terminal-release composition only; no source/model/native/media or creative qualification. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test, { type TestContext } from "node:test";
import { observeOpeningControllerCleanup, releaseOpeningControllerLease } from "../guided-opening-controller-lifecycle";
import { openingControllerTerminalFixture } from "./_guided-opening-controller-terminal-fixture";
import { launchOpeningControllerFixture, mockOpeningControllerIdentity } from "./_guided-opening-controller-lifecycle-fixture";
import { replaceReadIntegrationArchive } from "./_guided-source-color-read-integration-fixture";

function fixture(t: TestContext) {
  mockOpeningControllerIdentity(t);
  const startedAt = new Date(); startedAt.setUTCSeconds(0, 0);
  return openingControllerTerminalFixture(t, { start: input => launchOpeningControllerFixture(input.dir, input.before, {
    sourceColor: input.sourceColor, token: input.token, requestId: "a8b9ce05-29ec-4bba-93cf-982d811ed137",
    origin: { clockHash: "a".repeat(64), startedAt: startedAt.toISOString() },
  }) });
}

test("same original preclaim owner releases only after actual final cleanup is authenticated", async t => {
  const f = await fixture(t); f.parent.guard();
  assert.equal(releaseOpeningControllerLease(f.parent.lifecycle), false);
  const actual = observeOpeningControllerCleanup(f.parent.lifecycle, { claimHash: f.entered.bound.claimHash, cleanupHash: f.cleanup.cleanupHash });
  assert.equal(actual.receipt.claimRetained, false);
  assert.equal(actual.held.claim.beforeJournalHash, f.parent.before.sha256);
  assert.equal(actual.held.claimSha256, f.entered.bound.claimSha256);
  assert.equal(releaseOpeningControllerLease(f.parent.lifecycle), true); assert.throws(f.parent.guard);
  assert.throws(() => releaseOpeningControllerLease(f.parent.lifecycle), /cannot replay/);
});

test("a wrong cleanup reference cannot discharge the original live claim phase", async t => {
  const f = await fixture(t);
  assert.throws(() => observeOpeningControllerCleanup(f.parent.lifecycle, {
    claimHash: f.entered.bound.claimHash, cleanupHash: "0".repeat(64) }), /not terminal/);
  assert.equal(releaseOpeningControllerLease(f.parent.lifecycle), false); f.parent.guard();
});

test("later verification failure does not undo already proved exact cleanup", async t => {
  const f = await fixture(t);
  observeOpeningControllerCleanup(f.parent.lifecycle, { claimHash: f.entered.bound.claimHash, cleanupHash: f.cleanup.cleanupHash });
  const directory = path.join(path.dirname(f.entered.bound.claimPath), "readback-attempts", "TEST-verification-failure");
  assert(directory.startsWith(fs.realpathSync(f.staging.root) + path.sep));
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  fs.writeFileSync(path.join(directory, "failure.json"), JSON.stringify({ TEST: "independent later read failed; no cleanup failure" }), { flag: "wx", mode: 0o600 });
  assert.equal(releaseOpeningControllerLease(f.parent.lifecycle), true); assert.throws(f.parent.guard);
});

test("same-byte retirement archive replacement after terminal observation retains the original lease", async t => {
  const f = await fixture(t);
  observeOpeningControllerCleanup(f.parent.lifecycle, { claimHash: f.entered.bound.claimHash, cleanupHash: f.cleanup.cleanupHash });
  replaceReadIntegrationArchive(f);
  assert.throws(() => releaseOpeningControllerLease(f.parent.lifecycle)); f.parent.guard();
});
