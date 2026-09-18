import { objectValue } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { GENERATION_DEADLINE_POLICY, proposalDeadlineAdmission } from "./generation-deadline";
import { assertGenerationPrecommit, deadlineTimestamp, finiteDeadlineClock, startGenerationAttempt,
  SYSTEM_DEADLINE_CLOCKS, type DeadlineClocks, type GenerationClockOrigin } from "./generation-attempt-clock";

export const OPENING_DEADLINE_POLICY = Object.freeze({
  version: 1, basis: GENERATION_DEADLINE_POLICY.basis,
  requestMs: GENERATION_DEADLINE_POLICY.requestMs,
  wholeAttemptMs: 25 * 60_000,
  // Base/master completion is NOT proof that body graphics/captions are ready.
  // Preserve planning15 + body assets25 + assembly15 + QC15 + promotion5 + variance5.
  requiredDownstreamReserveMs: GENERATION_DEADLINE_POLICY.afterProposalReserveMs,
  preparedAssetCreditMs: 0,
  excess: "inside-original-proposal-phase-no-new-repair-pool",
} as const);

/** Conservative pre-render admission, not a forecast or a body-work credit.
 * Original proposal/readiness/retries keep consuming the same request clock. */
export function openingDeadlineAdmission(origin: GenerationClockOrigin, receivedMs: number) {
  const prior = proposalDeadlineAdmission(origin, receivedMs), policy = OPENING_DEADLINE_POLICY;
  const admitted = prior.remainingProposalWallMs >= policy.wholeAttemptMs;
  return Object.freeze({ schemaVersion: 1, kind: "guided-opening-deadline-admission", policy,
    scope: "private-opening-guard-not-body-readiness-or-complete-request-accounting", clockHash: prior.clockHash,
    generationStartedAt: prior.generationStartedAt, observedAt: prior.observedAt,
    requestDeadlineAt: prior.requestDeadlineAt, phaseDeadlineAt: prior.phaseDeadlineAt,
    elapsedRequestWallMs: prior.elapsedRequestWallMs, remainingOpeningPhaseWallMs: prior.remainingProposalWallMs,
    admitted, reason: admitted ? "within-declared-allocation" : "insufficient-time-for-opening-and-required-finish",
    attemptDeadlineAt: admitted ? new Date(receivedMs + policy.wholeAttemptMs).toISOString() : null,
    excludedUserWaitMs: null } as const);
}

/** Capture immediately after closed request parsing, BEFORE disk authority reads
 * or lease acquisition. Bind the actual origin later without renewing this start. */
export function captureOpeningAttemptStart(clocks: DeadlineClocks = SYSTEM_DEADLINE_CLOCKS) {
  const wall = finiteDeadlineClock(clocks.wall()), mono = finiteDeadlineClock(clocks.monotonic());
  if (!Number.isSafeInteger(wall)) throw new Error("Opening receipt clock must use whole milliseconds");
  let bound = false;
  return { receivedAt: new Date(wall).toISOString(), start(origin: GenerationClockOrigin) {
    if (bound) throw new Error("Opening attempt start cannot be renewed");
    bound = true;
    let firstWall = true, firstMono = true;
    return startGenerationAttempt({ origin, admit: openingDeadlineAdmission,
      attemptMs: OPENING_DEADLINE_POLICY.wholeAttemptMs, kind: "guided-opening-deadline-observation" }, {
      wall: () => { if (firstWall) { firstWall = false; return wall; } return clocks.wall(); },
      monotonic: () => { if (firstMono) { firstMono = false; return mono; } return clocks.monotonic(); },
    });
  } };
}

/** Reopening a successful deadline record cannot authorize a retry or media.
 * The exact receivedAt belongs to this execution, not its first idempotent intake. */
export function assertOpeningDeadlineProof(values: { admission: unknown; precommit: unknown }, binding: {
  origin: GenerationClockOrigin; executionReceivedAt: string; executionStartedAt: string; createdAt: string;
}): void {
  const admission = objectValue(values.admission, "opening budget admission"), received = deadlineTimestamp(binding.executionReceivedAt);
  const expected = openingDeadlineAdmission(binding.origin, received);
  if (!expected.admitted || canonicalJsonSha256(admission) !== canonicalJsonSha256(expected)
      || received > deadlineTimestamp(binding.executionStartedAt)
      || deadlineTimestamp(binding.executionStartedAt) > deadlineTimestamp(binding.createdAt)) {
    throw new Error("Opening budget admission changed or lost its actual request/execution start");
  }
  assertGenerationPrecommit(values.precommit, { clockHash: expected.clockHash, observedAt: expected.observedAt,
    createdAt: binding.createdAt, deadlineAt: String(expected.attemptDeadlineAt),
    kind: "guided-opening-deadline-observation", attemptMs: OPENING_DEADLINE_POLICY.wholeAttemptMs });
}
