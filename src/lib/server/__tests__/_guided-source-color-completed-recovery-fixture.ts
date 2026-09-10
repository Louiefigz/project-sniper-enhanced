/** Actual uncommitted completion and fresh TEMP ownership. Native/claim leaves remain explicitly TEST-only. */
import assert from "node:assert/strict";
import path from "node:path";
import type { TestContext } from "node:test";
import { acquireGuidedMutation } from "../guided-cut-v2-store";
import { acquireProjectMutationLease, type ProjectMutationLease } from "../project-mutation-lease";
import { readRetainedSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { reconcileCompletedSourceColorCleanup, reconcilePendingSourceColorCleanup,
  sourceColorCleanupRecoveryDependencies } from "../guided-source-color-cleanup-recovery";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { cleanupAdoptionFixture } from "./_guided-source-color-cleanup-adoption-fixture";
import { cleanupPendingReadLeaves } from "./_guided-source-color-cleanup-pending-read-fixture";

/** All real leases acquired by this TEST request are registered before exact-root teardown. */
export async function completedRecoveryFixture(t: TestContext) {
  const projects: ProjectMutationLease[] = [], resources: ProjectMutationLease[] = [];
  t.after(() => { for (const lease of [...resources, ...projects]) lease.release(); });
  const f = await cleanupAdoptionFixture(t), readers = cleanupPendingReadLeaves(f), clock = f.adoptionInput.clock;
  const workspace = process.env.SNIPER_WORKSPACE_ROOT; process.env.SNIPER_WORKSPACE_ROOT = f.staging.root;
  t.after(() => { if (workspace === undefined) delete process.env.SNIPER_WORKSPACE_ROOT; else process.env.SNIPER_WORKSPACE_ROOT = workspace; });
  f.projectLease.release(); f.staging.resource.lease.release(); f.timing.elapsed = 300_000;
  const callbacks = { projectBefore: async () => {}, projectAfter: () => {}, resourceBefore: () => {},
    resourceAfter: () => {}, pending: () => {} };
  const input = { dir: f.before.job.ctx.dir, expectedToken: f.before.job.token, expectedJournalHash: f.before.sha256,
    expectedClaimHash: f.input.held.claimHash, cleanupAttemptId: f.recorded.fact.cleanupAttemptId,
    preparedSha256: f.recorded.preparedRef.sha256, clock };
  const acquireProject: typeof acquireGuidedMutation = async (dir, checkpoint) => {
    await callbacks.projectBefore(); const lease = await acquireGuidedMutation(dir, checkpoint);
    projects.push(lease); callbacks.projectAfter(); return lease;
  };
  const acquireResource: typeof acquireProjectMutationLease = (dir, operation) => {
    callbacks.resourceBefore(); const result = acquireProjectMutationLease(dir, operation);
    if (result.lease) resources.push(result.lease);
    callbacks.resourceAfter(); return result;
  };
  const claim = readers.claim;
  const pending = { ...readers, claim: (dir: string, hash: string) => { callbacks.pending(); return claim(dir, hash); } };
  const history: typeof readRetainedSourceColorCleanupPending = (value, hash) => readRetainedSourceColorCleanupPending(value, hash, readers);
  const media: typeof f.readerDependencies.media = (held, capture) => {
    assert.deepEqual(held, f.input.held); for (const ref of f.media.files) capture(ref);
  };
  const controls = { ...sourceColorCleanupRecoveryDependencies, acquireProject, pending,
    resource: { ...sourceColorCleanupRecoveryDependencies.resource, workspace: () => f.staging.root, acquire: acquireResource },
    completed: { ...f.adoptionDependencies, history: { ...f.readerDependencies, media },
      resource: { ...sourceColorCleanupRecoveryDependencies.completed.resource,
      workspace: () => f.staging.root, acquire: acquireResource, stopped: f.readerDependencies.stopped } },
    final: { history }, read: { history } };
  const files = { project: path.join(f.staging.root, ".sniper-project-mutation.lock"),
    resource: path.join(f.staging.resource.resource, ".sniper-project-mutation.lock"),
    active: f.staged.reservation.path, ack: path.join(f.directory, "retirement-ack.json"), failure: path.join(f.directory, "failure.json") };
  const resumePending = () => {
    const current = observeHumanCutJob(input.dir);
    return reconcilePendingSourceColorCleanup({ dir: input.dir, expectedToken: current.job.token,
      expectedJournalHash: current.sha256, expectedClaimHash: input.expectedClaimHash, clock }, controls);
  };
  return { ...f, recoveryInput: input, recoveryControls: controls, recoveryCallbacks: callbacks, projects, resources, files,
    run: () => reconcileCompletedSourceColorCleanup(input, controls), resumePending };
}
