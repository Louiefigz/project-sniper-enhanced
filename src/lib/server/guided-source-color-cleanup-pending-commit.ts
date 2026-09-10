/** First exact source-color cleanup CAS. Never unlinks, clears a claim, releases a lease or selects media. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { autoEditJobPath } from "./auto-edit-job-persistence";
import { commitGuidedJob } from "./guided-cut-v2";
import { writeGuidedObject, strictGuidedTimestamp } from "./guided-cut-v2-store";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { retainGenerationClockObservation } from "./generation-clock-watermark";
import { buildSourceColorCleanupPendingJob } from "./guided-source-color-cleanup-pending-job";
import { assertRecordedSourceColorCleanupAttempt, heldRecordedSourceColorCleanupAttempt,
  remainingRecordedSourceColorCleanupAttempt, assertRecordedSourceColorCleanupMetadata,
  type RecordedSourceColorCleanupAttempt } from "./guided-source-color-cleanup-attempt";
import { fileIdentity, directoryIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { heldAdoptedSourceColorCleanup, remainingAdoptedSourceColorCleanup, assertAdoptedSourceColorCleanupMetadata,
  type AdoptedSourceColorCleanupCompletion } from "./guided-source-color-cleanup-adoption";

interface Publication { path: string; sha256: string; identity: bigint[]; parent: bigint[] }
interface FinalCheckpoint { started: number; remaining: number; observedAt: string }
type Completion = RecordedSourceColorCleanupAttempt | AdoptedSourceColorCleanupCompletion;
/** Code-only faults cannot replace the actual recording, clock, writes, CAS or success. */
export interface PreparedSourceColorCleanupFaults {
  beforeCasGuard?: (invocation: number) => void;
  afterCas?: () => void;
}

export function capturePublication(file: string, sha256: string): Publication {
  const record = { path: file, sha256, identity: fileIdentity(file), parent: directoryIdentity(path.dirname(file)) };
  assertPublication(record); return record;
}
export function assertPublication(record: Publication): void {
  if (!isDeepStrictEqual(directoryIdentity(path.dirname(record.path)), record.parent)
      || !isDeepStrictEqual(fileIdentity(record.path), record.identity)
      || readCutPreviewObject(record.path).sha256 !== record.sha256
      || !isDeepStrictEqual(fileIdentity(record.path), record.identity)) {
    throw new Error("Source color cleanup prepared publication original bytes or identity changed");
  }
}

function heldCompletion(recorded: Completion) {
  return recorded.scope === "completed-history-adoption-not-native-replay-retirement-or-approval"
    ? heldAdoptedSourceColorCleanup(recorded) : heldRecordedSourceColorCleanupAttempt(recorded);
}
function remainingCompletion(recorded: Completion): number {
  return recorded.scope === "completed-history-adoption-not-native-replay-retirement-or-approval"
    ? remainingAdoptedSourceColorCleanup(recorded) : remainingRecordedSourceColorCleanupAttempt(recorded);
}
function assertCompletion(recorded: Completion): void {
  if (recorded.scope === "completed-history-adoption-not-native-replay-retirement-or-approval") {
    heldAdoptedSourceColorCleanup(recorded); return;
  }
  assertRecordedSourceColorCleanupAttempt(recorded);
}
function completionMetadata(recorded: Completion): void {
  if (recorded.scope === "completed-history-adoption-not-native-replay-retirement-or-approval") {
    assertAdoptedSourceColorCleanupMetadata(recorded); return;
  }
  assertRecordedSourceColorCleanupMetadata(recorded);
}

function commitLifetime(recorded: Completion) {
  const held = heldCompletion(recorded), dir = held.job.ctx.dir;
  const journal = capturePublication(autoEditJobPath(dir), held.sha256);
  const publications: Publication[] = [journal];
  const guard = () => {
    const started = performance.now(), remaining = remainingCompletion(recorded);
    for (const publication of publications) assertPublication(publication);
    const now = strictGuidedTimestamp(new Date().toISOString());
    if (now < recorded.fact.createdAt) throw new Error("Source color cleanup wall clock moved backwards before its prepared CAS");
    const elapsed = performance.now() - started;
    if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= remaining) throw new Error("Source color cleanup prepared CAS exhausted its original protected remainder");
    return { started: performance.now(), remaining: remaining - elapsed, observedAt: now };
  };
  return { held, dir, guard, publications };
}

function assertCommittedTail(checkpoint: FinalCheckpoint | undefined): void {
  if (!checkpoint) throw new Error("Source color cleanup CAS never checked its original live remainder");
  const elapsed = performance.now() - checkpoint.started;
  if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= checkpoint.remaining
      || new Date().toISOString() < checkpoint.observedAt) {
    throw new Error("Source color cleanup CAS tail expired or clock moved backwards; pending evidence may be committed and must be retained");
  }
}

function publishPreparation(recorded: Completion, owner: ReturnType<typeof commitLifetime>): void {
  const { dir, held, guard, publications } = owner;
  guard();
  const resultHash = writeGuidedObject(dir, recorded.evidence.result);
  if (resultHash !== recorded.fact.cleanupResultHash) throw new Error("Source color cleanup stored result differs from actual owned output");
  publications.push(capturePublication(path.join(dir, ".sniper-authority-v1/objects/receipts", `${resultHash}.json`), resultHash));
  guard();
  const factHash = writeGuidedObject(dir, recorded.fact);
  if (factHash !== recorded.factHash) throw new Error("Source color cleanup prepared fact changed before publication");
  publications.push(capturePublication(path.join(dir, ".sniper-authority-v1/objects/receipts", `${factHash}.json`), factHash));
  guard(); saveHumanCutJobSnapshot(dir, held);
  publications.push(capturePublication(path.join(dir, "human-cut-job-snapshots", `${held.sha256}.json`), held.sha256));
  guard();
}

/** Only an actual live recording or separately authenticated historical adoption capability is accepted.
 * Failures retain all published evidence and the claim. The caller must not mark a committed attempt failed.
 */
export function commitPreparedSourceColorCleanup(recorded: Completion, testOnly?: PreparedSourceColorCleanupFaults) {
  const faults = { ...testOnly };
  const owner = commitLifetime(recorded), { held, dir } = owner;
  const job = buildSourceColorCleanupPendingJob(held, recorded.fact);
  publishPreparation(recorded, owner);
  let checkpoint: FinalCheckpoint | undefined, invocation = 0;
  const guard = () => {
    faults.beforeCasGuard?.(++invocation);
    const observedAt = new Date().toISOString();
    retainGenerationClockObservation({ dir, origin: { clockHash: held.claim.clockHash, startedAt: held.claim.generationStartedAt },
      executionId: held.claim.executionId, observedAt }, () => assertCompletion(recorded));
    checkpoint = owner.guard();
  };
  commitGuidedJob({ beforeHash: held.sha256, job, guard });
  faults.afterCas?.();
  const current = observeHumanCutJob(dir);
  if (canonicalJsonSha256(current.job) !== canonicalJsonSha256(job)) throw new Error("Source color cleanup pending journal changed after its prepared CAS; retain pending evidence");
  completionMetadata(recorded);
  for (const publication of owner.publications.slice(1)) assertPublication(publication);
  assertCommittedTail(checkpoint);
  return Object.freeze({ phase: "awaiting-retirement" as const, pendingJournalHash: current.sha256,
    preparedFactHash: recorded.factHash, claimHash: held.claimHash, executionId: held.claim.executionId,
    claimRetained: true as const, retirementObserved: false as const, mediaSelected: false as const,
    openingApproved: false as const, deliveryApproved: false as const });
}
