/** Completed-data adoption or pending retirement recovery: never another native worker or render allowance. */
import fs from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { mutationProjectRoot } from "@/app/api/_lib/project-mutation";
import { sha256, stringValue, uuid } from "@/lib/producer/contracts/validation";
import { parsePreparedSourceColorCleanupFact } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";
import { acquireGuidedMutation, readGuidedObject } from "./guided-cut-v2-store";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { autoEditJobPath } from "./auto-edit-job-persistence";
import { capturePublication, assertPublication, commitPreparedSourceColorCleanup } from "./guided-source-color-cleanup-pending-commit";
import { readSourceColorCleanupPending, sourceColorCleanupPendingReadDependencies } from "./guided-source-color-cleanup-pending-read";
import { recoverSourceColorRetirementResource, sourceColorRetirementResourceRecoveryDependencies,
  recoverSourceColorResource, sourceColorResourceRecoveryDependencies } from "./guided-source-color-resource-recovery";
import { readSourceColorCleanupHistory, assertSourceColorCleanupHistoryMetadata } from "./guided-source-color-cleanup-history";
import { holdCompletedSourceColorCleanup, sourceColorCleanupAdoptionDependencies } from "./guided-source-color-cleanup-adoption";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { retirePreparedSourceColorReservation } from "./guided-source-color-reservation-retirement";
import { commitRetiredSourceColorCleanup, sourceColorFinalCommitDependencies,
  assertCommittedSourceColorCleanupMetadata } from "./guided-source-color-cleanup-final-commit";
import { readFinalSourceColorCleanupForJournal, sourceColorFinalCleanupReadDependencies,
  assertSourceColorFinalCleanupMetadata } from "./guided-source-color-cleanup-final-read";
import { timedStage } from "./stage-timing";
import { withStageTimingContext } from "./stage-timing-context";
import type { SourceColorCleanupClock } from "./guided-source-color-cleanup-attempt";
import type { ProjectMutationLease } from "./project-mutation-lease";
import type { HeldGradeObservationResource } from "./grade-observation-resource";

export interface SourceColorCleanupRecoveryInput {
  dir: string; expectedToken: string; expectedJournalHash: string; expectedClaimHash: string;
  /** Created by the enclosing request before parsing or acquiring any lease. */
  clock: SourceColorCleanupClock;
}
export interface CompletedSourceColorCleanupRecoveryInput extends SourceColorCleanupRecoveryInput {
  cleanupAttemptId: string; preparedSha256: string;
}
// Resolve cyclic module defaults only on first use, retaining the same code-only dependency object thereafter.
let completedDefaults: typeof sourceColorCleanupAdoptionDependencies & { resource: typeof sourceColorResourceRecoveryDependencies } | undefined;
/** Original admission leaves only. Actual pending/retirement/CAS/final-read implementations cannot be replaced. */
export const sourceColorCleanupRecoveryDependencies = { acquireProject: acquireGuidedMutation,
  get pending() { return sourceColorCleanupPendingReadDependencies; }, get resource() { return sourceColorRetirementResourceRecoveryDependencies; },
  get final() { return sourceColorFinalCommitDependencies; }, get read() { return sourceColorFinalCleanupReadDependencies; },
  get completed() { return completedDefaults ??= { ...sourceColorCleanupAdoptionDependencies, resource: sourceColorResourceRecoveryDependencies }; } };
type Dependencies = typeof sourceColorCleanupRecoveryDependencies;
type Completion = { result: ReturnType<typeof commitRetiredSourceColorCleanup>;
  read: ReturnType<typeof readFinalSourceColorCleanupForJournal> };

/** Preserve the original request and one protected clock across await, CAS, proof read and release. */
class RecoveryOwner {
  readonly original;
  readonly before;
  readonly journal;
  readonly selection;
  project: { lease: ProjectMutationLease; release: () => void; guard: () => void } | undefined;
  resource: HeldGradeObservationResource | undefined;
  private releasedProject = false;
  private releasedResource = false;
  private resourceRelease: (() => void) | undefined;
  constructor(readonly input: SourceColorCleanupRecoveryInput, readonly completed?: CompletedSourceColorCleanupRecoveryInput) {
    this.original = { ...input, receivedAt: input.clock.receivedAt, remaining: input.clock.remainingMs, elapsed: input.clock.elapsedMs };
    if (canonicalProducerDir(input.dir) !== input.dir) throw new Error("Pending cleanup recovery needs its exact canonical producer directory");
    stringValue(input.expectedToken, "expectedToken", 200); sha256(input.expectedJournalHash, "expectedJournalHash");
    sha256(input.expectedClaimHash, "expectedClaimHash");
    this.before = observeHumanCutJob(input.dir);
    this.journal = capturePublication(autoEditJobPath(input.dir), input.expectedJournalHash);
    const pointer = this.before.job.guidedHandoffV2;
    if (this.before.sha256 !== input.expectedJournalHash || this.before.job.token !== input.expectedToken
        || pointer?.openingExecutionClaimHash !== input.expectedClaimHash) {
      throw new Error("Pending source color cleanup recovery request is stale");
    }
    this.selection = this.readSelection(completed);
    this.metadata();
  }
  private readSelection(completed?: CompletedSourceColorCleanupRecoveryInput) {
    const pointer = this.before.job.guidedHandoffV2!;
    if (completed) {
      const attemptId = uuid(completed.cleanupAttemptId, "completed cleanup attemptId");
      if (completed !== this.input || attemptId[14] !== "4" || pointer.openingCleanupHash) throw new Error("Completed cleanup recovery requires its exact precleanup request");
      return Object.freeze({ attemptId, preparedSha256: sha256(completed.preparedSha256, "preparedSha256") });
    }
    if (!pointer.openingCleanupHash) throw new Error("Pending cleanup recovery requires its prepared checkpoint");
    const fact = parsePreparedSourceColorCleanupFact(readGuidedObject(this.input.dir, pointer.openingCleanupHash));
    if (fact.claimHash !== this.input.expectedClaimHash) throw new Error("Pending cleanup fact names another claim");
    return undefined;
  }
  metadata = (): void => {
    const i = this.input, o = this.original;
    if (i.dir !== o.dir || i.expectedToken !== o.expectedToken || i.expectedJournalHash !== o.expectedJournalHash
        || i.expectedClaimHash !== o.expectedClaimHash || i.clock !== o.clock || i.clock.receivedAt !== o.receivedAt
        || i.clock.remainingMs !== o.remaining || i.clock.elapsedMs !== o.elapsed
        || (this.completed && (this.completed !== this.input || this.completed.cleanupAttemptId !== this.selection?.attemptId
          || this.completed.preparedSha256 !== this.selection?.preparedSha256))
        || (this.project && this.project.lease.release !== this.project.release)
        || (this.resource && this.resource.lease.release !== this.resourceRelease)) {
      throw new Error("Pending cleanup recovery original request, clock or lease handle changed");
    }
  };
  guard = (): void => {
    this.metadata();
    if (!this.releasedProject) this.project?.guard();
    if (!this.releasedResource) this.resource?.assertResource();
    this.metadata();
  };
  remaining = (): number => {
    this.metadata(); const started = performance.now(), remaining = this.original.remaining.call(this.original.clock);
    this.guard(); const elapsed = performance.now() - started, result = remaining - elapsed;
    if (!Number.isFinite(remaining) || remaining > 300_000 || !Number.isFinite(elapsed) || elapsed < 0 || result <= 0) {
      throw new Error("Pending cleanup recovery exhausted its original protected allowance");
    }
    return result;
  };
  bindProject(lease: ProjectMutationLease): void {
    this.project = { lease, release: lease.release, guard: cutPreviewLeaseGuard(this.original.dir, lease) };
    this.remaining(); assertPublication(this.journal);
  }
  bindResource(resource: HeldGradeObservationResource): void {
    this.resource = resource; this.resourceRelease = resource.lease.release; this.remaining();
  }
  release(kind: "project" | "resource"): void {
    const lease = kind === "project" ? this.project!.lease : this.resource!.lease;
    const release = kind === "project" ? this.project!.release : this.resourceRelease!;
    const root = kind === "project" ? mutationProjectRoot(this.original.dir) : this.resource!.resource;
    this.guard(); const lock = path.join(root, ".sniper-project-mutation.lock"), before = fs.lstatSync(lock);
    release.call(lease);
    let after: fs.Stats | undefined;
    try { after = fs.lstatSync(lock); } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
    if (after && after.dev === before.dev && after.ino === before.ino) throw new Error("Pending cleanup recovery lease release is unverified");
    if (kind === "project") this.releasedProject = true; else this.releasedResource = true;
    this.metadata();
  }
}

function finishPending(owner: RecoveryOwner, controls: Dependencies): Completion {
  const { dir } = owner.original;
  const pending = readSourceColorCleanupPending({ dir, guard: owner.guard, remainingMs: owner.remaining }, controls.pending);
  if (pending.pendingJournalHash !== owner.original.expectedJournalHash || pending.fact.claimHash !== owner.original.expectedClaimHash
      || !isDeepStrictEqual(pending.job, owner.before.job)) throw new Error("Pending cleanup changed during project acquisition");
  assertPublication(owner.journal);
  owner.bindResource(recoverSourceColorRetirementResource({ pending, projectLease: owner.project!.lease }, controls.resource));
  return finishHeldPending(owner, pending, controls);
}

function finishHeldPending(owner: RecoveryOwner, pending: ReturnType<typeof readSourceColorCleanupPending>, controls: Dependencies): Completion {
  const { dir } = owner.original;
  const retired = retirePreparedSourceColorReservation({ pending, projectLease: owner.project!.lease, resource: owner.resource! },
    { workspace: controls.resource.workspace });
  const result = commitRetiredSourceColorCleanup(retired, controls.final);
  owner.remaining(); assertCommittedSourceColorCleanupMetadata(result);
  const proofStarted = performance.now();
  const read = readFinalSourceColorCleanupForJournal({ dir, journal: { path: autoEditJobPath(dir), observed: observeHumanCutJob(dir) },
    guard: owner.guard, remainingMs: () => {
      const remaining = owner.remaining(), elapsed = performance.now() - proofStarted;
      if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= 30_000) throw new Error("Pending recovery final read-only proof allowance expired");
      return Math.min(30_000 - elapsed, remaining);
    } }, controls.read);
  assertSourceColorFinalCleanupMetadata(read);
  if (read.sha256 !== result.journalHash || read.cleanupHash !== result.cleanupHash || read.held.claimHash !== result.claimHash) {
    throw new Error("Pending recovery final cleanup readback differs from its actual commit");
  }
  return { result, read };
}

/** One protected recovery allowance delegates to the original clock; this wrapper starts no timer. */
function completedRecoveryClock(owner: RecoveryOwner): SourceColorCleanupClock {
  return { receivedAt: owner.original.receivedAt, remainingMs: owner.remaining, elapsedMs: () => {
    owner.metadata(); const elapsed = owner.original.elapsed.call(owner.original.clock); owner.metadata();
    if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed > 300_000) throw new Error("Completed cleanup recovery original elapsed clock is invalid");
    return elapsed;
  } };
}

/** Authenticate all prior completed attempts before acquiring the cold global owner; never replay native work. */
function finishCompleted(owner: RecoveryOwner, controls: Dependencies): Completion {
  const { dir } = owner.original, selection = owner.selection!, original = controls.completed;
  const held = original.claim(dir), fixed = snapshotSourceColorMetadata(held);
  const guard = () => {
    owner.guard(); assertPublication(owner.journal);
    if (!isDeepStrictEqual(held, fixed) || held.claimHash !== owner.original.expectedClaimHash
        || held.sha256 !== owner.before.sha256 || !isDeepStrictEqual(held.job, owner.before.job)
        || !isDeepStrictEqual(held.bytes, owner.before.bytes)) throw new Error("Completed cleanup recovery original current claim changed");
  };
  const history = readSourceColorCleanupHistory({ held, guard, remainingMs: owner.remaining }, original.history);
  const selected = history.attempts.find(row => row.attemptId === selection.attemptId);
  if (!selected || selected.preparedRef.sha256 !== selection.preparedSha256) throw new Error("Completed cleanup recovery preparation request is stale");
  const prepareGuard = () => { guard(); assertSourceColorCleanupHistoryMetadata(history); };
  owner.bindResource(recoverSourceColorResource({ held, stopped: selected.evidence.stop,
    projectGuard: prepareGuard, remainingMs: owner.remaining }, original.resource));
  prepareGuard(); const clock = completedRecoveryClock(owner);
  const adopted = holdCompletedSourceColorCleanup({ held, projectLease: owner.project!.lease, resource: owner.resource!,
    attemptId: selection.attemptId, clock }, original);
  prepareGuard(); owner.remaining(); prepareGuard();
  if (adopted.preparedRef.sha256 !== selection.preparedSha256) throw new Error("Completed cleanup preparation changed during adoption");
  const committed = commitPreparedSourceColorCleanup(adopted);
  const pending = readSourceColorCleanupPending({ dir, guard: owner.guard, remainingMs: owner.remaining }, controls.pending);
  if (pending.pendingJournalHash !== committed.pendingJournalHash || canonicalJsonSha256(pending.fact) !== adopted.factHash) {
    throw new Error("Completed cleanup recovery first checkpoint differs from its actual adoption");
  }
  return finishHeldPending(owner, pending, controls);
}

function finalEvidence(owner: RecoveryOwner, completion: Completion, committed = false): void {
  const started = performance.now(), remaining = owner.remaining();
  assertSourceColorFinalCleanupMetadata(completion.read);
  if (committed) assertCommittedSourceColorCleanupMetadata(completion.result);
  const elapsed = performance.now() - started;
  if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= remaining) throw new Error("Pending recovery final evidence exhausted its original remainder");
}

async function acquireAndRecover(owner: RecoveryOwner, controls: Dependencies): Promise<Completion> {
  owner.remaining();
  const lease = await controls.acquireProject(owner.original.dir, { workflowVersion: 2, action: "reconcile-guided-opening",
    expectedStatus: "treatment_admitted", expectedToken: owner.original.expectedToken, expectedJournalHash: owner.original.expectedJournalHash });
  const releaseProject = lease.release;
  try {
    owner.bindProject(lease);
    const completion = owner.selection ? finishCompleted(owner, controls) : finishPending(owner, controls);
    finalEvidence(owner, completion, true);
    owner.release("resource"); finalEvidence(owner, completion); owner.release("project"); finalEvidence(owner, completion);
    return completion;
  } catch (error) {
    if (owner.resource || error instanceof AggregateError) throw error;
    try { releaseProject.call(lease); } catch (releaseError) { throw new AggregateError([error, releaseError], "Pending cleanup recovery failed and project release is unverified"); }
    throw error;
  }
}

/** Acquisition failure releases only a newly acquired project lease; after handoff, errors retain each unreleased lease.
 * Final readback permits exact resource then project release. No error writes failure.json or starts native cleanup.
 * The timing span includes acquisition, proof and release; the same enclosing clock also charges entry parsing.
 */
export async function reconcilePendingSourceColorCleanup(input: SourceColorCleanupRecoveryInput,
  dependencies: Dependencies = sourceColorCleanupRecoveryDependencies) {
  return recover(new RecoveryOwner(input), dependencies);
}

/** Explicit completed-but-uncommitted recovery; partial attempts and stale preparation requests refuse.
 * Owns actual project/global acquisition, adoption, both CAS edges, final readback and verified release.
 * This is not a native-cleanup retry, and errors may follow a committed pending or final checkpoint.
 */
export async function reconcileCompletedSourceColorCleanup(input: CompletedSourceColorCleanupRecoveryInput,
  dependencies: Dependencies = sourceColorCleanupRecoveryDependencies) {
  return recover(new RecoveryOwner(input, input), dependencies);
}

async function recover(owner: RecoveryOwner, dependencies: Dependencies) {
  const controls = { ...dependencies, pending: { ...dependencies.pending }, resource: { ...dependencies.resource },
    final: { ...dependencies.final }, read: { ...dependencies.read }, completed: { ...dependencies.completed,
      history: { ...dependencies.completed.history }, resource: { ...dependencies.completed.resource } } }, job = owner.before.job;
  const completion = await withStageTimingContext({ runId: job.artifactToken ?? job.token,
    attemptId: `source-color-${owner.selection ? "adoption" : "retirement"}:${owner.original.expectedClaimHash}`, attemptNo: job.attempts }, () =>
    timedStage(owner.original.dir, owner.selection ? "guided_opening_source_color_completion_recovery"
      : "guided_opening_source_color_retirement_recovery", () => acquireAndRecover(owner, controls)));
  finalEvidence(owner, completion); return completion.result;
}
