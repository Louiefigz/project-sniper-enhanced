/** Actual current pending reads and TEMP leases; inherited native/claim/tool provenance stays TEST-only. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import type { ProjectMutationLease } from "../project-mutation-lease";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { readSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { recoverSourceColorRetirementResource, sourceColorRetirementResourceRecoveryDependencies,
  type SourceColorRetirementResourceRecoveryInput } from "../guided-source-color-resource-recovery";
import { cleanupPendingReadLeaves } from "./_guided-source-color-cleanup-pending-read-fixture";
import { sourceColorRetirementFixture } from "./_guided-source-color-reservation-retirement-fixture";

/** A recovery reader owns project exclusion and the SAME original clock, not the released old resource lease. */
export async function retirementResourceFixture(t: TestContext) {
  const leases: ProjectMutationLease[] = [], releases: (() => void)[] = [];
  t.after(() => { for (const release of releases) release(); });
  const f = await sourceColorRetirementFixture(t), callbacks = { guard: () => {}, remaining: () => {} };
  const clock = f.writerInput.clock, remaining = clock.remainingMs;
  const readInput = { dir: f.before.job.ctx.dir, guard: () => { callbacks.guard(); f.assertProject(); },
    remainingMs: () => { callbacks.remaining(); return remaining.call(clock); } };
  const pending = readSourceColorCleanupPending(readInput, cleanupPendingReadLeaves(f));
  const input: SourceColorRetirementResourceRecoveryInput = { pending, projectLease: f.projectLease };
  const events = { acquires: 0 }, actual = sourceColorRetirementResourceRecoveryDependencies;
  const controls = { ...actual, workspace: () => f.staging.root, acquire: (directory: string, operation: string) => {
    events.acquires++; const result = actual.acquire(directory, operation);
    if (result.lease) { leases.push(result.lease); releases.push(result.lease.release.bind(result.lease)); }
    return result;
  } };
  return { ...f, recoveryCallbacks: callbacks, readInput, recoveryInput: input, controls, recoveryEvents: events, leases,
    lock: path.join(f.staging.resource.resource, ".sniper-project-mutation.lock"),
    recover: () => recoverSourceColorRetirementResource(input, controls),
    releaseOriginal: () => f.staging.resource.lease.release() };
}
export type RetirementResourceFixture = Awaited<ReturnType<typeof retirementResourceFixture>>;

/** Constructor failure never modifies the actual active marker or records another cleanup. */
export function assertRetirementResourceRetained(f: RetirementResourceFixture): void {
  assert.deepEqual(fs.readFileSync(f.files.active), f.activeBytes);
  const current = fs.lstatSync(f.files.active, { bigint: true });
  assert.equal(current.dev, f.activeIdentity.dev); assert.equal(current.ino, f.activeIdentity.ino);
  assert.equal(f.calls.length, 1); assert(!fs.existsSync(f.files.ack));
  assert(!fs.existsSync(path.join(f.directory, "failure.json")));
}

/** Move only this exact private fixture resource namespace, preserving all contents for inherited root cleanup. */
export function moveRetirementResource(f: RetirementResourceFixture) {
  const source = f.staging.resource.resource, root = fs.realpathSync(f.staging.root), target = path.join(root, "TEST-moved-color-resource");
  assert.equal(source, path.join(root, ".sniper-color-resource")); assert.equal(fs.realpathSync(source), source);
  const stat = fs.lstatSync(source); assert(stat.isDirectory()); assert.equal(stat.uid, process.getuid!());
  assert.equal(stat.mode & 0o777, 0o700); assert.throws(() => fs.lstatSync(target), { code: "ENOENT" });
  fs.renameSync(source, target);
  return { target, restore: () => {
    assert.equal(fs.realpathSync(target), target); const current = fs.lstatSync(target);
    assert.equal(current.dev, stat.dev); assert.equal(current.ino, stat.ino);
    assert.throws(() => fs.lstatSync(source), { code: "ENOENT" }); fs.renameSync(target, source);
  } };
}

/** Replace only the known original TEMP journal; no caller-provided target or dependency mutation. */
export function replaceRetirementPendingJournal(f: RetirementResourceFixture): void {
  const file = autoEditJobPath(f.before.job.ctx.dir), root = fs.realpathSync(f.staging.root);
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), `TEST-retirement-journal-replacement-${randomUUID()}.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}
