/** Faults target exact TEMP records or actual TEMP lease handles. No native/daemon or dependency writes. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { reconcilePendingSourceColorCleanup } from "../guided-source-color-cleanup-recovery";
import { cleanupRecoveryFixture, cleanupRecoveryDependencies, replaceRecoveryFile,
  assertRecoveryRetained } from "./_guided-source-color-cleanup-recovery-fixture";

test("time spent awaiting the real project acquisition consumes the same original allowance", async t => {
  const f = await cleanupRecoveryFixture(t);
  f.callbacks.projectBefore = async () => { await Promise.resolve(); f.timing.advance = 300_000; };
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /allowance/);
  assert.equal(f.projects.length, 1); assert.equal(f.resources.length, 0);
  assertRecoveryRetained(f, { project: false, resource: false }); assert(fs.existsSync(f.files.active));
});

test("original request mutation during project acquisition rejects and releases only the new project lease", async t => {
  const f = await cleanupRecoveryFixture(t); f.callbacks.projectAfter = () => { f.input.expectedToken += "-changed"; };
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /original request/);
  assertRecoveryRetained(f, { project: false, resource: false }); assert.equal(f.events.resource, 0);
});

for (const name of ["journal", "original", "media", "output", "archive", "result"] as const) test(`pending-read ${name} replacement rejects before global acquisition`, async t => {
  const f = await cleanupRecoveryFixture(t);
  f.callbacks.stopped = () => { f.callbacks.stopped = () => {}; replaceRecoveryFile(f, name); };
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /changed|original|differs/);
  assertRecoveryRetained(f, { project: false, resource: false }); assert.equal(f.events.resource, 0);
});

test("expiry inside actual global acquisition releases its partial lease and the new project lease", async t => {
  const f = await cleanupRecoveryFixture(t); f.callbacks.resourceAfter = () => { f.timing.advance = 300_000; };
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /allowance/);
  assert.equal(f.resources.length, 1); assertRecoveryRetained(f, { project: false, resource: false });
});

test("an acquired resource whose release is uncertain conservatively retains the project lease", async t => {
  const f = await cleanupRecoveryFixture(t), failure = new Error("TEST resource release failed");
  let original: (() => void) | undefined;
  f.callbacks.resourceAfter = () => {
    const lease = f.resources[0]; original = lease.release; lease.release = () => { throw failure; }; f.timing.advance = 300_000;
  };
  try {
    await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), error => error instanceof AggregateError);
    assertRecoveryRetained(f, { project: true, resource: true });
  } finally { if (original) f.resources[0].release = original; }
});

test("unrelated active bytes discovered after resource handoff retain both leases without unlink", async t => {
  const f = await cleanupRecoveryFixture(t); f.callbacks.resourceAfter = () => replaceRecoveryFile(f, "active", Buffer.from("{}\n"));
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /marker|reservation|original|changed|differs/);
  assertRecoveryRetained(f, { project: true, resource: true }); assert(fs.existsSync(f.files.active)); assert(!fs.existsSync(f.files.ack));
});

for (const name of ["media", "output", "archive"] as const) test(`post-retirement ${name} drift retains both leases and the actual ack`, async t => {
  const f = await cleanupRecoveryFixture(t); let fired = false;
  f.callbacks.remaining = () => {
    if (fired || !fs.existsSync(f.files.ack)) return;
    fired = true; replaceRecoveryFile(f, name);
  };
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /original|changed/);
  assert(fired); assertRecoveryRetained(f, { project: true, resource: true });
  assert(!fs.existsSync(f.files.active)); assert(fs.existsSync(f.files.ack));
});

test("post-retirement original clock expiry keeps the ack and both leases without a new attempt", async t => {
  const f = await cleanupRecoveryFixture(t);
  f.callbacks.remaining = () => { if (fs.existsSync(f.files.ack)) f.timing.advance = 300_000; };
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /allowance/);
  assertRecoveryRetained(f, { project: true, resource: true }); assert(fs.existsSync(f.files.ack));
});

test("post-final-CAS media drift retains the actual final journal and both leases", async t => {
  const f = await cleanupRecoveryFixture(t); let fired = false;
  f.callbacks.remaining = () => {
    if (fired || observeHumanCutJob(f.input.dir).job.guidedHandoffV2!.openingExecutionClaimHash) return;
    fired = true; replaceRecoveryFile(f, "media");
  };
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /original|changed/);
  assert(fired); assertRecoveryRetained(f, { project: true, resource: true }, true);
});

for (const kind of ["resource", "project"] as const) test(`a no-op ${kind} release cannot report verified recovery`, async t => {
  const f = await cleanupRecoveryFixture(t); let original: (() => void) | undefined;
  const after = () => { const lease = kind === "project" ? f.projects[0] : f.resources[0]; original = lease.release; lease.release = () => {}; };
  if (kind === "project") f.callbacks.projectAfter = after; else f.callbacks.resourceAfter = after;
  try {
    await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /release is unverified/);
    assertRecoveryRetained(f, { project: true, resource: kind === "resource" }, true);
  } finally { if (original) (kind === "project" ? f.projects[0] : f.resources[0]).release = original; }
});

for (const kind of ["resource", "project"] as const) test(`actual ${kind} release is followed by exact metadata validation`, async t => {
  const f = await cleanupRecoveryFixture(t);
  const after = () => {
    const lease = kind === "project" ? f.projects[0] : f.resources[0], original = lease.release;
    let fired = false;
    lease.release = () => { original.call(lease); if (!fired) { fired = true; replaceRecoveryFile(f, "media"); } };
  };
  if (kind === "project") f.callbacks.projectAfter = after; else f.callbacks.resourceAfter = after;
  await assert.rejects(reconcilePendingSourceColorCleanup(f.input, cleanupRecoveryDependencies(f)), /original|changed/);
  assertRecoveryRetained(f, { project: kind === "resource", resource: false }, true);
});
