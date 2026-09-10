import { exactKeys, objectValue } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { openingDeadlineAdmission, OPENING_DEADLINE_POLICY } from "./opening-deadline";
import { captureGenerationCheckpointClock, deadlineTimestamp, finiteDeadlineClock, SYSTEM_DEADLINE_CLOCKS,
  type DeadlineClocks, type GenerationClockOrigin, type GenerationCheckpoint } from "./generation-attempt-clock";

export interface OpeningClockHandoff {
  receivedAt: string;
  admission: ReturnType<typeof openingDeadlineAdmission>;
  observation: { schemaVersion: number; kind: string; clockHash: string; observedAt: string;
    elapsedMs: number; remainingMs: number; state: string };
}

/** A handoff carries measured duration, never a foreign performance.now() epoch. */
export function parseOpeningClockHandoff(value: unknown, origin: GenerationClockOrigin): OpeningClockHandoff {
  const row = objectValue(value, "opening clock handoff"), keys = ["receivedAt", "admission", "observation"];
  exactKeys(row, keys, keys, "opening clock handoff");
  const received = deadlineTimestamp(String(row.receivedAt)), expected = openingDeadlineAdmission(origin, received);
  const observation = objectValue(row.observation, "opening handoff observation");
  const fields = ["schemaVersion", "kind", "clockHash", "observedAt", "elapsedMs", "remainingMs", "state"];
  exactKeys(observation, fields, fields, "opening handoff observation");
  const wallElapsed = deadlineTimestamp(String(observation.observedAt)) - received;
  const elapsed = observation.elapsedMs, maximum = OPENING_DEADLINE_POLICY.wholeAttemptMs;
  if (!expected.admitted || canonicalJsonSha256(row.admission) !== canonicalJsonSha256(expected)
      || observation.schemaVersion !== 1 || observation.kind !== "guided-opening-deadline-observation"
      || observation.clockHash !== origin.clockHash || observation.state !== "within-deadline"
      || wallElapsed < 0 || typeof elapsed !== "number" || !Number.isFinite(elapsed) || elapsed < wallElapsed
      || elapsed < 0 || elapsed >= maximum || observation.remainingMs !== Math.floor(maximum - elapsed)) {
    throw new Error("Opening controller handoff lost its original admitted deadline or measured elapsed time");
  }
  return row as unknown as OpeningClockHandoff;
}

/** Continue once after a launch, without resetting the original wall deadline or elapsed floor.
 * Subsequent controller crashes are NOT resumable through this helper. */
export function startHandedOffOpeningAttempt(input: { origin: GenerationClockOrigin; handoff: unknown; startupElapsedMs: number },
  clocks: DeadlineClocks = SYSTEM_DEADLINE_CLOCKS) {
  const held = parseOpeningClockHandoff(input.handoff, input.origin);
  const clock = captureGenerationCheckpointClock(clocks), initial = clock.sample();
  const beganWall = initial.wall, beganMono = initial.mono;
  const received = deadlineTimestamp(held.receivedAt), observed = deadlineTimestamp(held.observation.observedAt);
  // Charge this child's locally measured startup/wait even if wall time stalls. An overlap
  // with the parent's final measurement is conservatively charged, never refunded.
  const startup = finiteDeadlineClock(input.startupElapsedMs);
  const floor = Math.max(beganWall - received, held.observation.elapsedMs + Math.max(startup, beganWall - observed));
  let previousWall = beganWall, previousMono = beganMono, poisoned = beganWall < observed;
  function observe(retain?: GenerationCheckpoint) {
    const { wall, mono, invalid } = clock.sample();
    poisoned ||= invalid || wall < previousWall || mono < previousMono;
    previousWall = wall; previousMono = mono;
    const observedAt = new Date(wall).toISOString();
    const completed = clock.complete({ elapsedMs: Math.max(wall - received,
      floor + Math.max(wall - beganWall, mono - beganMono)), observedAt, mono }, retain);
    poisoned ||= completed.invalid || completed.mono < previousMono;
    previousMono = completed.mono;
    const elapsedMs = completed.elapsedMs;
    const remainingMs = poisoned ? 0 : Math.max(0, Math.floor(OPENING_DEADLINE_POLICY.wholeAttemptMs - elapsedMs));
    return { schemaVersion: 1, kind: "guided-opening-deadline-observation", clockHash: input.origin.clockHash,
      observedAt, elapsedMs, remainingMs,
      state: poisoned ? "clock-invalid" : remainingMs <= 0 ? "deadline-exceeded" : "within-deadline" } as const;
  }
  return { admission: held.admission, observe, remainingMs: () => {
    const result = observe();
    if (result.state !== "within-deadline") throw new Error(`Opening handoff budget ${result.state}; no new attempt allowance`);
    return result.remainingMs;
  } };
}
