import { claimGuidedOpeningExecution } from "./guided-opening-claim";
import { runClaimedOpeningMedia } from "./guided-opening-process";
import { reconcileClaimedOpeningUnderLease } from "./guided-opening-cleanup";
import { readCommittedOpeningCleanup } from "./guided-opening-cleanup-store";
import { verifyCleanedOpeningMediaUnderLease } from "./guided-opening-readback";
import { selectVerifiedOpeningMediaUnderLease } from "./guided-opening-selection";
import { readGuidedOpeningStatus } from "./guided-opening-status";
import { parsePrepareGuidedOpeningRequest } from "@/lib/producer/contracts/guided-source-color-v1";
import { beginOpeningControllerClaim, bindOpeningControllerClaim, observeOpeningControllerCleanup,
  type OpeningControllerLifecycle } from "./guided-opening-controller-lifecycle";

export type OpeningExecutionInput = Parameters<typeof claimGuidedOpeningExecution>[0];

/** The controller and media fixture share the same execution, cleanup and selection sequence.
 * Overrides exercise failure boundaries in tests; no dependency grants human approval. */
export const openingExecutionDependencies = {
  claim: claimGuidedOpeningExecution,
  run: runClaimedOpeningMedia,
  cleanup: reconcileClaimedOpeningUnderLease,
  readCleanup: readCommittedOpeningCleanup,
  verify: verifyCleanedOpeningMediaUnderLease,
  select: selectVerifiedOpeningMediaUnderLease,
  status: readGuidedOpeningStatus,
};
type Dependencies = typeof openingExecutionDependencies;

async function executeAndClean(input: OpeningExecutionInput, deps: Dependencies, lifecycle?: OpeningControllerLifecycle) {
  if (parsePrepareGuidedOpeningRequest(input.operation.record.submission).schemaVersion === 2) {
    throw new Error("Source-color execution and full-reservation cleanup are not connected yet; no opening claim or worker may start");
  }
  input.remainingMs();
  if (lifecycle) beginOpeningControllerClaim(lifecycle, input);
  const held = deps.claim(input), dir = input.proposal.job.ctx.dir;
  if (lifecycle) bindOpeningControllerClaim(lifecycle, held);
  const process = await deps.run({ dir, lease: input.lease, remainingMs: input.remainingMs });
  if (!process.receipt.groupStopped) {
    throw new Error("Opening owned group stop is unproved; keep its claim and prohibit selection");
  }
  // Cleanup has its own protected allowance, including when media exhausted its budget.
  // Do not insert a generation-deadline check before releasing verified owned resources.
  const cleanup = await deps.cleanup({ dir, lease: input.lease, expectedClaimHash: held.claimHash });
  if (cleanup.claimRetained) throw new Error("Opening resource ownership remains unresolved; no media may be selected");
  const observed = lifecycle ? observeOpeningControllerCleanup(lifecycle, { claimHash: held.claimHash, cleanupHash: cleanup.cleanupHash })
    : deps.readCleanup(dir);
  if (observed.cleanupHash !== cleanup.cleanupHash || observed.held.claimHash !== held.claimHash) {
    throw new Error("Opening committed cleanup differs from the exact owned execution");
  }
  if (process.receipt.status !== "complete") throw new Error(`Opening worker failed: ${process.receipt.error}`);
  return { held, process, cleanup };
}

/** Production orchestration under the caller's actual project lease and original remaining budget.
 * A selected opening is reviewable media only: never an opening/body/delivery approval. */
export async function executeGuidedOpeningUnderLease(
  input: OpeningExecutionInput,
  overrides: Partial<Dependencies> = {},
  lifecycle?: OpeningControllerLifecycle,
) {
  const deps = { ...openingExecutionDependencies, ...overrides }, dir = input.proposal.job.ctx.dir;
  const completed = await executeAndClean(input, deps, lifecycle);
  input.remainingMs();
  const verified = await deps.verify({ dir, lease: input.lease, expectedCleanupHash: completed.cleanup.cleanupHash,
    remainingMs: input.remainingMs });
  input.remainingMs();
  const selectionStarted = performance.now();
  const selection = deps.select({ dir, lease: input.lease, verified, remainingMs: input.remainingMs });
  const status = deps.status(dir);
  if (status.state !== "ready-for-review" || status.selectionHash !== selection.selectionHash || status.openingApproved) {
    throw new Error("Opening selection did not become the exact unapproved reviewable media");
  }
  return { ...completed, verified, selection, status, selectionElapsedMs: performance.now() - selectionStarted };
}
