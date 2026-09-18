import {
  acquireProjectMutationLease,
  type ProjectMutationConflict,
  type ProjectMutationLease,
  type ProjectMutationLeaseResult,
} from "./project-mutation-lease";

const DEFAULT_ATTEMPTS = 200;
const RETRY_MS = 25;

interface WorkerMutationLeaseRuntime {
  acquire?: (
    projectRoot: string,
    operation: string,
  ) => ProjectMutationLeaseResult;
  wait?: (milliseconds: number) => Promise<void>;
  attempts?: number;
}

const wait = (milliseconds: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

/**
 * The launch request briefly owns the project lease while it spawns us.
 * Retry that exact handoff, then retain the shared writer lease for the run.
 */
export async function acquireAutoEditWorkerMutationLease(
  projectRoot: string,
  runtime: WorkerMutationLeaseRuntime = {},
): Promise<ProjectMutationLease> {
  const acquire = runtime.acquire ?? acquireProjectMutationLease;
  const delay = runtime.wait ?? wait;
  const attempts = runtime.attempts ?? DEFAULT_ATTEMPTS;
  let conflict: ProjectMutationConflict = {};
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const result = acquire(projectRoot, "running detached Auto Edit");
    if (result.lease) return result.lease;
    conflict = result.conflict;
    if (attempt + 1 < attempts) await delay(RETRY_MS);
  }
  const holder = conflict.operation
    ? ` held by ${conflict.operation}` : "";
  const stale = conflict.stale ? " (stale owner requires recovery)" : "";
  throw new Error(`Auto Edit worker could not acquire project mutation lease${holder}${stale}`);
}
