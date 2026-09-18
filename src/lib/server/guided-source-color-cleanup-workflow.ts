/** One live V2 cleanup workflow on the caller's existing leases and protected clock. */
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { workspaceRoot } from "@/app/api/_lib/workspace";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { uuid } from "@/lib/producer/contracts/validation";
import { humanCutDirectory, observeHumanCutJob } from "./human-cut-acceptance-store";
import { holdSourceColorCleanupReservation } from "./guided-source-color-cleanup-hold";
import { readStoppedOpeningProcess, ownershipUnresolved, type HeldOpeningClaim } from "./guided-opening-process";
import { recordSourceColorCleanupAttempt, sourceColorCleanupAttemptDependencies, type SourceColorCleanupClock } from "./guided-source-color-cleanup-attempt";
import { commitPreparedSourceColorCleanup } from "./guided-source-color-cleanup-pending-commit";
import { readSourceColorCleanupPending, sourceColorCleanupPendingReadDependencies } from "./guided-source-color-cleanup-pending-read";
import { retirePreparedSourceColorReservation } from "./guided-source-color-reservation-retirement";
import { commitRetiredSourceColorCleanup, sourceColorFinalCommitDependencies,
  assertCommittedSourceColorCleanupMetadata } from "./guided-source-color-cleanup-final-commit";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { timedStage } from "./stage-timing";
import type { HeldGradeObservationResource } from "./grade-observation-resource";
import type { ProjectMutationLease } from "./project-mutation-lease";

export interface SourceColorCleanupWorkflowInput {
  held: HeldOpeningClaim; projectLease: ProjectMutationLease; resource: HeldGradeObservationResource; clock: SourceColorCleanupClock;
}
/** TEST leaves only; actual recording, both CAS operations and retirement cannot be replaced. */
export const sourceColorCleanupWorkflowDependencies = { workspace: workspaceRoot, attemptId: (): string => randomUUID(),
  stopped: readStoppedOpeningProcess, record: sourceColorCleanupAttemptDependencies,
  pending: sourceColorCleanupPendingReadDependencies, final: sourceColorFinalCommitDependencies };
type Dependencies = typeof sourceColorCleanupWorkflowDependencies;

function workflowOwner(input: SourceColorCleanupWorkflowInput, workspace: () => string) {
  const original = { ...input, releaseProject: input.projectLease.release, resourcePath: input.resource.resource,
    resourceLease: input.resource.lease, releaseResource: input.resource.lease.release, resourceCheck: input.resource.assertResource,
    remaining: input.clock.remainingMs, elapsed: input.clock.elapsedMs, receivedAt: input.clock.receivedAt };
  const held = snapshotSourceColorMetadata(input.held);
  const unchanged = () => {
    if (input.held !== original.held || input.projectLease !== original.projectLease || input.resource !== original.resource
        || input.projectLease.release !== original.releaseProject || input.resource.resource !== original.resourcePath
        || input.resource.lease !== original.resourceLease || input.resource.lease.release !== original.releaseResource
        || input.resource.assertResource !== original.resourceCheck || input.clock !== original.clock
        || input.clock.remainingMs !== original.remaining || input.clock.elapsedMs !== original.elapsed
        || input.clock.receivedAt !== original.receivedAt || !isDeepStrictEqual(input.held, held)) {
      throw new Error("Source color cleanup workflow original caller metadata changed");
    }
  };
  const resource = path.join(fs.realpathSync(workspace()), ".sniper-color-resource"); unchanged();
  if (input.resource.resource !== resource || input.held.submission.schemaVersion !== 2) throw new Error("Source color cleanup workflow requires its original V2 global resource");
  const projectGuard = cutPreviewLeaseGuard(held.job.ctx.dir, input.projectLease), resourceGuard = cutPreviewLeaseGuard(resource, input.resource.lease);
  const guard = () => { unchanged(); projectGuard(); resourceGuard(); unchanged(); };
  const remainingMs = () => {
    unchanged(); const started = performance.now(), remaining = original.remaining.call(original.clock); guard();
    const elapsed = performance.now() - started, bounded = Math.floor(remaining - elapsed);
    if (!Number.isFinite(remaining) || remaining > 300_000 || !Number.isFinite(elapsed) || elapsed < 0 || bounded <= 0) throw new Error("Source color cleanup workflow exhausted its original protected remainder");
    return bounded;
  };
  return { original, unchanged, guard, remainingMs };
}

function freshAttempt(owner: ReturnType<typeof workflowOwner>, controls: Dependencies) {
  const { held, resource } = owner.original; owner.remainingMs();
  const stopped = snapshotSourceColorMetadata(controls.stopped(held)); owner.remainingMs();
  if (!stopped.sourceColor || stopped.receipt.schemaVersion !== 3 || ownershipUnresolved(stopped)) {
    throw new Error("Source color cleanup workflow requires actual resolved original V3 media settlement");
  }
  const reservation = holdSourceColorCleanupReservation({ held, reference: stopped.sourceColor,
    resourceDir: resource.resource, guard: owner.guard, remainingMs: owner.remainingMs });
  const attemptId = uuid(controls.attemptId(), "cleanup attemptId"); owner.remainingMs();
  if (attemptId[14] !== "4") throw new Error("Source color cleanup workflow requires a fresh UUIDv4 attempt");
  const root = humanCutDirectory(path.dirname(held.claimPath), "cleanup-attempts");
  fs.mkdirSync(path.join(root, attemptId), { mode: 0o700 }); owner.remainingMs();
  return { reservation, attemptId };
}

async function completeWorkflow(owner: ReturnType<typeof workflowOwner>, controls: Dependencies) {
  const { held, projectLease, resource, clock } = owner.original;
  const prepareGuard = () => {
    owner.guard();
    if (observeHumanCutJob(held.job.ctx.dir).sha256 !== held.sha256) throw new Error("Source color cleanup workflow original precleanup journal changed");
  };
  prepareGuard(); const attempt = freshAttempt(owner, controls);
  const recorded = await recordSourceColorCleanupAttempt({ held, ...attempt, guard: prepareGuard, clock }, controls.record);
  commitPreparedSourceColorCleanup(recorded);
  const pending = readSourceColorCleanupPending({ dir: held.job.ctx.dir, guard: owner.guard, remainingMs: owner.remainingMs }, controls.pending);
  const retired = retirePreparedSourceColorReservation({ pending, projectLease, resource }, { workspace: controls.workspace });
  return commitRetiredSourceColorCleanup(retired, controls.final);
}

/** Keep original leases on every return/error. The enclosing owner releases only after separately reading final cleanup.
 * An error can follow either successful CAS; retain its journal/evidence, never retroactively add failure.json.
 * No new attempt/retry is made for a pending retirement: that requires the explicit recovery entry.
 */
export async function runSourceColorCleanupWorkflow(input: SourceColorCleanupWorkflowInput,
  dependencies: Dependencies = sourceColorCleanupWorkflowDependencies) {
  const controls = { ...dependencies, record: { ...dependencies.record }, pending: { ...dependencies.pending }, final: { ...dependencies.final } };
  const owner = workflowOwner(input, controls.workspace);
  const result = await timedStage(owner.original.held.job.ctx.dir, "guided_opening_source_color_protected_cleanup", () => completeWorkflow(owner, controls));
  const started = performance.now(), remaining = owner.remainingMs();
  assertCommittedSourceColorCleanupMetadata(result);
  const elapsed = performance.now() - started;
  if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= remaining) throw new Error("Source color cleanup workflow final evidence exhausted its original protected remainder");
  return result;
}
