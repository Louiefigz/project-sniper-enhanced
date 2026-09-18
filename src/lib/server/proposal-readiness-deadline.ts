import { objectValue } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { GENERATION_DEADLINE_POLICY, proposalDeadlineAdmission } from "./generation-deadline";
import { assertGenerationPrecommit, deadlineTimestamp, startGenerationAttempt,
  type DeadlineClocks, type GenerationClockOrigin } from "./generation-attempt-clock";

export const PROPOSAL_READINESS_DEADLINE_POLICY = Object.freeze({
  version: 1, basis: GENERATION_DEADLINE_POLICY.basis,
  requestMs: GENERATION_DEADLINE_POLICY.requestMs,
  afterProposalReserveMs: GENERATION_DEADLINE_POLICY.afterProposalReserveMs,
  wholeAttemptMs: 20 * 60_000,
  cleanProposalTargetMs: 10 * 60_000,
  excess: "inside-original-proposal-phase-not-free-planning-time",
} as const);

/** Both critics share one ceiling inside the ORIGINAL proposal phase. This
 * conservative admission is not the full repair ledger or measured throughput. */
export function proposalReadinessDeadlineAdmission(origin: GenerationClockOrigin, observedMs: number) {
  const prior = proposalDeadlineAdmission(origin, observedMs), policy = PROPOSAL_READINESS_DEADLINE_POLICY;
  const admitted = prior.remainingProposalWallMs >= policy.wholeAttemptMs;
  return Object.freeze({ schemaVersion: 1, kind: "guided-proposal-readiness-deadline-admission", policy,
    scope: "proposal-phase-guard-not-plan-or-complete-request-accounting", clockHash: prior.clockHash,
    generationStartedAt: prior.generationStartedAt, observedAt: prior.observedAt,
    requestDeadlineAt: prior.requestDeadlineAt, phaseDeadlineAt: prior.phaseDeadlineAt,
    elapsedRequestWallMs: prior.elapsedRequestWallMs, remainingProposalWallMs: prior.remainingProposalWallMs,
    admitted, reason: admitted ? "within-declared-allocation" : "insufficient-time-for-readiness-and-required-finish",
    attemptDeadlineAt: admitted ? new Date(observedMs + policy.wholeAttemptMs).toISOString() : null,
    excludedUserWaitMs: null } as const);
}

export function startProposalReadinessDeadline(origin: GenerationClockOrigin, clocks?: DeadlineClocks) {
  return startGenerationAttempt({ origin, admit: proposalReadinessDeadlineAdmission,
    attemptMs: PROPOSAL_READINESS_DEADLINE_POLICY.wholeAttemptMs, kind: "guided-proposal-readiness-deadline-observation" }, clocks);
}

/** Historical proof grants no fresh time. Every future execution must re-admit
 * against the live original clock even when this read-only proof remains valid. */
export function assertProposalReadinessDeadlineProof(values: { admission: unknown; precommit: unknown },
  binding: { origin: GenerationClockOrigin; executionStartedAt: string; createdAt: string }): void {
  const admission = objectValue(values.admission, "readiness budget admission"), observed = deadlineTimestamp(String(admission.observedAt));
  const expected = proposalReadinessDeadlineAdmission(binding.origin, observed);
  if (!expected.admitted || canonicalJsonSha256(admission) !== canonicalJsonSha256(expected)
      || observed < deadlineTimestamp(binding.executionStartedAt)) throw new Error("Readiness budget admission changed");
  assertGenerationPrecommit(values.precommit, { clockHash: expected.clockHash, observedAt: expected.observedAt,
    createdAt: binding.createdAt, deadlineAt: String(expected.attemptDeadlineAt),
    kind: "guided-proposal-readiness-deadline-observation", attemptMs: PROPOSAL_READINESS_DEADLINE_POLICY.wholeAttemptMs });
}
