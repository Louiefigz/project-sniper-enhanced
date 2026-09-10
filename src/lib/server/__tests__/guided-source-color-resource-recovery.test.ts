/** Metadata recovery only: real TEMP leases and raw holds, explicitly stubbed OS/journal admission. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { recoverSourceColorResource, sourceColorResourceRecoveryDependencies } from "../guided-source-color-resource-recovery";
import { readStoppedOpeningProcess } from "../guided-opening-process";
import { acquireGradeObservationResource } from "../grade-observation-resource";
import { copySourceColorCleanupReservation } from "../guided-source-color-cleanup-hold";
import { sourceColorRecoveryFixture, replaceRecoveryReservation } from "./_guided-source-color-resource-recovery-fixture";

test("production default is the actual stopped reader, never a serialized settlement flag", () => {
  assert.equal(sourceColorResourceRecoveryDependencies.stopped, readStoppedOpeningProcess);
});

test("cold acquisition holds full reservation and rereads original stopped evidence on every check", t => {
  const f = sourceColorRecoveryFixture(t), before = fs.lstatSync(f.staged.reservation.path, { bigint: true });
  f.releaseOriginal(); const held = recoverSourceColorResource(f.input, f.dependencies);
  assert.equal(held.lease, f.leases[0]); assert.equal(held.resource, f.staging.resource.resource);
  assert.equal(f.events.reads, 2); assert.equal(f.events.acquires, 1);
  assert.deepEqual(held.cleanupHold.containerNames, f.staged.jobs.map(job => job.containerName));
  held.assertCurrent(); assert.equal(f.events.reads, 3); held.assertResource();
  assert.equal(Object.isFrozen(f.input.held), false); assert.equal(Object.isFrozen(f.input.stopped), false);
  assert.deepEqual(fs.lstatSync(f.staged.reservation.path, { bigint: true }), before);
  held.lease.release(); assert.equal(fs.existsSync(f.lock), false); assert(fs.existsSync(f.staged.reservation.path));
});

test("busy original resource is retained and no foreign lease is released", t => {
  const f = sourceColorRecoveryFixture(t), lock = fs.readFileSync(f.lock), active = fs.readFileSync(f.staged.reservation.path);
  assert.throws(() => recoverSourceColorResource(f.input, f.dependencies), /busy/);
  assert.equal(f.events.acquires, 1); assert.equal(f.leases.length, 0); f.staging.resource.assertResource();
  assert.deepEqual(fs.readFileSync(f.lock), lock); assert.deepEqual(fs.readFileSync(f.staged.reservation.path), active);
});

test("fresh acquisition still refuses the same valid active reservation without changing it", t => {
  const f = sourceColorRecoveryFixture(t), bytes = fs.readFileSync(f.staged.reservation.path); f.releaseOriginal();
  assert.throws(() => acquireGradeObservationResource("TEST fresh remains fenced", {
    ...f.dependencies, guard: f.dependencies.leaseGuard, activeExists: file => fs.lstatSync(file).isFile(),
  }), /unverified cleanup/);
  assert.equal(fs.existsSync(f.lock), false); assert.deepEqual(fs.readFileSync(f.staged.reservation.path), bytes);
});

test("actual reader refusal or unresolved V3 evidence fails before lease acquisition", async t => {
  for (const kind of ["reader", "forced", "version", "reference", "nested", "outcome"] as const) await t.test(kind, t => {
    const f = sourceColorRecoveryFixture(t); f.releaseOriginal();
    if (kind === "reader") f.callbacks.read = () => { throw new Error("TEST actual reader refused"); };
    if (kind === "forced") f.actual.receipt.forcedStop = true;
    if (kind === "version") f.actual.receipt.schemaVersion = 2;
    if (kind === "reference") f.actual.sourceColor.reservation = { ...f.actual.sourceColor.reservation, sha256: "0".repeat(64) };
    if (kind === "nested") Object.assign(f.actual, { nestedOwnership: "unresolved-live-recorded-descendant" });
    if (kind === "outcome") f.actual.receiptSha256 = "0".repeat(64);
    assert.throws(() => recoverSourceColorResource(f.input, f.dependencies));
    assert.equal(f.events.acquires, 0); assert.equal(fs.existsSync(f.lock), false); assert(fs.existsSync(f.staged.reservation.path));
  });
});

test("original context and raw files cannot be adopted after the first project callback", async t => {
  for (const kind of ["claim", "request", "stop", "callback", "file"] as const) await t.test(kind, t => {
    const f = sourceColorRecoveryFixture(t); f.releaseOriginal();
    f.callbacks.guard = () => {
      if (kind === "claim") f.input.held.claimSha256 = "0".repeat(64);
      if (kind === "request") f.input.held.submission.expectedToken = "TEST changed";
      if (kind === "stop") f.input.stopped.receiptSha256 = "0".repeat(64);
      if (kind === "callback") f.input.remainingMs = () => 300_000;
      if (kind === "file") replaceRecoveryReservation(f);
    };
    assert.throws(() => recoverSourceColorResource(f.input, f.dependencies), /original/);
    assert.equal(f.events.acquires, 0); assert.equal(fs.existsSync(f.lock), false);
  });
});

test("post-acquisition stopped drift releases only the new lease and retains all active bytes", t => {
  const f = sourceColorRecoveryFixture(t), bytes = fs.readFileSync(f.staged.reservation.path); f.releaseOriginal();
  f.callbacks.read = () => { if (f.events.reads === 2) f.actual.receiptSha256 = "0".repeat(64); };
  assert.throws(() => recoverSourceColorResource(f.input, f.dependencies), /stopped-process evidence/);
  assert.equal(f.leases.length, 1); assert.equal(fs.existsSync(f.lock), false);
  assert.deepEqual(fs.readFileSync(f.staged.reservation.path), bytes);
});

test("acquisition callback cannot rebaseline original caller metadata or replace reservation", async t => {
  for (const kind of ["metadata", "file"] as const) await t.test(kind, t => {
    const f = sourceColorRecoveryFixture(t); f.releaseOriginal();
    const acquire = f.dependencies.acquire;
    f.dependencies.acquire = (directory, operation) => {
      const result = acquire(directory, operation);
      if (kind === "metadata") f.input.held.submission.expectedToken = "TEST changed at acquisition";
      if (kind === "file") replaceRecoveryReservation(f);
      return result;
    };
    assert.throws(() => recoverSourceColorResource(f.input, f.dependencies), /original/);
    assert.equal(f.leases.length, 1); assert.equal(fs.existsSync(f.lock), false); assert(fs.existsSync(f.staged.reservation.path));
  });
});

test("later assertion failures retain the handed-out resource and never retire the marker", t => {
  const f = sourceColorRecoveryFixture(t); f.releaseOriginal(); const held = recoverSourceColorResource(f.input, f.dependencies);
  f.actual.receiptSha256 = "0".repeat(64); assert.throws(held.assertCurrent, /stopped-process evidence/);
  assert(fs.existsSync(f.lock)); assert(fs.existsSync(f.staged.reservation.path)); held.assertResource();
});

test("final stopped-reader callback substitution is caught by the original raw-file hold", t => {
  const f = sourceColorRecoveryFixture(t); f.releaseOriginal(); const held = recoverSourceColorResource(f.input, f.dependencies);
  f.callbacks.read = () => replaceRecoveryReservation(f);
  assert.throws(held.assertCurrent, /original file/); assert(fs.existsSync(f.lock));
});

test("invalid or expired original allowance never acquires a resource", t => {
  const f = sourceColorRecoveryFixture(t); f.releaseOriginal();
  for (const value of [0, -1, NaN, Infinity, 300_001]) {
    f.input.remainingMs = () => value;
    assert.throws(() => recoverSourceColorResource(f.input, f.dependencies), /deadline/);
  }
  assert.equal(f.events.acquires, 0); assert(fs.existsSync(f.staged.reservation.path));
});

test("recovery never creates a missing global namespace", t => {
  const f = sourceColorRecoveryFixture(t), empty = path.join(f.staging.root, "TEST-empty-workspace");
  fs.mkdirSync(empty, { mode: 0o700 });
  assert.throws(() => recoverSourceColorResource(f.input, { ...f.dependencies, workspace: () => empty }), /ENOENT/);
  assert.deepEqual(fs.readdirSync(empty), []); assert.equal(f.events.acquires, 0); f.staging.resource.assertResource();
});

test("resource namespace substitution and unsafe permissions reject before acquisition", t => {
  const f = sourceColorRecoveryFixture(t); f.releaseOriginal();
  assert.throws(() => recoverSourceColorResource(f.input, { ...f.dependencies, directory: () => f.staging.root }), /namespace/);
  assert.equal(fs.realpathSync(f.staging.resource.resource), f.staging.resource.resource);
  fs.chmodSync(f.staging.resource.resource, 0o755);
  assert.throws(() => recoverSourceColorResource(f.input, f.dependencies), /Unsafe private/);
  fs.chmodSync(f.staging.resource.resource, 0o700); assert.equal(f.events.acquires, 0);
});

test("acquisition exception is not retried and never releases somebody else's lease", t => {
  const f = sourceColorRecoveryFixture(t), failure = new Error("TEST acquisition failed"); let calls = 0;
  assert.throws(() => recoverSourceColorResource(f.input, { ...f.dependencies,
    acquire: () => { calls++; throw failure; },
  }), error => error === failure);
  assert.equal(calls, 1); assert.equal(f.leases.length, 0); f.staging.resource.assertResource();
});

test("returned check rejects loss of the original acquired lease without releasing its replacement", t => {
  const f = sourceColorRecoveryFixture(t); f.releaseOriginal(); const held = recoverSourceColorResource(f.input, f.dependencies);
  held.lease.release(); const replacement = f.dependencies.acquire(held.resource, "TEST replacement resource owner");
  assert(replacement.lease); const check = f.dependencies.leaseGuard(held.resource, replacement.lease);
  assert.throws(held.assertCurrent, /replaced/); check(); assert(fs.existsSync(f.staged.reservation.path));
});

test("last original remaining callback cannot release the acquired lease after its final check", async t => {
  for (const mode of ["current", "metadata", "copy"] as const) await t.test(mode, t => {
    const f = sourceColorRecoveryFixture(t); let armed = false, calls = 0;
    const finalCall = mode === "metadata" ? 1 : 2;
    f.input.remainingMs = () => {
      if (armed && ++calls === finalCall) f.leases[0].release();
      return 300_000;
    };
    f.releaseOriginal(); const held = recoverSourceColorResource(f.input, f.dependencies); armed = true;
    const operation = mode === "current" ? held.assertCurrent : mode === "metadata" ? held.cleanupHold.assertCurrent
      : () => copySourceColorCleanupReservation(held.cleanupHold);
    assert.throws(operation, /ENOENT|replaced/);
    assert.equal(calls, finalCall); assert.equal(fs.existsSync(f.lock), false);
    assert(fs.existsSync(f.staged.reservation.path));
  });
});

test("failed guard construction and uncertain release preserve both original errors", t => {
  const f = sourceColorRecoveryFixture(t), primary = new Error("TEST guard failure"), release = new Error("TEST uncertain release");
  f.releaseOriginal(); const acquire = f.dependencies.acquire;
  assert.throws(() => recoverSourceColorResource(f.input, { ...f.dependencies,
    acquire: (directory, operation) => {
      const result = acquire(directory, operation); assert(result.lease);
      return { lease: { release: () => { throw release; } } };
    }, leaseGuard: () => { throw primary; },
  }), error => { assert(error instanceof AggregateError); assert.deepEqual(error.errors, [primary, release]); return true; });
  assert(fs.existsSync(f.lock)); assert(fs.existsSync(f.staged.reservation.path));
});

test("failed acquisition cannot treat a void no-op release as verified ownership release", t => {
  const f = sourceColorRecoveryFixture(t), primary = new Error("TEST guard failure");
  f.releaseOriginal(); const acquire = f.dependencies.acquire; let original: fs.Stats | undefined;
  assert.throws(() => recoverSourceColorResource(f.input, { ...f.dependencies,
    acquire: (directory, operation) => {
      const result = acquire(directory, operation); assert(result.lease); original = fs.lstatSync(f.lock);
      return { lease: { release: () => {} } };
    }, leaseGuard: () => { throw primary; },
  }), error => {
    assert(error instanceof AggregateError); assert.equal(error.errors[0], primary);
    assert.match(String(error.errors[1]), /release is unverified/); return true;
  });
  const after = fs.lstatSync(f.lock); assert.equal(after.dev, original!.dev); assert.equal(after.ino, original!.ino);
  assert(fs.existsSync(f.staged.reservation.path));
});

test("failed acquisition uses the release method captured before guard callbacks", t => {
  const f = sourceColorRecoveryFixture(t), primary = new Error("TEST guard failure");
  f.releaseOriginal(); const acquire = f.dependencies.acquire; let replacements = 0;
  assert.throws(() => recoverSourceColorResource(f.input, { ...f.dependencies,
    acquire: (directory, operation) => acquire(directory, operation),
    leaseGuard: (_directory, lease) => {
      lease.release = () => { replacements++; }; throw primary;
    },
  }), error => error === primary);
  assert.equal(replacements, 0); assert.equal(fs.existsSync(f.lock), false);
  assert(fs.existsSync(f.staged.reservation.path));
});

test("failed acquisition reports unknown post-release lock observation as retained uncertainty", t => {
  const f = sourceColorRecoveryFixture(t), primary = new Error("TEST guard failure");
  const unreadable = Object.assign(new Error("TEST exact acquired lock cannot be observed"), { code: "EACCES" });
  f.releaseOriginal(); const acquire = f.dependencies.acquire, lstat = fs.lstatSync; let released = false;
  const mocked = t.mock.method(fs, "lstatSync", (...args: Parameters<typeof fs.lstatSync>) => {
    if (released && args[0] === f.lock) throw unreadable;
    return lstat(...args);
  });
  try {
    assert.throws(() => recoverSourceColorResource(f.input, { ...f.dependencies,
      acquire: (directory, operation) => {
        const result = acquire(directory, operation); assert(result.lease);
        return { lease: { release: () => { released = true; } } };
      }, leaseGuard: () => { throw primary; },
    }), error => { assert(error instanceof AggregateError); assert.deepEqual(error.errors, [primary, unreadable]); return true; });
  } finally { mocked.mock.restore(); }
  assert(fs.existsSync(f.lock)); assert(fs.existsSync(f.staged.reservation.path));
});

test("failed original acquired-lock capture never invents a verified release", t => {
  const f = sourceColorRecoveryFixture(t), unreadable = Object.assign(new Error("TEST initial lock observation failed"), { code: "EACCES" });
  f.releaseOriginal(); const acquire = f.dependencies.acquire, lstat = fs.lstatSync; let acquired = false, guards = 0;
  const mocked = t.mock.method(fs, "lstatSync", (...args: Parameters<typeof fs.lstatSync>) => {
    if (acquired && args[0] === f.lock) throw unreadable;
    return lstat(...args);
  });
  try {
    assert.throws(() => recoverSourceColorResource(f.input, { ...f.dependencies,
      acquire: (directory, operation) => { const result = acquire(directory, operation); acquired = true; return result; },
      leaseGuard: () => { guards++; throw new Error("TEST must not reach post-acquisition guard"); },
    }), error => { assert(error instanceof AggregateError); assert.deepEqual(error.errors, [unreadable]); return true; });
  } finally { mocked.mock.restore(); }
  assert.equal(guards, 0); assert(fs.existsSync(f.lock)); assert(fs.existsSync(f.staged.reservation.path));
});
