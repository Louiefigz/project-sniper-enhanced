import { isDeepStrictEqual } from "node:util";
import { sha256, uuid } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { humanCutDirectory } from "./human-cut-acceptance-store";
import { readGenerationClockHistory, publishGenerationClockWatermark } from "./generation-clock-history";
import { startProposalDeadline, type DeadlineClocks, type GenerationClockOrigin } from "./generation-deadline";
import type { GenerationCheckpoint } from "./generation-attempt-clock";

const LIMIT = 512;
export interface GenerationClockGuardInput {
  dir: string; origin: GenerationClockOrigin; executionId: string; guard: () => void;
}

function stamp(value: unknown): string {
  if (typeof value !== "string" || !Number.isSafeInteger(Date.parse(value))
      || new Date(value).toISOString() !== value) throw new Error("Generation clock observation is malformed");
  return value;
}

/** Versioned scheduling state, not an immutable event per millisecond check.
 * Preserve all old observations; advance only this execution's monotone V2
 * watermark under the actual caller lease. No skipped check or renewed budget.
 */
export function retainGenerationClockObservation(input: {
  dir: string; origin: GenerationClockOrigin; executionId: string; observedAt: string;
}, guard: () => void): void {
  const original = structuredClone(input), originReference = input.origin;
  const unchanged = () => {
    if (input.origin !== originReference || !isDeepStrictEqual(input, original)) throw new Error("Generation clock original input changed");
  };
  const checkedGuard = () => { unchanged(); guard(); unchanged(); };
  checkedGuard();
  const origin = { clockHash: sha256(input.origin.clockHash, "clockHash"), startedAt: stamp(input.origin.startedAt) };
  const executionId = uuid(input.executionId, "executionId"), observedAt = stamp(input.observedAt);
  if (observedAt < origin.startedAt) throw new Error("Generation budget clock-invalid before its original request");
  const root = humanCutDirectory(input.dir, "generation-clock-observations");
  const directory = humanCutDirectory(root, origin.clockHash), history = readGenerationClockHistory(directory, origin);
  if (observedAt < history.highWater) throw new Error("Generation budget clock-invalid: wall clock moved backwards across attempts");
  const value = { schemaVersion: 2, kind: "generation-wall-clock-watermark", clockHash: origin.clockHash,
    generationStartedAt: origin.startedAt, executionId, observedAt };
  if (history.observedAtForExecution(executionId) === observedAt) {
    checkedGuard(); history.assertCurrent(); return;
  }
  if (history.names.length === LIMIT && !history.names.includes(`${executionId}.json`)) {
    throw new Error("Generation clock history capacity exhausted; no automatic reset");
  }
  publishGenerationClockWatermark(history, { ...value, watermarkHash: canonicalJsonSha256(value) }, checkedGuard);
  unchanged();
}

/** Bound retries to durable wall-clock observations as well as one live process's
 * monotonic clock. This scheduling journal grants no approval or repair allowance. */
export function startGuardedProposalDeadline(input: GenerationClockGuardInput,
  clocks?: DeadlineClocks): ReturnType<typeof startProposalDeadline> {
  return guardGenerationAttempt(input, startProposalDeadline(input.origin, clocks));
}

/** Share the same original-clock history across stage kinds and failures. No
 * separate stage directory can reset a previously observed request wall time. */
export function guardGenerationAttempt<A, O extends { observedAt: string; state: string; remainingMs: number }>(
  input: GenerationClockGuardInput, budget: { admission: A; observe: (retain?: GenerationCheckpoint) => O; remainingMs: () => number },
) {
  const originalObserve = budget.observe, originalRemaining = budget.remainingMs;
  const originalClock = () => {
    if (budget.observe !== originalObserve || budget.remainingMs !== originalRemaining) {
      throw new Error("Generation budget original clock callbacks changed");
    }
  };
  const retain = (observedAt: string) => retainGenerationClockObservation({
    dir: input.dir, origin: input.origin, executionId: input.executionId, observedAt,
  }, input.guard);
  const observe = () => {
    originalClock(); const value = originalObserve.call(budget, retain);
    originalClock();
    return value;
  };
  return { ...budget, observe, remainingMs: () => {
    const value = observe();
    if (value.state !== "within-deadline") {
      throw new Error(`Proposal budget ${value.state}; preserve unresolved work and required quality checks`);
    }
    // observe(retain) already charges persistence with only the original monotonic clock.
    // Calling remainingMs here would sample a second, unpersisted wall observation.
    if (!Number.isSafeInteger(value.remainingMs) || value.remainingMs < 1) {
      throw new Error("Generation budget changed or expired during clock persistence");
    }
    return value.remainingMs;
  } };
}
