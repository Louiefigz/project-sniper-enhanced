/** Real pending journal, both TEMP leases and checkpoint policy. Native/claim/tool provenance stays TEST-only. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { acquireGuidedMutation } from "../guided-cut-v2-store";
import { acquireProjectMutationLease, type ProjectMutationLease } from "../project-mutation-lease";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { readRetainedSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { sourceColorCleanupRecoveryDependencies } from "../guided-source-color-cleanup-recovery";
import { cleanupPendingReadLeaves } from "./_guided-source-color-cleanup-pending-read-fixture";
import { sourceColorRetirementFixture, removeRetirementMarker } from "./_guided-source-color-reservation-retirement-fixture";

/** Recovery begins after old owners release, with one enclosing clock created before its service/acquisition. */
export async function cleanupRecoveryFixture(t: TestContext, state: "present" | "absent" | "acked" = "present") {
  const projects: ProjectMutationLease[] = [], resources: ProjectMutationLease[] = [];
  t.after(() => { for (const lease of [...resources, ...projects]) lease.release(); });
  const base = await sourceColorRetirementFixture(t);
  const workspace = process.env.SNIPER_WORKSPACE_ROOT;
  process.env.SNIPER_WORKSPACE_ROOT = base.staging.root;
  t.after(() => { if (workspace === undefined) delete process.env.SNIPER_WORKSPACE_ROOT; else process.env.SNIPER_WORKSPACE_ROOT = workspace; });
  if (state === "absent") removeRetirementMarker(base);
  if (state === "acked") base.retire();
  base.projectLease.release(); base.staging.resource.lease.release();
  const current = observeHumanCutJob(base.before.job.ctx.dir), origin = performance.now(), timing = { advance: 0 };
  const callbacks = { projectBefore: async () => {}, projectAfter: () => {}, resourceBefore: () => {}, resourceAfter: () => {},
    remaining: () => {}, elapsed: () => {}, stopped: () => {} };
  const events = { project: 0, resource: 0, stopped: 0 }, elapsed = () => performance.now() - origin + timing.advance;
  const clock = { receivedAt: new Date().toISOString(), remainingMs: () => { callbacks.remaining(); return 300_000 - elapsed(); },
    elapsedMs: () => { callbacks.elapsed(); return elapsed(); } };
  const input = { dir: current.job.ctx.dir, expectedToken: current.job.token, expectedJournalHash: current.sha256,
    expectedClaimHash: base.input.held.claimHash, clock };
  const acquireProject: typeof acquireGuidedMutation = async (directory, checkpoint) => {
    events.project++; await callbacks.projectBefore(); const lease = await acquireGuidedMutation(directory, checkpoint);
    projects.push(lease); callbacks.projectAfter(); return lease;
  };
  const acquireResource: typeof acquireProjectMutationLease = (directory, operation) => {
    events.resource++; callbacks.resourceBefore(); const result = acquireProjectMutationLease(directory, operation);
    if (result.lease) resources.push(result.lease);
    callbacks.resourceAfter(); return result;
  };
  const stopped = base.readerDependencies.stopped;
  base.readerDependencies.stopped = () => { events.stopped++; const value = stopped(); callbacks.stopped(); return value; };
  const readers = cleanupPendingReadLeaves(base), snapshots = path.join(input.dir, "human-cut-job-snapshots");
  const files = { journal: autoEditJobPath(input.dir), active: base.files.active, ack: base.files.ack,
    prepared: path.join(base.before.job.ctx.dir, ".sniper-authority-v1/objects/receipts", `${base.recorded.factHash}.json`),
    original: path.join(snapshots, `${base.before.sha256}.json`), pending: path.join(snapshots, `${current.sha256}.json`),
    archive: base.files.archive, media: base.files.media, output: path.join(base.directory, "output.json"),
    result: path.join(base.before.job.ctx.dir, ".sniper-authority-v1/objects/receipts", `${base.recorded.fact.cleanupResultHash}.json`) };
  return { base, current, input, timing, callbacks, events, readers, acquireProject, acquireResource, projects, resources, files,
    projectLock: path.join(base.staging.root, ".sniper-project-mutation.lock"),
    resourceLock: path.join(base.staging.resource.resource, ".sniper-project-mutation.lock") };
}
export type CleanupRecoveryFixture = Awaited<ReturnType<typeof cleanupRecoveryFixture>>;

/** Keep actual project/global acquisition and every whole reader/retire/CAS call; only original native/claim leaves are TEST data. */
export function cleanupRecoveryDependencies(f: CleanupRecoveryFixture): typeof sourceColorCleanupRecoveryDependencies {
  const history: typeof readRetainedSourceColorCleanupPending = (input, hash) => readRetainedSourceColorCleanupPending(input, hash, f.readers);
  return { ...sourceColorCleanupRecoveryDependencies, acquireProject: f.acquireProject, pending: f.readers,
    resource: { ...sourceColorCleanupRecoveryDependencies.resource, workspace: () => f.base.staging.root, acquire: f.acquireResource },
    final: { history }, read: { history } };
}

/** Scope faults to exact private single-link fixture files. No decoder, tool or caller-selected target is writable. */
export function recoveryFaultFile(f: CleanupRecoveryFixture, name: keyof CleanupRecoveryFixture["files"]): string {
  const file = f.files[name], root = fs.realpathSync(f.base.staging.root);
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  return file;
}

/** Same-byte inode substitutions stay in the unique TEST namespace and are never cleaned up as successes. */
export function replaceRecoveryFile(f: CleanupRecoveryFixture, name: keyof CleanupRecoveryFixture["files"], bytes?: Buffer): void {
  const file = recoveryFaultFile(f, name), temporary = path.join(path.dirname(file), `TEST-recovery-replacement-${randomUUID()}.json`);
  fs.writeFileSync(temporary, bytes ?? fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

/** Check failure retention separately from expected owner release; this is not cleanup/selection approval. */
export function assertRecoveryRetained(f: CleanupRecoveryFixture, locks: { project: boolean; resource: boolean }, final = false): void {
  assert.equal(fs.existsSync(f.projectLock), locks.project); assert.equal(fs.existsSync(f.resourceLock), locks.resource);
  const current = observeHumanCutJob(f.input.dir);
  if (!final) assert.equal(current.sha256, f.current.sha256);
  assert.equal(Object.hasOwn(current.job.guidedHandoffV2!, "openingExecutionClaimHash"), !final);
  assert(fs.existsSync(f.files.archive)); assert.equal(f.base.calls.length, 1);
  assert(!fs.existsSync(path.join(f.base.directory, "failure.json")));
}
