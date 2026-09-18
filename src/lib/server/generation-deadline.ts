import { objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { assertGenerationPrecommit, deadlineTimestamp as timestamp, finiteDeadlineClock as finiteClock,
  startGenerationAttempt, type DeadlineClocks, type GenerationClockOrigin } from "./generation-attempt-clock";
export type { DeadlineClocks, GenerationClockOrigin } from "./generation-attempt-clock";

const MINUTE = 60_000;
export const GENERATION_DEADLINE_POLICY = Object.freeze({
  version: 1,
  basis: "declared-engineering-allocation-not-measured-throughput",
  requestMs: 120 * MINUTE,
  proposalAttemptMs: 10 * MINUTE,
  // Remaining clean work: planning15 + assets25 + assembly15 + QC15 +
  // promotion5 + variance5. No reduced review or lower-effort provider fallback.
  afterProposalReserveMs: 80 * MINUTE,
} as const);

/** Pure scheduling decision; caller must verify the original clock authority.
 * No idle time is inferred/excluded, and this does not implement the repair ledger. */
export function proposalDeadlineAdmission(origin: GenerationClockOrigin, observedMs: number) {
  const clockHash = sha256(origin.clockHash, "generation clock hash");
  const began = timestamp(origin.startedAt), observed = finiteClock(observedMs);
  if (!Number.isSafeInteger(observed)) throw new Error("Generation wall clock must use whole milliseconds");
  if (observed < began) throw new Error("Generation clock moved backwards before admission");
  const policy = GENERATION_DEADLINE_POLICY;
  const requestDeadlineMs = began + policy.requestMs;
  const phaseDeadlineMs = requestDeadlineMs - policy.afterProposalReserveMs;
  const remainingMs = Math.max(0, phaseDeadlineMs - observed);
  const admitted = remainingMs >= policy.proposalAttemptMs;
  return Object.freeze({
    schemaVersion: 1, kind: "guided-proposal-deadline-admission", policy,
    scope: "proposal-guard-not-complete-request-accounting", clockHash,
    generationStartedAt: origin.startedAt, observedAt: new Date(observed).toISOString(),
    requestDeadlineAt: new Date(requestDeadlineMs).toISOString(),
    phaseDeadlineAt: new Date(phaseDeadlineMs).toISOString(),
    elapsedRequestWallMs: observed - began, remainingProposalWallMs: remainingMs,
    admitted, reason: admitted ? "within-declared-allocation" : "insufficient-time-for-proposal-and-required-finish",
    attemptDeadlineAt: admitted ? new Date(observed + policy.proposalAttemptMs).toISOString() : null,
    excludedUserWaitMs: null,
  } as const);
}
export type ProposalDeadlineAdmission = ReturnType<typeof proposalDeadlineAdmission>;

/** Reopen scheduling evidence against the already verified request/execution.
 * A passing deadline record is not editorial, rendering or delivery authority. */
export function assertProposalDeadlineProof(values: { admission: unknown; precommit: unknown },
  binding: { origin: GenerationClockOrigin; executionStartedAt: string; createdAt: string }): void {
  const admission = objectValue(values.admission, "proposal budget admission");
  const observed = timestamp(String(admission.observedAt));
  const expected = proposalDeadlineAdmission(binding.origin, observed);
  if (!expected.admitted || canonicalJsonSha256(admission) !== canonicalJsonSha256(expected)
      || observed < timestamp(binding.executionStartedAt)) throw new Error("Proposal budget admission changed");
  assertGenerationPrecommit(values.precommit, { clockHash: expected.clockHash, observedAt: expected.observedAt,
    createdAt: binding.createdAt, deadlineAt: String(expected.attemptDeadlineAt),
    kind: "guided-proposal-deadline-observation", attemptMs: GENERATION_DEADLINE_POLICY.proposalAttemptMs });
}

/** A live same-process attempt clock. Persist its observation, never reuse its
 * monotonic origin across process restarts or manufacture a fresh request clock. */
export function startProposalDeadline(origin: GenerationClockOrigin, clocks?: DeadlineClocks) {
  return startGenerationAttempt({ origin, admit: proposalDeadlineAdmission,
    attemptMs: GENERATION_DEADLINE_POLICY.proposalAttemptMs, kind: "guided-proposal-deadline-observation" }, clocks);
}
