/** Exact stopped-execution resource acquisition, not native cleanup or retirement.
 * This cold-only entry never creates a namespace or deletes an active marker.
 * Live execution must keep its existing resource handle instead of reacquiring.
 */
import fs from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { workspaceRoot } from "@/app/api/_lib/workspace";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { readStoppedOpeningProcess, ownershipUnresolved, type HeldOpeningClaim } from "./guided-opening-process";
import { holdSourceColorCleanupReservation } from "./guided-source-color-cleanup-hold";
import { privateDirectory } from "./grade-observation-store";
import { acquireProjectMutationLease, type ProjectMutationLease } from "./project-mutation-lease";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { assertSourceColorCleanupPendingMetadata, remainingSourceColorCleanupPending,
  type SourceColorCleanupPendingEvidence } from "./guided-source-color-cleanup-pending-read";
import type { HeldGradeObservationResource } from "./grade-observation-resource";

type StoppedOpening = ReturnType<typeof readStoppedOpeningProcess>;
export interface SourceColorResourceRecoveryInput {
  held: HeldOpeningClaim;
  stopped: StoppedOpening;
  projectGuard: () => void;
  /** The caller's same protected cleanup allowance; this helper creates no clock. */
  remainingMs: () => number;
}

/** Code-only TEST seams for existing process/lease/workspace admission, never JSON authority. */
export const sourceColorResourceRecoveryDependencies = {
  workspace: workspaceRoot, canonical: fs.realpathSync, directory: privateDirectory,
  acquire: acquireProjectMutationLease, leaseGuard: cutPreviewLeaseGuard, stopped: readStoppedOpeningProcess,
};
type Dependencies = typeof sourceColorResourceRecoveryDependencies;

function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Source color recovery original ${label} changed`);
}

/** Hold caller metadata before any callback without freezing caller-owned objects. */
class RecoveryLifetime {
  private readonly original;
  private readonly fixed;
  private resourceGuard: (() => void) | undefined;
  constructor(readonly input: SourceColorResourceRecoveryInput, readonly dependencies: Dependencies) {
    this.original = { held: input.held, stopped: input.stopped, projectGuard: input.projectGuard, remainingMs: input.remainingMs };
    this.fixed = snapshotSourceColorMetadata({ held: input.held, stopped: input.stopped });
  }
  unchanged = (): void => {
    const i = this.input, o = this.original;
    if (i.held !== o.held || i.stopped !== o.stopped || i.projectGuard !== o.projectGuard || i.remainingMs !== o.remainingMs) {
      throw new Error("Source color recovery original caller identity changed");
    }
    same({ held: i.held, stopped: i.stopped }, this.fixed, "claim/stopped metadata");
  };
  guard = (): void => {
    this.unchanged(); this.original.projectGuard(); this.unchanged();
    this.resourceGuard?.(); this.unchanged();
  };
  remaining = (): number => {
    this.unchanged(); const remaining = this.original.remainingMs(); this.unchanged();
    if (!Number.isFinite(remaining) || remaining <= 0 || remaining > 300_000) throw new Error("Source color recovery protected cleanup deadline is invalid");
    this.resourceGuard?.(); this.unchanged();
    return remaining;
  };
  bindResource(resource: string, lease: ProjectMutationLease): () => void {
    this.unchanged();
    if (this.resourceGuard) throw new Error("Source color recovery cannot replace its acquired lease");
    this.resourceGuard = this.dependencies.leaseGuard(resource, lease); this.unchanged();
    return this.resourceGuard;
  }
  readStopped = (): void => {
    this.unchanged(); const current = this.dependencies.stopped(this.original.held); this.unchanged();
    if (current.receipt.schemaVersion !== 3 || current.receipt.groupStopped !== true || !current.sourceColor
        || ownershipUnresolved(current) || current.liveDescendants.length || current.unknownDescendants.length
        || current.unrecordedSpawns.length) throw new Error("Source color recovery requires actual resolved V3 stopped-process evidence");
    same(current, this.fixed.stopped, "stopped-process evidence");
  };
}

interface AcquiredLease {
  lease: ProjectMutationLease; release: () => void; lock: string; identity: fs.BigIntStats;
}

/** Hold the actual acquired inode and release method before any later admission callback. */
function holdAcquiredLease(resource: string, lease: ProjectMutationLease): AcquiredLease {
  const release = lease.release, lock = path.join(resource, ".sniper-project-mutation.lock");
  try {
    const identity = fs.lstatSync(lock, { bigint: true });
    if (!identity.isFile()) throw new Error("Acquired source color lock is not a regular file");
    return { lease, release, lock, identity };
  } catch (error) {
    throw new AggregateError([error], "Source color acquired lock capture failed and release is unverified");
  }
}

/** A void release return is not evidence that the original owned lock was removed. */
function assertAcquiredLeaseReleased(held: AcquiredLease): void {
  let after: fs.BigIntStats;
  try { after = fs.lstatSync(held.lock, { bigint: true }); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
  if (after.dev === held.identity.dev && after.ino === held.identity.ino) {
    throw new Error("Source color acquired lock release is unverified");
  }
}

/** Never swallow release uncertainty or touch a reservation on a failed acquisition. */
function releaseFailedAcquisition(held: AcquiredLease, failure: unknown): never {
  try { held.release.call(held.lease); assertAcquiredLeaseReleased(held); }
  catch (releaseFailure) {
    throw new AggregateError([failure, releaseFailure], "Source color recovery acquisition failed and lease release is unverified");
  }
  throw failure;
}

/** Acquire only the existing global lease, after authenticating the complete retained name map.
 * assertCurrent re-reads actual original stopped provenance and all three held metadata files.
 * It is a metadata lifetime check, not a hard timer: the enclosing owner checks its same
 * remaining allowance immediately before native work/commit. Success has no auto-finalizer;
 * later failures retain this lease until the owner resolves cleanup and release separately.
 */
export function recoverSourceColorResource(input: SourceColorResourceRecoveryInput,
  dependencies: Dependencies = sourceColorResourceRecoveryDependencies) {
  const controls = { ...dependencies }, lifetime = new RecoveryLifetime(input, controls);
  const workspace = controls.canonical(controls.workspace()); lifetime.unchanged();
  const expectedResource = path.join(workspace, ".sniper-color-resource");
  const resource = controls.directory(expectedResource); lifetime.unchanged();
  if (resource !== expectedResource) throw new Error("Source color recovery global resource namespace differs");
  if (!input.stopped.sourceColor) throw new Error("Source color recovery requires a V3 source color reference");
  const cleanupHold = holdSourceColorCleanupReservation({ held: input.held, reference: input.stopped.sourceColor,
    resourceDir: resource, guard: lifetime.guard, remainingMs: lifetime.remaining });
  const assertCurrent = () => {
    cleanupHold.assertCurrent(); lifetime.readStopped(); cleanupHold.assertCurrent(); lifetime.unchanged();
  };
  assertCurrent();
  const acquired = controls.acquire(resource, "guided opening exact source color cleanup recovery");
  if (!acquired.lease) { lifetime.unchanged(); throw new Error("The shared private color worker is busy"); }
  const lease = acquired.lease, heldLease = holdAcquiredLease(resource, lease);
  try {
    const assertResource = lifetime.bindResource(resource, lease); assertCurrent();
    return Object.freeze({ resource, lease, assertResource, cleanupHold, assertCurrent });
  } catch (error) { return releaseFailedAcquisition(heldLease, error); }
}

export interface SourceColorRetirementResourceRecoveryInput {
  pending: SourceColorCleanupPendingEvidence;
  projectLease: ProjectMutationLease;
}
/** Code-only namespace/fault seams; no stopped flags, marker interpretation or alternate clock. */
export const sourceColorRetirementResourceRecoveryDependencies = {
  workspace: workspaceRoot, canonical: fs.realpathSync, directory: privateDirectory,
  acquire: acquireProjectMutationLease, leaseGuard: cutPreviewLeaseGuard,
};
type RetirementDependencies = typeof sourceColorRetirementResourceRecoveryDependencies;

/** Current pending evidence and project ownership remain original across resource acquisition. */
class RetirementRecoveryLifetime {
  readonly controls;
  private readonly original;
  private readonly projectGuard;
  private resource: { lease: ProjectMutationLease; release: () => void; guard: () => void } | undefined;
  constructor(readonly input: SourceColorRetirementResourceRecoveryInput, readonly dependencies: RetirementDependencies) {
    this.controls = { ...dependencies };
    this.original = { pending: input.pending, assertPending: input.pending.assertCurrent,
      projectLease: input.projectLease, releaseProject: input.projectLease.release };
    this.metadata();
    this.projectGuard = this.controls.leaseGuard(input.pending.job.ctx.dir, input.projectLease); this.metadata();
  }
  metadata = (): void => {
    const i = this.input, o = this.original;
    if (i.pending !== o.pending || i.pending.assertCurrent !== o.assertPending || i.projectLease !== o.projectLease
        || i.projectLease.release !== o.releaseProject || Object.keys(this.controls).some(key =>
          this.dependencies[key as keyof RetirementDependencies] !== this.controls[key as keyof RetirementDependencies])
        || (this.resource && this.resource.lease.release !== this.resource.release)) {
      throw new Error("Source color retirement recovery original caller or dependency identity changed");
    }
    assertSourceColorCleanupPendingMetadata(o.pending);
    if (o.pending.scope !== "current-pending-source-color-cleanup-not-retirement-or-approval") {
      throw new Error("Source color retirement recovery requires its actual current pending journal");
    }
  };
  check = (): void => {
    this.metadata(); this.projectGuard(); remainingSourceColorCleanupPending(this.original.pending);
    this.metadata(); this.projectGuard(); this.resource?.guard(); this.metadata();
  };
  bindResource(resource: string, lease: ProjectMutationLease): () => void {
    const release = lease.release;
    this.metadata();
    if (this.resource) throw new Error("Source color retirement recovery cannot replace its acquired lease");
    const guard = this.controls.leaseGuard(resource, lease);
    this.resource = { lease, release, guard }; this.check(); return guard;
  }
}

/** Reacquire only exclusion for an authenticated current pending retirement.
 * The marker may exist or be absent: this function never reads or interprets it.
 * The exact retirement primitive separately checks its bytes/absence and ack.
 * Project authority is the existing live same-process lock protocol, not a
 * private JavaScript lease-object capability. Supplied handle identity stays held.
 * Success returns the actual resource-only guard; later errors never auto-release.
 */
export function recoverSourceColorRetirementResource(input: SourceColorRetirementResourceRecoveryInput,
  dependencies: RetirementDependencies = sourceColorRetirementResourceRecoveryDependencies): HeldGradeObservationResource {
  const owner = new RetirementRecoveryLifetime(input, dependencies), controls = owner.controls; owner.check();
  const workspace = controls.canonical(controls.workspace()); owner.check();
  const expected = path.join(workspace, ".sniper-color-resource"), resource = controls.directory(expected, false); owner.check();
  if (resource !== expected || input.pending.fact.reservation.path !== path.join(resource, "active.json")) {
    throw new Error("Source color retirement recovery resource namespace differs");
  }
  const acquired = controls.acquire(resource, "guided opening pending source color retirement recovery");
  if (!acquired.lease) { owner.check(); throw new Error("The shared private color worker is busy"); }
  const lease = acquired.lease, heldLease = holdAcquiredLease(resource, lease);
  try {
    const assertResource = owner.bindResource(resource, lease); owner.check(); assertResource(); owner.metadata();
    return Object.freeze({ resource, lease, assertResource });
  } catch (error) { return releaseFailedAcquisition(heldLease, error); }
}
