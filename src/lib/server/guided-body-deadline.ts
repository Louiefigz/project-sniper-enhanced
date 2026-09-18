import { objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { GENERATION_DEADLINE_POLICY } from "./generation-deadline";
import { OPENING_DEADLINE_POLICY } from "./opening-deadline";
import { assertGenerationPrecommit, deadlineTimestamp, finiteDeadlineClock, startGenerationAttempt,
  SYSTEM_DEADLINE_CLOCKS, type DeadlineClocks, type GenerationClockOrigin } from "./generation-attempt-clock";

export const BODY_DEADLINE_POLICY = Object.freeze({
  version: 1, basis: GENERATION_DEADLINE_POLICY.basis, requestMs: GENERATION_DEADLINE_POLICY.requestMs,
  wholeAttemptMs: 55 * 60_000, requiredFinishReserveMs: 25 * 60_000,
  preparedAssetCreditMs: 0, scope: "body-admission-not-calibrated-throughput-or-complete-request-accounting",
} as const);
const verifierTails = new WeakMap<() => number, () => void>();

/** Charge the last finite metadata sweep without calling the parent or renewing its allowance. */
export function assertBodyVerifierRemainderCurrent(remaining: () => number): void {
  const check = verifierTails.get(remaining);
  if (!check) throw new Error("Body verifier tail requires its actual original subdeadline");
  check();
}

/** One readback subdeadline inside the live body attempt, never a renewed per-call allowance. */
export function captureBodyVerifierRemainder(parent: () => number, monotonic = () => performance.now()): () => number {
  const began = finiteDeadlineClock(monotonic());
  const initial = finiteDeadlineClock(parent());
  const allowance = Math.min(initial, OPENING_DEADLINE_POLICY.wholeAttemptMs);
  if (allowance < 1) throw new Error("Body verifier has no remaining caller budget");
  let previous = began, end = began + allowance, invalid = false;
  const read = (caller?: number) => {
    if (invalid) throw new Error("Body verifier subdeadline is invalid or exhausted");
    try {
      const now = finiteDeadlineClock(monotonic());
      if (caller !== undefined) end = Math.min(end, now + caller);
      const remaining = Math.floor(end - now);
      if (now < previous || remaining < 1) throw new Error("Body verifier subdeadline is invalid or exhausted");
      previous = now;
      return remaining;
    } catch (error) { invalid = true; throw error; }
  };
  const remaining = () => {
    if (invalid) throw new Error("Body verifier subdeadline is invalid or exhausted");
    try { return read(finiteDeadlineClock(parent())); }
    catch (error) { invalid = true; throw error; }
  };
  verifierTails.set(remaining, () => { read(); }); return remaining;
}

/** Body preparation keeps QC15 + promotion5 + variance5 inside the ORIGINAL request. */
export function bodyDeadlineAdmission(origin: GenerationClockOrigin, receivedMs: number) {
  const clockHash = sha256(origin.clockHash, "body clockHash"), began = deadlineTimestamp(origin.startedAt);
  const observed = finiteDeadlineClock(receivedMs), policy = BODY_DEADLINE_POLICY;
  if (!Number.isSafeInteger(observed) || observed < began) throw new Error("Body original request clock is invalid");
  const requestDeadline = began + policy.requestMs, phaseDeadline = requestDeadline - policy.requiredFinishReserveMs;
  const remaining = Math.max(0, phaseDeadline - observed), admitted = remaining >= policy.wholeAttemptMs;
  return Object.freeze({ schemaVersion: 1, kind: "guided-body-deadline-admission", policy, clockHash,
    generationStartedAt: origin.startedAt, observedAt: new Date(observed).toISOString(),
    requestDeadlineAt: new Date(requestDeadline).toISOString(), phaseDeadlineAt: new Date(phaseDeadline).toISOString(),
    elapsedRequestWallMs: observed - began, remainingBodyPhaseWallMs: remaining, admitted,
    reason: admitted ? "within-declared-allocation" : "insufficient-time-for-body-and-required-finish",
    attemptDeadlineAt: admitted ? new Date(observed + policy.wholeAttemptMs).toISOString() : null,
    excludedUserWaitMs: null } as const);
}

/** Capture after closed parsing, before authority/lease I/O; bind once without renewing elapsed time. */
export function captureBodyAttemptStart(clocks: DeadlineClocks = SYSTEM_DEADLINE_CLOCKS) {
  const wall = finiteDeadlineClock(clocks.wall()), mono = finiteDeadlineClock(clocks.monotonic());
  if (!Number.isSafeInteger(wall)) throw new Error("Body received clock must use whole milliseconds");
  let bound = false;
  return { receivedAt: new Date(wall).toISOString(), start(origin: GenerationClockOrigin) {
    if (bound) throw new Error("Body attempt cannot renew its original admission");
    bound = true;
    let firstWall = true, firstMono = true;
    return startGenerationAttempt({ origin, admit: bodyDeadlineAdmission, attemptMs: BODY_DEADLINE_POLICY.wholeAttemptMs,
      kind: "guided-body-deadline-observation" }, {
      wall: () => { if (firstWall) { firstWall = false; return wall; } return clocks.wall(); },
      monotonic: () => { if (firstMono) { firstMono = false; return mono; } return clocks.monotonic(); },
    });
  } };
}

/** Retained admission is historical only; it never restarts body work or excludes approval wait. */
export function assertBodyDeadlineProof(values: { admission: unknown; precommit: unknown }, binding: {
  origin: GenerationClockOrigin; executionReceivedAt: string; executionStartedAt: string; createdAt: string;
}): void {
  const admission = objectValue(values.admission, "body budget admission"), received = deadlineTimestamp(binding.executionReceivedAt);
  const expected = bodyDeadlineAdmission(binding.origin, received);
  if (!expected.admitted || canonicalJsonSha256(admission) !== canonicalJsonSha256(expected)
      || received > deadlineTimestamp(binding.executionStartedAt)
      || deadlineTimestamp(binding.executionStartedAt) > deadlineTimestamp(binding.createdAt)) {
    throw new Error("Body admission lost its exact request/execution/original-clock binding");
  }
  assertGenerationPrecommit(values.precommit, { clockHash: expected.clockHash, observedAt: expected.observedAt,
    createdAt: binding.createdAt, deadlineAt: String(expected.attemptDeadlineAt),
    kind: "guided-body-deadline-observation", attemptMs: BODY_DEADLINE_POLICY.wholeAttemptMs });
}
