/** Actual cleanup attempt recording. The caller still owns both leases and every journal CAS. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { parsePreparedSourceColorCleanupFact } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";
import { assertSourceColorCleanupReservationMetadata, type HeldSourceColorCleanupReservation } from "./guided-source-color-cleanup-hold";
import { writeSourceColorReservationArchive } from "./guided-source-color-reservation-archive";
import { runSourceColorCleanupProcess } from "./guided-source-color-cleanup-process";
import { assertSourceColorCleanupAttemptMetadata, readSourceColorCleanupAttempt } from "./guided-source-color-cleanup-attempt-read";
import { createOpeningRecord } from "./guided-opening-process-activation";
import { readStoppedOpeningProcess, type HeldOpeningClaim } from "./guided-opening-process";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { strictGuidedTimestamp } from "./guided-cut-v2-store";
import { freezeSourceColorValue, snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { CleanupPreparationPublication, type SourceColorCleanupPreparationRef } from "./guided-source-color-cleanup-preparation";

export interface SourceColorCleanupClock {
  receivedAt: string;
  elapsedMs: () => number;
  remainingMs: () => number;
}
export interface SourceColorCleanupAttemptInput {
  held: HeldOpeningClaim;
  reservation: HeldSourceColorCleanupReservation;
  /** Existing new-only private attempt directory, created under the caller's original leases. */
  attemptId: string;
  guard: () => void;
  clock: SourceColorCleanupClock;
}
/** Existing actual process/readers by default; code-only TEST seams cannot be supplied as JSON. */
export const sourceColorCleanupAttemptDependencies = {
  stopped: readStoppedOpeningProcess, run: runSourceColorCleanupProcess, read: readSourceColorCleanupAttempt,
};
type Dependencies = typeof sourceColorCleanupAttemptDependencies;
const recordedAttempts = new WeakMap<RecordedSourceColorCleanupAttempt, { check: () => number; metadata: () => void; held: HeldOpeningClaim }>();
export interface RecordedSourceColorCleanupAttempt {
  readonly fact: ReturnType<typeof parsePreparedSourceColorCleanupFact>;
  readonly factHash: string;
  readonly evidence: ReturnType<typeof readSourceColorCleanupAttempt>;
  readonly preparedRef: Readonly<SourceColorCleanupPreparationRef>;
  readonly scope: "owned-cleanup-attempt-not-journal-commit-retirement-or-approval";
}

function holdWriter(input: SourceColorCleanupAttemptInput) {
  const original = { ...input, elapsed: input.clock.elapsedMs, remaining: input.clock.remainingMs };
  const fixed = snapshotSourceColorMetadata({ held: input.held, reference: input.reservation.reference, attemptId: input.attemptId, receivedAt: input.clock.receivedAt });
  strictGuidedTimestamp(fixed.receivedAt);
  const preparation = new CleanupPreparationPublication({ held: input.held, attemptId: input.attemptId });
  const unchanged = () => {
    if (input.held !== original.held || input.reservation !== original.reservation || input.guard !== original.guard || input.clock !== original.clock
        || input.clock.elapsedMs !== original.elapsed || input.clock.remainingMs !== original.remaining
        || !isDeepStrictEqual({ held: input.held, reference: input.reservation.reference, attemptId: input.attemptId, receivedAt: input.clock.receivedAt }, fixed)) {
      throw new Error("Source color cleanup attempt original caller metadata changed");
    }
  };
  const guard = () => {
    preparation.assertMetadata();
    unchanged(); original.reservation.assertCurrent(); unchanged(); original.guard(); unchanged();
    assertSourceColorCleanupReservationMetadata(original.reservation); preparation.assertMetadata(); unchanged();
  };
  const remainingMs = () => {
    unchanged(); const started = performance.now(), remaining = original.remaining.call(original.clock); guard();
    const elapsed = performance.now() - started, bounded = Math.floor(remaining - elapsed);
    if (!Number.isFinite(remaining) || remaining > 300_000 || !Number.isFinite(elapsed) || elapsed < 0 || bounded <= 0) {
      throw new Error("Source color cleanup attempt exhausted its original protected remainder");
    }
    return bounded;
  };
  const elapsedMs = () => {
    unchanged(); const elapsed = original.elapsed.call(original.clock); unchanged();
    if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed > 300_000) throw new Error("Source color cleanup attempt elapsed clock is invalid");
    return elapsed;
  };
  return { original, fixed, unchanged, guard, remainingMs, elapsedMs, preparation };
}

interface StoppedSnapshot {
  observed: ReturnType<typeof readStoppedOpeningProcess>;
  fixed: ReturnType<typeof readStoppedOpeningProcess>;
}
function assertStoppedSnapshot(stopped: StoppedSnapshot): void {
  if (!isDeepStrictEqual(stopped.observed, stopped.fixed)) throw new Error("Source color cleanup attempt original stopped observation changed");
}

function startAttempt(owner: ReturnType<typeof holdWriter>, snapshot: StoppedSnapshot) {
  const { original: input, fixed } = owner, stopped = snapshot.fixed; owner.remainingMs(); assertStoppedSnapshot(snapshot);
  if (!stopped.sourceColor || !isDeepStrictEqual(stopped.sourceColor, fixed.reference)) throw new Error("Source color cleanup start lost its original media reference");
  const archive = writeSourceColorReservationArchive({ held: input.held, reservation: input.reservation,
    attemptId: input.attemptId, guard: owner.guard, remainingMs: owner.remainingMs });
  assertStoppedSnapshot(snapshot);
  const directory = path.dirname(archive.archive.path);
  const start = createOpeningRecord(path.join(directory, "start.json"), { schemaVersion: 2, kind: "guided-opening-cleanup-start",
    cleanupAttemptId: input.attemptId, claimHash: input.held.claimHash, processOutcomeSha256: stopped.receiptSha256,
    beforeJournalHash: input.held.sha256, clockHash: input.held.claim.clockHash, generationStartedAt: input.held.claim.generationStartedAt,
    receivedAt: fixed.receivedAt, startedAt: new Date().toISOString(), budgetScope: "separate-protected-cleanup-not-render-allowance",
    sourceColor: fixed.reference, archive: archive.archive });
  owner.remainingMs(); assertStoppedSnapshot(snapshot); return { start, archive, directory };
}

function recordOutput(owner: ReturnType<typeof holdWriter>, attempt: ReturnType<typeof startAttempt>, result: Awaited<ReturnType<typeof runSourceColorCleanupProcess>>) {
  const elapsedMs = owner.elapsedMs(); owner.remainingMs();
  if (result.result.elapsedMs > elapsedMs + 1) throw new Error("Source color cleanup child timing exceeds its original enclosing attempt");
  return createOpeningRecord(path.join(attempt.directory, "output.json"), { schemaVersion: 2, kind: "guided-opening-cleanup-owned-output",
    stdout: result.stdout, stderr: result.stderr, mediaProcessGroupStopped: true, cleanupProcessGroupStopped: true,
    cleanupNestedOwnership: "resolved-by-normal-return", observedAt: new Date().toISOString(), elapsedMs,
    invocationSha256: result.invocation.sha256, ledger: result.ledger });
}

function preparedFact(owner: ReturnType<typeof holdWriter>, attempt: ReturnType<typeof startAttempt>,
  completed: { process: Awaited<ReturnType<typeof runSourceColorCleanupProcess>>; output: ReturnType<typeof recordOutput> }) {
  const { original: input } = owner, { process, output } = completed;
  return parsePreparedSourceColorCleanupFact({ schemaVersion: 2, kind: "guided-opening-source-color-cleanup-prepared",
    scope: "exact-owned-resource-cleanup-awaiting-reservation-retirement-not-approval", phase: "awaiting-retirement", claimRetained: true,
    claimHash: input.held.claimHash, executionId: input.held.claim.executionId, cleanupAttemptId: input.attemptId, beforeJournalHash: input.held.sha256,
    processOutcomeSha256: process.processOutcomeSha256, cleanupStartSha256: attempt.start.sha256, cleanupOutputSha256: output.sha256,
    cleanupResultHash: canonicalJsonSha256(process.result), cleanupInvocationSha256: process.invocation.sha256,
    reservation: input.reservation.reference.reservation, archive: attempt.archive.archive, sourceColorHash: input.reservation.reference.sourceColorHash,
    clockHash: input.held.claim.clockHash, generationStartedAt: input.held.claim.generationStartedAt, createdAt: new Date().toISOString(),
    mediaSelected: false, openingApproved: false, deliveryApproved: false });
}

/** Record actual returned evidence, then independently read it back. No CAS, unlink or lease release. */
export async function recordSourceColorCleanupAttempt(input: SourceColorCleanupAttemptInput,
  dependencies: Dependencies = sourceColorCleanupAttemptDependencies): Promise<RecordedSourceColorCleanupAttempt> {
  const controls = { ...dependencies }, owner = holdWriter(input); owner.remainingMs();
  const observed = controls.stopped(owner.original.held), stopped = { observed, fixed: freezeSourceColorValue(structuredClone(observed)) };
  owner.unchanged(); const attempt = startAttempt(owner, stopped);
  const process = await controls.run({ held: owner.original.held, reservation: owner.original.reservation,
    attemptId: owner.original.attemptId, guard: owner.guard, remainingMs: owner.remainingMs });
  owner.unchanged(); const output = recordOutput(owner, attempt, process);
  const fact = freezeSourceColorValue(preparedFact(owner, attempt, { process, output }));
  const evidence = controls.read({ held: owner.original.held, fact, guard: owner.guard, remainingMs: owner.remainingMs });
  owner.remainingMs(); assertSourceColorCleanupAttemptMetadata(evidence);
  const preparedRef = owner.preparation.publish(fact);
  const recorded = Object.freeze({ fact, factHash: canonicalJsonSha256(fact), evidence, preparedRef,
    scope: "owned-cleanup-attempt-not-journal-commit-retirement-or-approval" as const });
  const metadata = () => {
    owner.unchanged(); assertSourceColorCleanupReservationMetadata(owner.original.reservation);
    assertSourceColorCleanupAttemptMetadata(evidence); owner.preparation.assertMetadata(); owner.unchanged();
  };
  const started = performance.now(), remaining = owner.remainingMs(); metadata();
  const tail = performance.now() - started;
  if (!Number.isFinite(tail) || tail < 0 || tail >= remaining) throw new Error("Cleanup preparation publication exhausted its original protected remainder");
  recordedAttempts.set(recorded, { held: owner.original.held, metadata, check: () => {
    const started = performance.now(), remaining = owner.remainingMs();
    evidence.assertCurrent(); metadata();
    const elapsed = performance.now() - started, bounded = Math.floor(remaining - elapsed);
    if (!Number.isFinite(elapsed) || elapsed < 0 || bounded <= 0) throw new Error("Source color cleanup recording exhausted its original protected remainder");
    return bounded;
  } });
  return recorded;
}

/** Only the actual live recording can enter its first journal CAS; JSON/rebuilt data is not a live completion.
 * A later historical recovery requires its own explicit authenticated journal edge.
 */
export function assertRecordedSourceColorCleanupAttempt(recorded: RecordedSourceColorCleanupAttempt): void {
  heldRecordedSourceColorCleanupAttempt(recorded);
}

/** Retrieve only the original recording's held claim, never a caller-selected replacement journal. */
export function heldRecordedSourceColorCleanupAttempt(recorded: RecordedSourceColorCleanupAttempt): HeldOpeningClaim {
  const original = recordedAttempts.get(recorded);
  if (!original) throw new Error("Source color cleanup commit requires the actual live recorded attempt");
  original.check(); return original.held;
}

/** Charge a finite callback-free caller sweep to the same live attempt, never a newly started allowance. */
export function remainingRecordedSourceColorCleanupAttempt(recorded: RecordedSourceColorCleanupAttempt): number {
  const original = recordedAttempts.get(recorded);
  if (!original) throw new Error("Source color cleanup commit requires the actual live recorded attempt");
  return original.check();
}

/** Original evidence only after first CAS: no old-journal callback, lease, time or retirement authority. */
export function assertRecordedSourceColorCleanupMetadata(recorded: RecordedSourceColorCleanupAttempt): void {
  const original = recordedAttempts.get(recorded);
  if (!original) throw new Error("Source color cleanup metadata requires the actual live recorded attempt");
  original.metadata();
}
