import path from "node:path";
import { randomUUID } from "node:crypto";
import { parseOpeningCleanupStdout, type OpeningCleanupResultV1 } from "@/lib/producer/contracts/guided-opening-cleanup-v1";
import { parsePreparedSourceColorCleanupFact } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";
import { sha256, stringValue } from "@/lib/producer/contracts/validation";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { readGuidedOpeningExecutionClaim } from "./guided-opening-claim";
import { openingChildTools, openingOwnershipGuard, invokeOpeningChild, ownershipUnresolved, readStoppedOpeningProcess,
  type HeldOpeningClaim, type StoppedOwnership } from "./guided-opening-process";
import { acquireGuidedMutation, writeGuidedObject, readGuidedObject } from "./guided-cut-v2-store";
import { humanCutDirectory, createHumanCutIndex, saveHumanCutJobSnapshot, observeHumanCutJob } from "./human-cut-acceptance-store";
import { commitGuidedJob } from "./guided-cut-v2";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { retainGenerationClockObservation } from "./generation-clock-watermark";
import { timedStage } from "./stage-timing";
import { withStageTimingContext } from "./stage-timing-context";
import type { ProjectMutationLease } from "./project-mutation-lease";
import { createOpeningRecord, assertOpeningRecord, assertOpeningFailureAbsent, type HeldOpeningRecord } from "./guided-opening-process-activation";
import { reconcilePendingSourceColorCleanup } from "./guided-source-color-cleanup-recovery";

interface CleanupInput { dir: unknown; expectedToken: unknown; expectedJournalHash: unknown; claimHash: unknown }

/** Internal TEST-only faults after real owned cleanup. No child, stop, output or success override. */
export interface OpeningCleanupTestFaults {
  afterOwnedCleanup?: (records: { attemptId: string; directory: string; start: HeldOpeningRecord; output: HeldOpeningRecord }) => void;
  beforeFinalCas?: (observation: { invocation: number; actualNow: string; createdAt: string }) => string | void;
}

/** Closed result identity check; actual child provenance and stopped groups are separate requirements. */
export function assertOpeningCleanupIdentity(result: OpeningCleanupResultV1, held: Pick<HeldOpeningClaim, "claim" | "claimHash" | "claimPath" | "claimSha256">) {
  if (result.claimPath !== held.claimPath || result.claimSha256 !== held.claimSha256 || result.claimSha256 !== held.claimHash
      || result.inputSha256 !== held.claim.inputSha256 || result.outputRoot !== held.claim.outputRoot
      || result.executionId !== held.claim.executionId
      || canonicalJsonSha256(result.graphics.map((row) => row.order)) !== canonicalJsonSha256(held.claim.selectedGraphicOrders)) {
    throw new Error("Opening cleanup completion does not bind its exact held claim/input/selected resources");
  }
}

/** Do not let an internal V2 claim fall through to graphics-only legacy cleanup. */
export function assertLegacyOpeningCleanup(held: Pick<HeldOpeningClaim, "submission">): void {
  if (held.submission.schemaVersion !== 1) {
    throw new Error("Source-color cleanup commit and retirement are not connected yet; retain the full claim without graphics-only cleanup");
  }
}

function protectedClock() {
  const receivedAt = new Date().toISOString(), started = performance.now();
  return { receivedAt, elapsedMs: () => performance.now() - started, remainingMs: () => {
    const remaining = Math.floor(300_000 - (performance.now() - started));
    if (remaining <= 0) throw new Error("Opening protected cleanup deadline exceeded; original render allowance is not renewed");
    return remaining;
  } };
}
/** Code-only request entry clock; a CLI may create it before reading its bounded request file. */
export { protectedClock as createOpeningProtectedCleanupClock };

function recordClock(held: HeldOpeningClaim, guard: () => void, observedAt = new Date().toISOString()): string | null {
  try {
    retainGenerationClockObservation({ dir: held.job.ctx.dir, origin: { clockHash: held.claim.clockHash, startedAt: held.claim.generationStartedAt },
      executionId: held.claim.executionId, observedAt }, guard);
    return null;
  } catch (error) { return String(error).slice(0, 2000); } // Cleanup may still remove exact owned resources; a bad clock forbids commit.
}

function cleanupAttempt(held: HeldOpeningClaim, clock: ReturnType<typeof protectedClock>) {
  const root = humanCutDirectory(path.dirname(held.claimPath), "cleanup-attempts"), id = randomUUID();
  const directory = humanCutDirectory(root, id), stopped = readStoppedOpeningProcess(held);
  const start = { schemaVersion: 1, kind: "guided-opening-cleanup-start", cleanupAttemptId: id,
    claimHash: held.claimHash, processOutcomeSha256: stopped.receiptSha256, beforeJournalHash: held.sha256,
    clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt,
    receivedAt: clock.receivedAt, startedAt: new Date().toISOString(), budgetScope: "separate-protected-cleanup-not-render-allowance" };
  const startRecord = createOpeningRecord(path.join(directory, "start.json"), start);
  return { id, directory, start, stopped, startRecord };
}

export type StoppedForPolicy = StoppedOwnership;

/** Ownership stays unresolved after a forced OUTER stop (nested sessions unobserved by the group stop), whenever a pid
 * the worker itself recorded (headless/process_runner.py ledger) is still alive with the same program, and whenever
 * an intent to spawn was recorded without its pid. */
export function retainsClaimAfterStop(stopped: StoppedForPolicy): boolean {
  return ownershipUnresolved(stopped);
}

/** A later live/unknown observation may not clear a claim based on an earlier resolved observation. */
export function assertCleanupOwnershipFresh(initial: StoppedForPolicy, current: StoppedForPolicy): void {
  if (!retainsClaimAfterStop(initial) && retainsClaimAfterStop(current)) {
    throw new Error("Opening nested ownership became unresolved before cleanup CAS; retain the claim");
  }
}

/** Pure pointer policy: exact Docker cleanup never clears ownership while outer/nested ownership is unresolved. */
export function cleanupPointerAfterStop(pointer: NonNullable<HeldOpeningClaim["job"]["guidedHandoffV2"]>, cleanupHash: string,
  stopped: StoppedForPolicy) {
  const retained = retainsClaimAfterStop(stopped);
  const { openingExecutionClaimHash: claim, openingProcessOutcomeHash: outcome, ...rest } = pointer;
  const next: NonNullable<HeldOpeningClaim["job"]["guidedHandoffV2"]> = retained
    ? { ...rest, openingExecutionClaimHash: claim, openingProcessOutcomeHash: outcome, openingCleanupHash: cleanupHash }
    : { ...rest, openingCleanupHash: cleanupHash };
  return { claimRetained: retained, pointer: next };
}

function commitCleanup(input: { held: HeldOpeningClaim; attempt: ReturnType<typeof cleanupAttempt>;
  result: OpeningCleanupResultV1; outputRecord: HeldOpeningRecord; clock: ReturnType<typeof protectedClock>; guard: () => void;
  testOnly?: OpeningCleanupTestFaults }) {
  const { held, attempt, result, outputRecord, clock, guard } = input, dir = held.job.ctx.dir;
  guard(); clock.remainingMs();
  const previousStop = readStoppedOpeningProcess(held);
  if (previousStop.receiptSha256 !== attempt.stopped.receiptSha256) throw new Error("Opening stopped-process evidence changed during cleanup");
  assertCleanupOwnershipFresh(attempt.stopped, previousStop);
  const createdAt = new Date().toISOString(), receipt = { schemaVersion: 1, kind: "guided-opening-cleanup-commit",
    scope: "exact-owned-resource-cleanup-not-opening-or-delivery-approval", claimHash: held.claimHash,
    beforeJournalHash: held.sha256, cleanupAttemptId: attempt.id, processOutcomeSha256: attempt.stopped.receiptSha256,
    cleanupStartSha256: attempt.startRecord.sha256,
    cleanupOutputSha256: outputRecord.sha256,
    cleanupResultHash: writeGuidedObject(dir, result), clockHash: held.claim.clockHash,
    generationStartedAt: held.claim.generationStartedAt, createdAt, claimRetained: retainsClaimAfterStop(attempt.stopped),
    openingApproved: false, deliveryApproved: false };
  const hash = writeGuidedObject(dir, receipt); saveHumanCutJobSnapshot(dir, held);
  const policy = cleanupPointerAfterStop(held.job.guidedHandoffV2!, hash, attempt.stopped);
  const job = held.job; let invocation = 0;
  const commitGuard = () => {
    const actualNow = new Date().toISOString();
    const now = input.testOnly?.beforeFinalCas?.({ invocation: ++invocation, actualNow, createdAt }) ?? actualNow;
    if (!Number.isFinite(Date.parse(now)) || new Date(now).toISOString() !== now || now > actualNow) throw new Error("Cleanup TEST clock may only inject a canonical backward observation");
    guard(); clock.remainingMs(); assertOpeningRecord(attempt.startRecord); assertOpeningRecord(outputRecord);
    assertOpeningFailureAbsent(path.join(attempt.directory, "failure.json"));
    const stopped = readStoppedOpeningProcess(held);
    if (stopped.receiptSha256 !== attempt.stopped.receiptSha256) throw new Error("Opening stopped outcome changed before cleanup CAS");
    assertCleanupOwnershipFresh(attempt.stopped, stopped);
    if (now < createdAt || createdAt < String(outputRecord.value.observedAt)) throw new Error("Opening cleanup wall clock moved backwards before CAS");
    const clockError = recordClock(held, guard, now); if (clockError) throw new Error(clockError);
  };
  commitGuidedJob({ beforeHash: held.sha256, guard: commitGuard, job: { ...job, updatedAt: createdAt,
    guidedHandoffV2: policy.pointer, message: policy.claimRetained
      ? (attempt.stopped.receipt.forcedStop === true
        ? "Exact private opening Docker resources were reconciled, but the outer worker was force-stopped; nested local probe ownership is unresolved, so this claim is retained and nothing is selectable."
        : "Exact private opening Docker resources were reconciled, but nested local process ownership is live, unknown or incomplete; this claim is retained and nothing is selectable.")
      : "Exact private opening resources were reconciled. No opening, body or final is approved.",
    nextEventId: job.nextEventId + 1, events: [...job.events, { id: job.nextEventId, at: createdAt,
      payload: { event: "opening_execution_cleanup_verified", executionId: held.claim.executionId, cleanupHash: hash,
        claimRetained: policy.claimRetained, clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt,
        openingApproved: false, deliveryApproved: false } }].slice(-256) } });
  return { cleanupHash: hash, claimHash: held.claimHash, executionId: held.claim.executionId, claimRetained: policy.claimRetained,
    resourceCleanup: "verified" as const, mediaSelected: false as const, openingApproved: false as const, deliveryApproved: false as const };
}

async function underLease(held: HeldOpeningClaim, lease: ProjectMutationLease, clock: ReturnType<typeof protectedClock>, testOnly?: OpeningCleanupTestFaults) {
  assertLegacyOpeningCleanup(held);
  const guard = openingOwnershipGuard(held, lease); guard(); clock.remainingMs();
  const attempt = cleanupAttempt(held, clock), beforeClockError = recordClock(held, guard);
  try {
    const tools = openingChildTools(held, "cleanup"); guard(); clock.remainingMs();
    const output = await timedStage(held.job.ctx.dir, "guided_opening_protected_cleanup", async () => {
      const value = await invokeOpeningChild({ held, tools, kind: "cleanup", remainingMs: clock.remainingMs });
      const record = createOpeningRecord(path.join(attempt.directory, "output.json"), { schemaVersion: 1, kind: "guided-opening-cleanup-owned-output", ...value,
        mediaProcessGroupStopped: true, cleanupProcessGroupStopped: true, observedAt: new Date().toISOString(), elapsedMs: clock.elapsedMs() });
      const result = parseOpeningCleanupStdout(value.stdout); assertOpeningCleanupIdentity(result, held);
      if (canonicalJsonSha256(openingChildTools(held, "cleanup")) !== canonicalJsonSha256(tools)) throw new Error("Opening cleanup executable closure changed");
      guard(); clock.remainingMs(); return { ...value, record };
    });
    const afterClockError = recordClock(held, guard);
    if (beforeClockError || afterClockError) throw new Error(`Opening resources returned clean but timing authority is invalid; keep claim: ${beforeClockError ?? afterClockError}`);
    testOnly?.afterOwnedCleanup?.({ attemptId: attempt.id, directory: attempt.directory, start: attempt.startRecord, output: output.record });
    return commitCleanup({ held, attempt, result: parseOpeningCleanupStdout(output.stdout), outputRecord: output.record, clock, guard, testOnly });
  } catch (error) {
    createHumanCutIndex(path.join(attempt.directory, "failure.json"), { schemaVersion: 1, kind: "guided-opening-cleanup-failure",
      claimHash: held.claimHash, cleanupAttemptId: attempt.id, observedAt: new Date().toISOString(), elapsedMs: clock.elapsedMs(),
      clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt,
      error: String(error).slice(0, 4000), clockError: recordClock(held, guard),
      ...(error instanceof CutPreviewProcessError ? error.details : {}), claimCleared: false, openingApproved: false });
    throw error;
  }
}

/** Same live project lease across media and cleanup; the supplied observation is re-read, never trusted as authority. */
export async function reconcileClaimedOpeningUnderLease(input: { dir: string; lease: ProjectMutationLease; expectedClaimHash: string }, testOnly?: OpeningCleanupTestFaults) {
  const clock = protectedClock(), held = readGuidedOpeningExecutionClaim(input.dir);
  if (held.claimHash !== sha256(input.expectedClaimHash, "expectedClaimHash")) throw new Error("Opening cleanup names another current claim");
  readStoppedOpeningProcess(held);
  return withStageTimingContext({ runId: held.job.artifactToken ?? held.job.token,
    attemptId: `opening-cleanup:${held.claim.executionId}`, attemptNo: held.job.attempts }, () => underLease(held, input.lease, clock, testOnly));
}

/** Dedicated recovery only. No caller stop boolean, source/media work, generic mutation bypass or automatic render retry. */
export async function reconcileGuidedOpeningExecution(input: CleanupInput, clock = protectedClock()) {
  const dir = canonicalProducerDir(input.dir), token = stringValue(input.expectedToken, "expectedToken", 200);
  const before = sha256(input.expectedJournalHash, "expectedJournalHash"), claimHash = sha256(input.claimHash, "claimHash");
  const checkpoint = readOpeningRecoveryCheckpoint(dir);
  if (checkpoint.kind === "pending-retirement") {
    return reconcilePendingSourceColorCleanup({ dir, expectedToken: token, expectedJournalHash: before, expectedClaimHash: claimHash, clock });
  }
  const observed = checkpoint.held;
  if (observed.sha256 !== before || observed.job.token !== token || observed.claimHash !== claimHash) throw new Error("Opening cleanup request is stale");
  readStoppedOpeningProcess(observed); // Missing durable stop is an explicit unsupported recovery, before any Docker action.
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "reconcile-guided-opening", expectedStatus: "treatment_admitted",
    expectedToken: token, expectedJournalHash: before });
  try {
    const held = readGuidedOpeningExecutionClaim(dir);
    if (held.sha256 !== before || held.claimHash !== claimHash) throw new Error("Opening ownership changed while acquiring cleanup lease");
    return await withStageTimingContext({ runId: held.job.artifactToken ?? held.job.token,
      attemptId: `opening-cleanup:${held.claim.executionId}`, attemptNo: held.job.attempts }, () => underLease(held, lease, clock));
  } finally { lease.release(); }
}

/** Preserve ordinary current-claim authority first; only an exact closed prepared fact selects the distinct reader.
 * A failed generic claim read never becomes cleanup success. The retirement service still authenticates the
 * entire pending journal/retained claim/actual attempt under the unchanged checkpoint lease policy.
 */
function readOpeningRecoveryCheckpoint(dir: string) {
  try { return { kind: "current-claim" as const, held: readGuidedOpeningExecutionClaim(dir) }; }
  catch (claimError) {
    const observed = observeHumanCutJob(dir), hash = observed.job.guidedHandoffV2?.openingCleanupHash;
    if (!hash) throw claimError;
    const fact = readGuidedObject(dir, hash);
    if (fact.schemaVersion !== 2 || fact.kind !== "guided-opening-source-color-cleanup-prepared") throw claimError;
    parsePreparedSourceColorCleanupFact(fact);
    return { kind: "pending-retirement" as const };
  }
}
