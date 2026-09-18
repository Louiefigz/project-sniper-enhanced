import { exactKeys, objectValue } from "@/lib/producer/contracts/validation";

export interface GenerationClockOrigin { clockHash: string; startedAt: string }
export interface DeadlineClocks { wall: () => number; monotonic: () => number }
export const SYSTEM_DEADLINE_CLOCKS: DeadlineClocks = { wall: () => Date.now(), monotonic: () => performance.now() };
export type GenerationCheckpoint = (observedAt: string) => void;

/** Hold original clock callbacks and charge one synchronous durable checkpoint.
 * A checkpoint samples wall only once. Its post-I/O monotonic cost remains an
 * elapsed floor, including when the sampled wall elapsed dominated monotonic.
 */
export function captureGenerationCheckpointClock(clocks: DeadlineClocks) {
  const originalWall = clocks.wall, originalMono = clocks.monotonic;
  let floor: { elapsedMs: number; mono: number } | undefined;
  let previousMono: number | undefined, invalid = false;
  const check = () => {
    if (clocks.wall !== originalWall || clocks.monotonic !== originalMono) {
      throw new Error("Generation budget original clock callbacks changed");
    }
  };
  const read = (callback: () => number) => {
    check(); const value = finiteDeadlineClock(callback.call(clocks)); check(); return value;
  };
  const readMono = () => {
    const value = read(originalMono);
    // Finally can observe rollback even when a failed checkpoint never returns to its owner.
    invalid ||= previousMono !== undefined && value < previousMono;
    previousMono = value; return value;
  };
  const elapsedFloor = (elapsedMs: number, mono: number) => floor
    ? Math.max(elapsedMs, floor.elapsedMs + Math.max(0, mono - floor.mono)) : elapsedMs;
  const sample = () => ({ wall: read(originalWall), mono: readMono(), invalid });
  const complete = (value: { elapsedMs: number; observedAt: string; mono: number }, retain?: GenerationCheckpoint) => {
    const elapsedMs = elapsedFloor(value.elapsedMs, value.mono);
    if (!retain) return { elapsedMs, mono: value.mono, invalid };
    try { check(); retain(value.observedAt); check(); }
    finally {
      const mono = readMono();
      floor = { elapsedMs: elapsedFloor(elapsedMs + Math.max(0, mono - value.mono), mono), mono };
    }
    return { ...floor, invalid };
  };
  return { sample, complete };
}

/** Accept exact UTC timestamps only; scheduling cannot infer missing clock data. */
export function deadlineTimestamp(value: string): number {
  const number = Date.parse(value);
  if (!Number.isSafeInteger(number) || new Date(number).toISOString() !== value) {
    throw new Error("Generation budget needs a canonical original timestamp");
  }
  return number;
}

export function finiteDeadlineClock(value: number): number {
  if (!Number.isFinite(value) || value < 0 || value > Number.MAX_SAFE_INTEGER) {
    throw new Error("Generation budget clock is unavailable");
  }
  return value;
}

/** Never give a child a fresh ceiling after its parent has spent the allowance. */
export function generationChildTimeout(ceilingMs: number, remaining?: () => number): number {
  const left = remaining?.() ?? ceilingMs;
  if (!Number.isSafeInteger(ceilingMs) || ceilingMs < 1 || !Number.isSafeInteger(left) || left < 1) {
    throw new Error("Generation child needs a positive bounded remaining deadline");
  }
  return Math.min(ceilingMs, left);
}

/** One live attempt, including preparation and persistence. Never restore its
 * monotonic origin across processes or grant approval when its deadline expires. */
export function startGenerationAttempt<A extends { clockHash: string; admitted: boolean }, K extends string>(input: {
  origin: GenerationClockOrigin; admit: (origin: GenerationClockOrigin, wall: number) => A; attemptMs: number; kind: K;
}, clocks: DeadlineClocks = SYSTEM_DEADLINE_CLOCKS) {
  const clock = captureGenerationCheckpointClock(clocks), initial = clock.sample();
  const admittedWall = initial.wall, beganMono = initial.mono;
  const admission = input.admit(input.origin, admittedWall);
  let previousWall = admittedWall, previousMono = beganMono, poisoned = false;
  function observe(retain?: GenerationCheckpoint) {
    const { wall, mono, invalid } = clock.sample();
    poisoned ||= invalid || wall < previousWall || mono < previousMono;
    previousWall = wall; previousMono = mono;
    const observedAt = new Date(wall).toISOString();
    const completed = clock.complete({ elapsedMs: Math.max(0, wall - admittedWall, mono - beganMono), observedAt, mono }, retain);
    poisoned ||= completed.invalid || completed.mono < previousMono;
    previousMono = completed.mono;
    const elapsedMs = completed.elapsedMs;
    const remainingMs = admission.admitted && !poisoned ? Math.max(0, Math.floor(input.attemptMs - elapsedMs)) : 0;
    return { schemaVersion: 1, kind: input.kind, clockHash: admission.clockHash,
      observedAt, elapsedMs, remainingMs,
      state: poisoned ? "clock-invalid" : !admission.admitted ? "not-admitted"
        : remainingMs <= 0 ? "deadline-exceeded" : "within-deadline" } as const;
  }
  function remainingMs(): number {
    const observed = observe();
    if (observed.state !== "within-deadline") {
      throw new Error(`Proposal budget ${observed.state}; preserve unresolved work and required quality checks`);
    }
    return observed.remainingMs;
  }
  return { admission, observe, remainingMs };
}

/** Check a retained precommit against its already reconstructed admission.
 * This is timing evidence, not proof that media or editorial review passed. */
export function assertGenerationPrecommit(value: unknown, input: {
  clockHash: string; observedAt: string; createdAt: string; deadlineAt: string; kind: string; attemptMs: number;
}): void {
  const check = objectValue(value, "proposal budget precommit");
  const keys = ["schemaVersion", "kind", "clockHash", "observedAt", "elapsedMs", "remainingMs", "state"];
  exactKeys(check, keys, keys, "proposal budget precommit");
  const at = deadlineTimestamp(String(check.observedAt)), elapsed = check.elapsedMs;
  if (check.schemaVersion !== 1 || check.kind !== input.kind || check.clockHash !== input.clockHash
      || check.state !== "within-deadline" || at < deadlineTimestamp(input.observedAt)
      || at > deadlineTimestamp(input.createdAt) || deadlineTimestamp(input.createdAt) >= deadlineTimestamp(input.deadlineAt)
      || typeof elapsed !== "number" || !Number.isFinite(elapsed) || elapsed < at - deadlineTimestamp(input.observedAt)
      || elapsed < 0 || elapsed >= input.attemptMs || check.remainingMs !== Math.floor(input.attemptMs - elapsed)) {
    throw new Error("Proposal budget precommit is expired, changed or unbound");
  }
}
