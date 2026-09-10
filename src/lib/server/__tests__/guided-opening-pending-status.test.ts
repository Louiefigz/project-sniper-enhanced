/** Actual TEMP writer/CAS/pending reader; original claim/native admission remain explicit TEST leaves. */
import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import { guidedOpeningStatusReads, readGuidedOpeningStatus } from "../guided-opening-status";
import { openingCleanupStoreDependencies, readPendingOpeningCleanup, assertPendingOpeningCleanupRead } from "../guided-opening-cleanup-store";
import { readSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { canonicalJson } from "../auto-edit-hash";
import { parseGuidedOpeningStatus } from "@/lib/producer/guided-opening-client";
import { cleanupPendingReadFixture, replacePendingFile } from "./_guided-source-color-cleanup-pending-read-fixture";

/** Retain actual pending proof and its exact clock; no fake private capability replaces the reader. */
async function fixture(t: TestContext) {
  const f = await cleanupPendingReadFixture(t), calls = { claim: 0, pending: 0, cleanup: 0, stopped: 0, job: 0 };
  const dir = f.before.job.ctx.dir, callbacks = { job: () => {}, pending: () => {} };
  t.mock.method(openingCleanupStoreDependencies, "pending", (input: Parameters<typeof readSourceColorCleanupPending>[0]) => {
    calls.pending++; callbacks.pending(); return readSourceColorCleanupPending(input, f.pendingDependencies);
  });
  const reads = { ...guidedOpeningStatusReads,
    job: () => { calls.job++; callbacks.job(); return observeHumanCutJob(dir); },
    claim: () => { calls.claim++; throw new Error("TEST strict current claim rejects the additional prepared cleanup pointer"); },
    cleanup: () => { calls.cleanup++; throw new Error("TEST final cleanup must not be consulted"); },
    stopped: () => { calls.stopped++; throw new Error("TEST pending proof retains its own actual stopped return"); } };
  return { ...f, dir, statusCounts: calls, statusCallbacks: callbacks, statusReads: reads, status: () => readGuidedOpeningStatus(dir, reads) };
}

test("current prepared cleanup displays pending retirement with no media, cleanup completion or approval", async t => {
  assert.equal(openingCleanupStoreDependencies.pending, readSourceColorCleanupPending);
  const f = await fixture(t), status = f.status();
  assert.equal(status.state, "pending-cleanup"); assert.equal(status.claimHash, f.input.held.claimHash);
  assert.equal(status.executionId, f.input.held.claim.executionId); assert.match(status.detail, /retirement.*remain pending/);
  assert.equal(status.timing.engineElapsedMs, Number(f.actual.receipt.elapsedMs)); assert.equal(status.timing.cleanupElapsedMs, null);
  assert.equal(status.openingApproved, false); assert.equal(status.deliveryApproved, false); assert.equal("media" in status, false);
  assert.deepEqual(parseGuidedOpeningStatus(JSON.parse(JSON.stringify(status)), f.dir), status);
  assert.equal(f.statusCounts.claim, 1); assert.equal(f.statusCounts.pending, 1); assert.equal(f.statusCounts.cleanup, 0); assert.equal(f.statusCounts.stopped, 0);
  assert.equal(observeHumanCutJob(f.dir).sha256, f.current.sha256);
});

test("only the actual wrapper read carries its original final metadata and observation allowance", async t => {
  const f = await fixture(t), pending = readPendingOpeningCleanup(f.dir);
  assertPendingOpeningCleanupRead(pending);
  assert.throws(() => assertPendingOpeningCleanupRead({ ...pending }), /actual original bounded proof/);
  assert.throws(() => assertPendingOpeningCleanupRead(f.read()), /actual original bounded proof/);
  t.mock.method(openingCleanupStoreDependencies, "pending", (input: Parameters<typeof readSourceColorCleanupPending>[0]) =>
    ({ ...readSourceColorCleanupPending(input, f.pendingDependencies) }));
  assert.throws(() => readPendingOpeningCleanup(f.dir), /actual original read evidence/);
});

test("wrapper expiry is the one 30s proof allowance even after actual pending capture", async t => {
  const f = await fixture(t); let now = 1000;
  t.mock.method(performance, "now", () => now);
  const pending = readPendingOpeningCleanup(f.dir); now += 30_001;
  assert.throws(() => assertPendingOpeningCleanupRead(pending), /observation budget expired/);
  f.statusCallbacks.pending = () => { now += 30_001; };
  assert.throws(f.status, /observation budget expired/);
});

test("status charges its last journal callback to the same pending proof allowance", async t => {
  const f = await fixture(t); let now = 1000;
  t.mock.method(performance, "now", () => now);
  f.statusCallbacks.job = () => { if (f.statusCounts.job === 2) now += 30_001; };
  assert.throws(f.status, /observation budget expired/);
});

for (const name of ["journal", "fact", "result", "snapshot"] as const) {
  test(`status last journal callback cannot replace original pending ${name} bytes or inode`, async t => {
    const f = await fixture(t);
    f.statusCallbacks.job = () => { if (f.statusCounts.job === 2) replacePendingFile(f, name); };
    assert.throws(f.status, /identity changed|parent identity/);
  });
}

test("prepared proof from another current journal cannot be displayed for the original observation", async t => {
  const f = await fixture(t), original = f.current;
  const changed = structuredClone(original.job); changed.message = "TEST foreign journal projection";
  f.statusReads.job = () => ({ ...original, sha256: "b".repeat(64), job: changed });
  assert.throws(() => readGuidedOpeningStatus(f.dir, f.statusReads), /another original journal/);
});

test("same-hash initial DTO with another claim cannot borrow actual current pending evidence", async t => {
  const f = await fixture(t), before = observeHumanCutJob(f.dir);
  before.job.guidedHandoffV2!.openingExecutionClaimHash = "b".repeat(64);
  f.statusReads.job = () => before;
  assert.throws(f.status, /another original journal or claim/);
});

test("claim callback cannot replace the first observed claim pointer while retaining its raw hash", async t => {
  const f = await fixture(t), before = observeHumanCutJob(f.dir);
  f.statusReads.job = () => before;
  f.statusReads.claim = () => {
    before.job.guidedHandoffV2!.openingExecutionClaimHash = "b".repeat(64);
    throw new Error("TEST strict claim failure with a changed earlier DTO");
  };
  assert.throws(f.status, /changed during observation/);
});

test("the complete pending reader rejects an unjoined job instead of masking current claim failure", async t => {
  const f = await fixture(t), job = structuredClone(f.current.job); job.message = "TEST changed pending transition";
  replacePendingFile(f, "journal", Buffer.from(canonicalJson(job)));
  assert.throws(f.status, /entire deterministic pending job/);
  assert.equal(f.statusCounts.cleanup, 0); assert.equal(f.statusCounts.stopped, 0);
});

for (const kind of ["legacy", "final", "unknown"] as const) {
  test(`${kind} cleanup discriminant cannot acquire a pending proof read`, async t => {
    const f = await fixture(t), versions = { legacy: 1, final: 2, unknown: 9 };
    const kinds = { legacy: "guided-opening-cleanup-commit", final: "guided-opening-source-color-cleanup-commit", unknown: "TEST-unknown" };
    replacePendingFile(f, "fact", Buffer.from(canonicalJson({ ...f.recorded.fact, schemaVersion: versions[kind], kind: kinds[kind] })));
    assert.throws(() => readPendingOpeningCleanup(f.dir)); assert.equal(f.statusCounts.pending, 0);
  });
}

test("an actual malformed or unresolved stopped attempt cannot become pending retirement", async t => {
  const f = await fixture(t), original = f.readerDependencies.stopped;
  t.mock.method(f.readerDependencies, "stopped", () => ({ ...original(), nestedOwnership: "unresolved-unknown-descendant" }));
  assert.throws(f.status, /resolved original V3 media settlement/);
  assert.equal(f.statusCounts.cleanup, 0); assert.equal(f.statusCounts.stopped, 0);
});
