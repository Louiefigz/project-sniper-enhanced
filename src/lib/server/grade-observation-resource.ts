/** Shared color-worker exclusion, not cleanup, observation or approval authority.
 * The caller already owns its project lease and original clock. This helper
 * acquires only the existing global resource and never starts work or recovery.
 */
import fs from "node:fs";
import path from "node:path";
import { workspaceRoot } from "@/app/api/_lib/workspace";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { acquireProjectMutationLease, type ProjectMutationLease } from "./project-mutation-lease";
import { privateDirectory } from "./grade-observation-store";

export interface HeldGradeObservationResource {
  resource: string;
  /** Actual acquired lease; release remains the enclosing owner's decision. */
  lease: ProjectMutationLease;
  /** Rechecks the original live lock inode, nonce and process identity. */
  assertResource: () => void;
}

/** Any directory entry fences work, including a dangling link or special file. */
function activeMarkerExists(file: fs.PathLike): boolean {
  try { fs.lstatSync(file); return true; }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
    throw error;
  }
}

/** Code-only fault seam for temp-root tests; no serialized caller controls. */
export const gradeObservationResourceDependencies = {
  workspace: workspaceRoot,
  canonical: fs.realpathSync,
  directory: privateDirectory,
  acquire: acquireProjectMutationLease,
  guard: cutPreviewLeaseGuard,
  activeExists: activeMarkerExists,
};
type Dependencies = typeof gradeObservationResourceDependencies;

/** Release only this attempt's new lease; preserve both errors if release fails. */
function failedAcquisition(lease: ProjectMutationLease, failure: unknown): never {
  try { lease.release(); }
  catch (releaseFailure) {
    throw new AggregateError([failure, releaseFailure], "Color resource acquisition failed and lease release is unverified");
  }
  throw failure;
}

/** An active record is a fence, including malformed bytes; never parse/delete it. */
function validateAcquisition(resource: string, lease: ProjectMutationLease, dependencies: Dependencies) {
  try {
    const assertResource = dependencies.guard(resource, lease);
    if (dependencies.activeExists(path.join(resource, "active.json"))) {
      throw new Error("A prior color worker has unverified cleanup; operator recovery is required");
    }
    assertResource();
    return { resource, lease, assertResource };
  } catch (error) { return failedAcquisition(lease, error); }
}

/** Acquire once using the existing workspace namespace and real lease protocol.
 * Busy acquisition never releases somebody else's lease. Validation failures
 * release only the lease acquired here and retain every active record/file.
 * Success has no auto-finalizer: callers must separately prove resource cleanup
 * and process settlement before releasing. No project lease or clock is made.
 */
export function acquireGradeObservationResource(operation: string,
  dependencies: Dependencies = gradeObservationResourceDependencies): HeldGradeObservationResource {
  const workspace = dependencies.canonical(dependencies.workspace());
  const resource = dependencies.directory(path.join(workspace, ".sniper-color-resource"), true);
  const acquired = dependencies.acquire(resource, operation);
  if (!acquired.lease) throw new Error("The shared private color worker is busy");
  return validateAcquisition(resource, acquired.lease, dependencies);
}
