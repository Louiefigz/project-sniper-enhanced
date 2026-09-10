/** Actual adopted completion through both CAS edges. Native and original claim admission remain inherited TEST leaves. */
import path from "node:path";
import type { TestContext } from "node:test";
import { acquireGuidedMutation } from "../guided-cut-v2-store";
import { acquireProjectMutationLease, type ProjectMutationLease } from "../project-mutation-lease";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { commitPreparedSourceColorCleanup, type PreparedSourceColorCleanupFaults } from "../guided-source-color-cleanup-pending-commit";
import { readSourceColorCleanupPending, readRetainedSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { retirePreparedSourceColorReservation } from "../guided-source-color-reservation-retirement";
import { commitRetiredSourceColorCleanup } from "../guided-source-color-cleanup-final-commit";
import { readFinalSourceColorCleanupForJournal } from "../guided-source-color-cleanup-final-read";
import { reconcilePendingSourceColorCleanup, sourceColorCleanupRecoveryDependencies } from "../guided-source-color-cleanup-recovery";
import { cleanupAdoptionFixture } from "./_guided-source-color-cleanup-adoption-fixture";
import { cleanupPendingReadLeaves } from "./_guided-source-color-cleanup-pending-read-fixture";

/** Register acquired recovery owners before the unique TEST root's teardown; never replace an actual whole proof function. */
export async function cleanupAdoptionIntegrationFixture(t: TestContext) {
  const projects: ProjectMutationLease[] = [], resources: ProjectMutationLease[] = [];
  t.after(() => { for (const lease of [...resources, ...projects]) lease.release(); });
  const f = await cleanupAdoptionFixture(t), clock = f.adoptionInput.clock, readers = cleanupPendingReadLeaves(f);
  const workspace = process.env.SNIPER_WORKSPACE_ROOT; process.env.SNIPER_WORKSPACE_ROOT = f.staging.root;
  t.after(() => { if (workspace === undefined) delete process.env.SNIPER_WORKSPACE_ROOT; else process.env.SNIPER_WORKSPACE_ROOT = workspace; });
  const callbacks = { pending: () => {}, finalRead: () => {}, recoveredProject: () => {}, recoveredResource: () => {} };
  const history: typeof readRetainedSourceColorCleanupPending = (input, hash) => readRetainedSourceColorCleanupPending(input, hash, readers);
  const pending = () => readSourceColorCleanupPending({ dir: f.before.job.ctx.dir,
    guard: () => { callbacks.pending(); f.assertLeases(); }, remainingMs: clock.remainingMs }, readers);
  const commit = (faults?: PreparedSourceColorCleanupFaults) => commitPreparedSourceColorCleanup(f.adopt(), faults);
  const retire = (value: ReturnType<typeof pending>) => retirePreparedSourceColorReservation({ pending: value,
    projectLease: f.projectLease, resource: f.staging.resource }, { workspace: () => f.staging.root });
  const finalize = (retired: ReturnType<typeof retire>) => commitRetiredSourceColorCleanup(retired, { history });
  const read = () => {
    const proofStarted = performance.now(), dir = f.before.job.ctx.dir;
    return readFinalSourceColorCleanupForJournal({ dir, journal: { path: autoEditJobPath(dir), observed: observeHumanCutJob(dir) },
      guard: () => { callbacks.finalRead(); f.assertLeases(); },
      remainingMs: () => Math.min(clock.remainingMs(), 30_000 - (performance.now() - proofStarted)) }, { history });
  };
  const acquireProject: typeof acquireGuidedMutation = async (directory, checkpoint) => {
    const lease = await acquireGuidedMutation(directory, checkpoint); projects.push(lease); callbacks.recoveredProject(); return lease;
  };
  const acquireResource: typeof acquireProjectMutationLease = (directory, operation) => {
    const result = acquireProjectMutationLease(directory, operation);
    if (result.lease) resources.push(result.lease); callbacks.recoveredResource(); return result;
  };
  const recovery = { ...sourceColorCleanupRecoveryDependencies, acquireProject, pending: readers,
    resource: { ...sourceColorCleanupRecoveryDependencies.resource, workspace: () => f.staging.root, acquire: acquireResource },
    final: { history }, read: { history } };
  const recover = () => {
    const current = observeHumanCutJob(f.before.job.ctx.dir);
    return reconcilePendingSourceColorCleanup({ dir: current.job.ctx.dir, expectedToken: current.job.token,
      expectedJournalHash: current.sha256, expectedClaimHash: f.input.held.claimHash, clock }, recovery);
  };
  const files = { projectLock: path.join(f.staging.root, ".sniper-project-mutation.lock"),
    resourceLock: path.join(f.staging.resource.resource, ".sniper-project-mutation.lock"),
    active: f.staged.reservation.path, ack: path.join(f.directory, "retirement-ack.json"),
    archive: f.recorded.fact.archive.path, failure: path.join(f.directory, "failure.json") };
  return { ...f, clock, integrationCallbacks: callbacks, projects, resources, files, commit, pending, retire, finalize, read, recover };
}
