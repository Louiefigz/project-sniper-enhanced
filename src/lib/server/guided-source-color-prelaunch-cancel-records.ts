/** Distinct pre-dispatch cancellation records and one deterministic journal edge. Never process/cleanup proof. */
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { strictGuidedTimestamp } from "./guided-cut-v2-store";
import { sourceColorOpeningReference } from "./guided-source-color-staging-hold";
import type { claimSourceColorPrelaunchCancellation } from "./guided-source-color-prelaunch-owner";
import type { SourceColorFileRef } from "./guided-source-color-expectations";
import type { AutoEditJob } from "./auto-edit-job-types";

export type PrelaunchCancellationTransfer = ReturnType<typeof claimSourceColorPrelaunchCancellation>;
const FLAGS = { mediaSelected: false, openingApproved: false, deliveryApproved: false } as const;
export interface CancellationRecordReferences {
  reservation: SourceColorFileRef | null;
  archive: SourceColorFileRef | null;
  journalSnapshot: SourceColorFileRef;
}

/** Values come from the actual live transfer, never caller-supplied declarations of absent children. */
export function prelaunchCancellationIntent(held: PrelaunchCancellationTransfer,
  refs: CancellationRecordReferences, receivedAt: string) {
  strictGuidedTimestamp(receivedAt);
  if (receivedAt < held.journal.job.updatedAt || receivedAt < held.original.claim.claim.generationStartedAt) {
    throw new Error("Prelaunch cancellation clock precedes its original claimed journal");
  }
  return { schemaVersion: 1 as const, kind: "guided-opening-source-color-prelaunch-cancellation-intent" as const,
    scope: "same-live-undispatched-cancellation-not-process-settlement-or-cleanup" as const,
    opening: sourceColorOpeningReference(held.original.staging), claimedJournalHash: held.journal.sha256,
    sourceColorHash: canonicalJsonSha256(held.original.staging.sourceColor), publications: [...held.publications],
    ...refs, receivedAt, budgetScope: "separate-protected-cleanup-not-render-allowance" as const,
    claimRetained: true as const, ...FLAGS };
}
export type PrelaunchCancellationIntent = ReturnType<typeof prelaunchCancellationIntent>;

/** An acknowledgement records an actual same-live transition; serialized absence is not recovery authority. */
export function prelaunchCancellationAck(intent: PrelaunchCancellationIntent, intentRef: SourceColorFileRef, observedAt: string) {
  strictGuidedTimestamp(observedAt);
  if (observedAt < intent.receivedAt) throw new Error("Prelaunch cancellation acknowledgement clock moved backwards");
  return { schemaVersion: 1 as const, kind: "guided-opening-source-color-prelaunch-cancellation-ack" as const,
    scope: "same-live-reservation-transition-not-process-cleanup-or-claim-clearance" as const,
    intent: intentRef, claimHash: intent.opening.claimSha256, executionId: intent.opening.executionId,
    claimedJournalHash: intent.claimedJournalHash, reservation: intent.reservation, archive: intent.archive,
    disposition: intent.reservation ? "unlinked-original-by-this-live-cancellation" as const : "no-publication-by-this-live-owner" as const,
    observedAt, claimRetained: true as const, ...FLAGS };
}
export type PrelaunchCancellationAck = ReturnType<typeof prelaunchCancellationAck>;

/** Remove only THIS original claim pointer. All previous selection/approval/cleanup fields stay unchanged. */
export function prelaunchCancelledJob(held: PrelaunchCancellationTransfer,
  records: { intent: PrelaunchCancellationIntent; ack: PrelaunchCancellationAck; ackRef: SourceColorFileRef }, createdAt: string): AutoEditJob {
  const job = structuredClone(parseAutoEditJobRecord(held.journal.job)), pointer = job.guidedHandoffV2;
  strictGuidedTimestamp(createdAt);
  if (job.status !== "treatment_admitted" || pointer?.openingExecutionClaimHash !== held.original.claim.claimHash
      || pointer.openingProcessOutcomeHash || records.intent.claimedJournalHash !== held.journal.sha256
      || records.ack.claimHash !== held.original.claim.claimHash || createdAt < records.ack.observedAt
      || createdAt < job.updatedAt || !Number.isSafeInteger(job.nextEventId) || job.nextEventId < 1
      || !Number.isSafeInteger(job.nextEventId + 1)) throw new Error("Cancellation lost its exact undispatched claimed journal");
  const { openingExecutionClaimHash: removed, ...rest } = pointer; void removed;
  return parseAutoEditJobRecord({ ...job, guidedHandoffV2: rest, updatedAt: createdAt,
    message: "This live opening was cancelled before child dispatch. Cancellation does not select or approve media.",
    nextEventId: job.nextEventId + 1, events: [...job.events, { id: job.nextEventId, at: createdAt, payload: {
      event: "opening_source_color_prelaunch_cancelled", executionId: held.original.claim.claim.executionId,
      claimHash: held.original.claim.claimHash, claimedJournalHash: held.journal.sha256,
      cancellationIntentSha256: records.ack.intent.sha256, cancellationAck: records.ackRef,
      clockHash: held.original.claim.claim.clockHash, generationStartedAt: held.original.claim.claim.generationStartedAt,
      claimRetained: false, ...FLAGS,
    } }].slice(-256) });
}
