/** Actual current pending capabilities and TEMP leases; no native cleanup, source reads or public activation. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { recoverSourceColorRetirementResource } from "../guided-source-color-resource-recovery";
import { acquireGradeObservationResource, gradeObservationResourceDependencies } from "../grade-observation-resource";
import { readRetainedSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { cleanupPendingReadLeaves } from "./_guided-source-color-cleanup-pending-read-fixture";
import { assertRetirementPending, insertRetirementMarker, removeRetirementMarker,
  replaceRetirementFile } from "./_guided-source-color-reservation-retirement-fixture";
import { retirementResourceFixture, assertRetirementResourceRetained, moveRetirementResource,
  replaceRetirementPendingJournal } from "./_guided-source-color-retirement-resource-fixture";

test("current pending can reacquire an existing active resource without interpreting or retiring its marker", async t => {
  const f = await retirementResourceFixture(t); f.releaseOriginal(); const held = f.recover();
  assert.deepEqual(Object.keys(held).sort(), ["assertResource", "lease", "resource"]);
  assert.equal(held.lease, f.leases[0]); assert.equal(held.resource, f.staging.resource.resource);
  assert.equal(f.recoveryEvents.acquires, 1); held.assertResource(); f.assertProject();
  assertRetirementResourceRetained(f); assertRetirementPending(f);
  held.lease.release(); assert.throws(held.assertResource, /ENOENT|replaced/); assertRetirementResourceRetained(f);
});

test("actual committed retirement can reacquire the absent marker namespace without creating it", async t => {
  const f = await retirementResourceFixture(t), retired = f.retire(); f.releaseOriginal(); const held = f.recover();
  held.assertResource(); assert(!fs.existsSync(f.files.active)); assert(fs.existsSync(retired.reference.path));
  assert.equal(f.calls.length, 1); assertRetirementPending(f); f.assertProject();
});

test("foreign or dangling active entries are deliberately left to the exact retirement primitive", async t => {
  for (const kind of ["foreign", "dangling"] as const) await t.test(kind, async t => {
    const f = await retirementResourceFixture(t); f.releaseOriginal();
    if (kind === "foreign") replaceRetirementFile(f, "active", Buffer.from("TEST unrelated marker"));
    else { removeRetirementMarker(f); insertRetirementMarker(f, true); }
    const before = fs.lstatSync(f.files.active, { bigint: true }), held = f.recover(); held.assertResource();
    assert.deepEqual(fs.lstatSync(f.files.active, { bigint: true }), before);
    assert(!fs.existsSync(f.files.ack)); assert.equal(f.calls.length, 1);
  });
});

test("fresh acquisition retains its existing any-marker fence", async t => {
  const f = await retirementResourceFixture(t); f.releaseOriginal();
  assert.throws(() => acquireGradeObservationResource("TEST fresh remains fenced", {
    ...gradeObservationResourceDependencies, workspace: () => f.staging.root,
  }), /unverified cleanup/);
  assert(!fs.existsSync(f.lock)); assertRetirementResourceRetained(f);
});

test("busy global lease remains owned by its original holder", async t => {
  const f = await retirementResourceFixture(t), bytes = fs.readFileSync(f.lock);
  assert.throws(f.recover, /busy/); assert.equal(f.leases.length, 0); assert.equal(f.recoveryEvents.acquires, 1);
  assert.deepEqual(fs.readFileSync(f.lock), bytes); f.staging.resource.assertResource(); assertRetirementResourceRetained(f);
});

test("spread and JSON pending evidence cannot acquire resources", async t => {
  const f = await retirementResourceFixture(t); f.releaseOriginal();
  for (const pending of [{ ...f.recoveryInput.pending }, JSON.parse(JSON.stringify(f.recoveryInput.pending))]) {
    assert.throws(() => recoverSourceColorRetirementResource({ ...f.recoveryInput, pending }, f.controls), /actual original read evidence/);
  }
  assert.equal(f.recoveryEvents.acquires, 0); assertRetirementResourceRetained(f);
});

test("actual retained-history capability is not a current-pending recovery capability", async t => {
  const f = await retirementResourceFixture(t);
  saveHumanCutJobSnapshot(f.before.job.ctx.dir, observeHumanCutJob(f.before.job.ctx.dir));
  const pending = readRetainedSourceColorCleanupPending(f.readInput, f.committed.pendingJournalHash, cleanupPendingReadLeaves(f));
  f.releaseOriginal();
  assert.throws(() => recoverSourceColorRetirementResource({ ...f.recoveryInput, pending }, f.controls), /actual current pending/);
  assert.equal(f.recoveryEvents.acquires, 0); assertRetirementResourceRetained(f);
});

test("original caller, lease method and dependency identities cannot change inside a namespace callback", async t => {
  for (const kind of ["pending", "project", "release", "dependency"] as const) await t.test(kind, async t => {
    const f = await retirementResourceFixture(t); f.releaseOriginal();
    const release = f.projectLease.release;
    f.controls.workspace = () => {
      if (kind === "pending") f.recoveryInput.pending = { ...f.recoveryInput.pending };
      if (kind === "project") f.recoveryInput.projectLease = { release };
      if (kind === "release") f.projectLease.release = () => {};
      if (kind === "dependency") f.controls.acquire = () => { throw new Error("TEST replaced dependency invoked"); };
      return f.staging.root;
    };
    try { assert.throws(f.recover, /original caller or dependency/); }
    finally { f.projectLease.release = release; }
    assert.equal(f.recoveryEvents.acquires, 0); assertRetirementResourceRetained(f);
  });
});

test("original pending callback identity cannot be replaced or its allowance renewed", async t => {
  for (const kind of ["guard", "remaining", "expired"] as const) await t.test(kind, async t => {
    const f = await retirementResourceFixture(t); f.releaseOriginal();
    f.recoveryCallbacks.guard = () => {
      if (kind === "guard") f.readInput.guard = () => {};
      if (kind === "remaining") f.readInput.remainingMs = () => 300_000;
      if (kind === "expired") f.timing.elapsed = 300_001;
    };
    assert.throws(f.recover, /original caller|remainder|deadline/);
    assert.equal(f.recoveryEvents.acquires, 0); assertRetirementResourceRetained(f);
  });
});

test("remaining callback after acquisition cannot release either actual lease and still return a handle", async t => {
  for (const kind of ["project", "resource"] as const) await t.test(kind, async t => {
    const f = await retirementResourceFixture(t); f.releaseOriginal();
    f.recoveryCallbacks.remaining = () => {
      if (!f.leases.length) return;
      if (kind === "project") f.projectLease.release();
      else f.leases[0].release();
    };
    assert.throws(f.recover, /ENOENT|replaced/); assert.equal(f.leases.length, 1);
    assert(!fs.existsSync(f.lock)); assertRetirementResourceRetained(f);
  });
});

test("post-acquisition current journal drift or expiry releases only the new resource", async t => {
  for (const kind of ["journal", "expiry"] as const) await t.test(kind, async t => {
    const f = await retirementResourceFixture(t); f.releaseOriginal(); let changed = false;
    f.recoveryCallbacks.remaining = () => {
      if (!f.leases.length || changed) return;
      changed = true;
      if (kind === "journal") replaceRetirementPendingJournal(f);
      else f.timing.elapsed = 300_001;
    };
    assert.throws(f.recover, /original file|remainder|deadline/); assert.equal(f.leases.length, 1);
    assert(!fs.existsSync(f.lock)); f.assertProject(); assertRetirementResourceRetained(f);
  });
});

test("a supplied lease-shaped object without an actual live project lock cannot acquire resources", async t => {
  const f = await retirementResourceFixture(t); f.releaseOriginal(); f.projectLease.release();
  assert.throws(() => recoverSourceColorRetirementResource({ pending: f.recoveryInput.pending,
    projectLease: { release: () => {} } }, f.controls), /ENOENT|lease|ownership|nonce/);
  assert.equal(f.recoveryEvents.acquires, 0); assertRetirementResourceRetained(f);
});

test("failed resource guard and uncertain release retain both errors and original reservation", async t => {
  const f = await retirementResourceFixture(t), primary = new Error("TEST binding failed"), secondary = new Error("TEST release uncertain");
  f.releaseOriginal(); const acquire = f.controls.acquire, leaseGuard = f.controls.leaseGuard;
  f.controls.acquire = (directory, operation) => {
    const result = acquire(directory, operation); assert(result.lease);
    result.lease.release = () => { throw secondary; }; return result;
  };
  f.controls.leaseGuard = (directory, lease) => {
    if (directory === f.staging.resource.resource) throw primary;
    return leaseGuard(directory, lease);
  };
  assert.throws(f.recover, error => {
    assert(error instanceof AggregateError); assert.deepEqual(error.errors, [primary, secondary]); return true;
  });
  assert(fs.existsSync(f.lock)); assertRetirementResourceRetained(f);
});

test("missing namespace is not created and no lease acquisition is attempted", async t => {
  const f = await retirementResourceFixture(t); f.releaseOriginal(); const moved = moveRetirementResource(f);
  try {
    assert.throws(f.recover, /ENOENT/); assert(!fs.existsSync(f.staging.resource.resource));
    assert(fs.existsSync(path.join(moved.target, "active.json"))); assert.equal(f.recoveryEvents.acquires, 0);
  } finally { moved.restore(); }
});

test("namespace return substitution cannot redirect global ownership", async t => {
  const f = await retirementResourceFixture(t); f.releaseOriginal(); f.controls.directory = () => f.staging.root;
  assert.throws(f.recover, /namespace/); assert.equal(f.recoveryEvents.acquires, 0); assertRetirementResourceRetained(f);
});

test("a later pending read failure does not automatically release the returned actual resource", async t => {
  const f = await retirementResourceFixture(t); f.releaseOriginal(); const held = f.recover();
  f.timing.elapsed = 300_001; assert.throws(f.recoveryInput.pending.assertCurrent, /remainder|deadline/);
  held.assertResource(); assert(fs.existsSync(f.lock)); assertRetirementResourceRetained(f);
});
