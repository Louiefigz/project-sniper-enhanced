/** Second exact cleanup CAS. Only actual retirement plus retained pending history may clear the claim. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { parseFinalSourceColorCleanupFact } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";
import { autoEditJobPath } from "./auto-edit-job-persistence";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { readRetainedSourceColorCleanupPending, assertSourceColorCleanupPendingMetadata } from "./guided-source-color-cleanup-pending-read";
import { buildSourceColorCleanupRetiredJob } from "./guided-source-color-cleanup-retired-job";
import { writeGuidedObject } from "./guided-cut-v2-store";
import { commitGuidedJob } from "./guided-cut-v2";
import { retainGenerationClockObservation } from "./generation-clock-watermark";
import { freezeSourceColorValue } from "./guided-source-color-staging-hold";
import { capturePublication, assertPublication } from "./guided-source-color-cleanup-pending-commit";
import { assertSourceColorReservationRetired, pendingSourceColorRetirement, remainingSourceColorRetirement,
  assertSourceColorRetirementResourceOwnership, type retirePreparedSourceColorReservation } from "./guided-source-color-reservation-retirement";

type Retired = ReturnType<typeof retirePreparedSourceColorReservation>;
type Checkpoint = { started: number; remaining: number; observedAt: string };
const finalCommitMetadata = new WeakMap<object, () => void>();
/** Only code may supply explicit TEST claim/native leaves; history still requires a genuine authenticated read. */
export const sourceColorFinalCommitDependencies = { history: readRetainedSourceColorCleanupPending };
export interface SourceColorFinalCommitFaults { beforeCasGuard?: (invocation: number) => void; afterCas?: () => void }

function finalFact(retired: Retired) {
  const pending = pendingSourceColorRetirement(retired), original = pending.fact;
  const fact = parseFinalSourceColorCleanupFact({ schemaVersion: 2, kind: "guided-opening-source-color-cleanup-commit",
    scope: "exact-owned-resource-cleanup-and-reservation-retirement-not-approval", phase: "retired", claimRetained: false,
    claimHash: original.claimHash, executionId: original.executionId, cleanupAttemptId: original.cleanupAttemptId,
    preparedFactHash: pending.factHash, pendingJournalHash: pending.pendingJournalHash, retirementAck: retired.reference,
    clockHash: original.clockHash, generationStartedAt: original.generationStartedAt, createdAt: new Date().toISOString(),
    mediaSelected: false, openingApproved: false, deliveryApproved: false });
  if (fact.createdAt < retired.ack.observedAt) throw new Error("Source color final cleanup clock precedes actual retirement");
  return { pending, fact: freezeSourceColorValue(fact), factHash: canonicalJsonSha256(fact) };
}

function preservePending(retired: Retired, original: ReturnType<typeof finalFact>) {
  const dir = original.pending.job.ctx.dir, current = observeHumanCutJob(dir);
  if (current.sha256 !== original.pending.pendingJournalHash || !isDeepStrictEqual(current.job, original.pending.job)) {
    throw new Error("Source color final cleanup lost its exact pending journal");
  }
  const journal = capturePublication(autoEditJobPath(dir), current.sha256);
  assertSourceColorReservationRetired(retired); saveHumanCutJobSnapshot(dir, current);
  const snapshot = capturePublication(path.join(dir, "human-cut-job-snapshots", `${current.sha256}.json`), current.sha256);
  assertSourceColorReservationRetired(retired); assertPublication(journal); assertPublication(snapshot);
  return { dir, journal, snapshot };
}

function retainedHistory(retired: Retired, original: ReturnType<typeof finalFact>, controls: typeof sourceColorFinalCommitDependencies) {
  const history = controls.history({ dir: original.pending.job.ctx.dir,
    guard: () => assertSourceColorReservationRetired(retired), remainingMs: () => remainingSourceColorRetirement(retired) }, original.pending.pendingJournalHash);
  assertSourceColorCleanupPendingMetadata(history);
  if (history.scope !== "retained-pending-source-color-cleanup-not-retirement-or-approval"
      || history.pendingJournalHash !== original.pending.pendingJournalHash || history.factHash !== original.pending.factHash
      || !isDeepStrictEqual(history.job, original.pending.job) || !isDeepStrictEqual(history.fact, original.pending.fact)
      || !isDeepStrictEqual(history.result, original.pending.result)) throw new Error("Source color final cleanup history differs from its actual pending parent");
  return history;
}

function finalLifetime(retired: Retired, controls: typeof sourceColorFinalCommitDependencies) {
  const original = finalFact(retired), saved = preservePending(retired, original), history = retainedHistory(retired, original, controls);
  const job = buildSourceColorCleanupRetiredJob({ job: original.pending.job,
    pendingJournalHash: original.pending.pendingJournalHash, prepared: original.pending.fact }, original.fact);
  assertSourceColorReservationRetired(retired);
  const published = writeGuidedObject(saved.dir, original.fact);
  if (published !== original.factHash) throw new Error("Source color final cleanup published another fact");
  const factFile = capturePublication(path.join(saved.dir, ".sniper-authority-v1/objects/receipts", `${published}.json`), published);
  const metadata = () => {
    assertSourceColorCleanupPendingMetadata(history); assertPublication(saved.snapshot); assertPublication(factFile);
    assertSourceColorRetirementResourceOwnership(retired);
  };
  const guard = (): Checkpoint => {
    const started = performance.now(), remaining = remainingSourceColorRetirement(retired);
    metadata(); assertPublication(saved.journal);
    const observedAt = new Date().toISOString(), elapsed = performance.now() - started;
    if (observedAt < original.fact.createdAt || !Number.isFinite(elapsed) || elapsed < 0 || elapsed >= remaining) {
      throw new Error("Source color final cleanup exhausted its original remainder or wall clock before CAS");
    }
    return { started: performance.now(), remaining: remaining - elapsed, observedAt };
  };
  guard(); return { ...original, ...saved, history, job, metadata, guard };
}

function finalTail(checkpoint: Checkpoint | undefined): void {
  if (!checkpoint) throw new Error("Source color final cleanup CAS omitted its original clock guard");
  const elapsed = performance.now() - checkpoint.started;
  if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= checkpoint.remaining || new Date().toISOString() < checkpoint.observedAt) {
    throw new Error("Source color final cleanup CAS tail expired; final cleanup may be committed and all evidence must be retained");
  }
}

/** No cleanup retry, marker deletion, worker, lease release, selection or approval occurs in this commit.
 * Any error after CAS may leave the final fact active; never write failure.json retroactively.
 */
export function commitRetiredSourceColorCleanup(retired: Retired,
  dependencies = sourceColorFinalCommitDependencies, testOnly?: SourceColorFinalCommitFaults) {
  const controls = { ...dependencies }, faults = { ...testOnly }, owner = finalLifetime(retired, controls);
  let checkpoint: Checkpoint | undefined, invocation = 0;
  const guard = () => {
    faults.beforeCasGuard?.(++invocation);
    retainGenerationClockObservation({ dir: owner.dir,
      origin: { clockHash: owner.fact.clockHash, startedAt: owner.fact.generationStartedAt }, executionId: owner.fact.executionId,
      observedAt: new Date().toISOString() }, () => assertSourceColorReservationRetired(retired));
    checkpoint = owner.guard();
  };
  commitGuidedJob({ beforeHash: owner.pending.pendingJournalHash, job: owner.job, guard }); faults.afterCas?.();
  const current = observeHumanCutJob(owner.dir);
  if (!isDeepStrictEqual(current.job, owner.job)) throw new Error("Source color final cleanup journal changed after CAS; retain all committed evidence");
  const journal = capturePublication(autoEditJobPath(owner.dir), current.sha256);
  const metadata = () => { owner.metadata(); assertPublication(journal); };
  metadata(); finalTail(checkpoint);
  const result = Object.freeze({ cleanupHash: owner.factHash, journalHash: current.sha256, claimHash: owner.fact.claimHash,
    executionId: owner.fact.executionId, claimRetained: false as const, resourceCleanup: "verified" as const,
    mediaSelected: false as const, openingApproved: false as const, deliveryApproved: false as const });
  finalCommitMetadata.set(result, metadata); return result;
}

/** Actual post-commit evidence only; callers separately charge this finite sweep to the original remainder. */
export function assertCommittedSourceColorCleanupMetadata(value: ReturnType<typeof commitRetiredSourceColorCleanup>): void {
  const check = finalCommitMetadata.get(value);
  if (!check) throw new Error("Final source color cleanup metadata requires its actual original commit");
  check();
}
