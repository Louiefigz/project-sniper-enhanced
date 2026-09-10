/** Exact first cleanup journal transition. Pure data policy, never live cleanup or retirement authority. */
import { parsePreparedSourceColorCleanupFact, type PreparedSourceColorCleanupFact } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import type { AutoEditJob } from "./auto-edit-job-types";
import type { HeldOpeningClaim } from "./guided-opening-process";
import { strictGuidedTimestamp } from "./guided-cut-v2-store";

const PENDING_MESSAGE = "Exact opening resources are clean; source-color reservation retirement remains pending. The claim is retained and no media is selectable.";

function assertPreparedIdentity(held: HeldOpeningClaim, fact: PreparedSourceColorCleanupFact): void {
  const pointer = held.job.guidedHandoffV2;
  if (held.submission.schemaVersion !== 2 || held.job.status !== "treatment_admitted"
      || !pointer?.openingProcessOutcomeHash || pointer.openingExecutionClaimHash !== held.claimHash
      || pointer.openingCleanupHash || pointer.openingMediaSelectionHash || pointer.openingApprovalHash
      || pointer.bodyExecutionClaimHash || pointer.bodyActivationHash || pointer.bodyProcessOutcomeHash
      || pointer.bodyCleanupHash || pointer.bodyCandidateHash) {
    throw new Error("Source color cleanup preparation requires its original unselected stopped claim");
  }
  if (fact.beforeJournalHash !== held.sha256 || fact.claimHash !== held.claimHash
      || fact.executionId !== held.claim.executionId || fact.clockHash !== held.claim.clockHash
      || fact.generationStartedAt !== held.claim.generationStartedAt
      || fact.sourceColorHash !== canonicalJsonSha256(held.submission.sourceColor)
      || strictGuidedTimestamp(held.job.updatedAt) > fact.createdAt) {
    throw new Error("Source color cleanup prepared fact differs from its entire original claim and clock");
  }
  if (!Number.isSafeInteger(held.job.nextEventId) || held.job.nextEventId < 1
      || !Number.isSafeInteger(held.job.nextEventId + 1)) {
    throw new Error("Source color cleanup event sequence is invalid or exhausted");
  }
}

function pendingEvent(held: HeldOpeningClaim, fact: PreparedSourceColorCleanupFact) {
  return { id: held.job.nextEventId, at: fact.createdAt, payload: {
    event: "opening_source_color_cleanup_prepared", executionId: held.claim.executionId,
    cleanupHash: canonicalJsonSha256(fact), claimRetained: true, clockHash: held.claim.clockHash,
    generationStartedAt: held.claim.generationStartedAt, mediaSelected: false,
    openingApproved: false, deliveryApproved: false,
  } };
}

/** Keep claim/outcome and every unrelated field. Only a later exact retirement edge can clear them.
 * Both the writer and cold pending reader use this complete deterministic job, not a stripped pointer.
 */
export function buildSourceColorCleanupPendingJob(held: HeldOpeningClaim, value: PreparedSourceColorCleanupFact): AutoEditJob {
  const fact = parsePreparedSourceColorCleanupFact(value);
  assertPreparedIdentity(held, fact);
  const original = structuredClone(parseAutoEditJobRecord(held.job));
  return parseAutoEditJobRecord({
    ...original,
    updatedAt: fact.createdAt,
    message: PENDING_MESSAGE,
    guidedHandoffV2: { ...original.guidedHandoffV2, openingCleanupHash: canonicalJsonSha256(fact) },
    nextEventId: original.nextEventId + 1,
    events: [...original.events, pendingEvent(held, fact)].slice(-256),
  });
}
