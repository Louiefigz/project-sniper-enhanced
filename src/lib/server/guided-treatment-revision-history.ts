import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { readRawTreatmentAdmission } from "./guided-raw-treatment-store";
import { readHistoricalGuidedProposal } from "./guided-proposal-history";
import { assertTreatmentRevisionIdle, invalidatedTreatment, readTreatmentRevisionReservation } from "./guided-treatment-revision-store";

/** Current text plus bounded immutable ancestors; no source refresh, fulfillment or historical-current substitution. */
export function readTreatmentBriefHistory(value: unknown) {
  const dir = canonicalProducerDir(value), held = readRawTreatmentAdmission(dir, { pendingRevisionObservation: true });
  const history = held.lineage.map((row, index) => {
    const pointer = index === 0 ? held.pointer : held.lineage[index - 1].before.guidedHandoffV2!;
    const proposal = pointer.treatmentProposalHash ? readHistoricalGuidedProposal(dir, row.hash) : null;
    return { treatmentAdmissionHash: row.hash, requestHash: canonicalJsonSha256(row.submission), requestId: row.submission.requestId,
      rawIntent: row.submission.rawIntent, admittedAt: String(row.admission.admittedAt), active: index === 0,
      parentAdmissionHash: row.admission.parentAdmissionHash ?? null, supersedesRequestHash: row.admission.supersedesRequestHash ?? null,
      retainedUnapprovedPointers: invalidatedTreatment(pointer), proposal };
  });
  let revisionBlockedReason: string | null = null;
  try { assertTreatmentRevisionIdle(held); } catch (error) { revisionBlockedReason = String(error); }
  const pending = readTreatmentRevisionReservation(dir, held.pointer.treatmentAdmissionHash!);
  if (observeHumanCutJob(dir).sha256 !== held.sha256) throw new Error("Treatment brief history changed during read");
  return { scope: "raw-treatment-history-not-source-requalification-or-approval", generationStartedAt: held.generationStartedAt,
    pendingReservationHash: pending?.sha256 ?? null,
    clockHash: held.clock.hash, firstRequestHash: held.clock.value.firstRequestHash, currentBrief: history[0], history,
    revisionBlockedReason, pendingRevision: pending ? { idempotencyKey: String(pending.value.idempotencyKey),
      requestHash: String(pending.value.requestObjectHash), parentAdmissionHash: String(pending.value.parentAdmissionHash),
      recovery: "reconcile-revision with the same retained full request" } : null,
    revisionBindings: revisionBlockedReason ? null : { expectedToken: held.job.token, expectedJournalHash: held.sha256,
      cutDecisionHash: held.pointer.cutDecisionHash, parentRevisionHash: held.pointer.pictureLockedRevisionHash,
      parentAdmissionHash: held.pointer.treatmentAdmissionHash!, supersedesRequestHash: canonicalJsonSha256(held.submission) },
    sourceFreshness: "not-requalified-by-history", approved: false };
}

/** A reservation is an independent durable fence; unchanged journal bytes alone cannot imply no pending revision. */
export function assertTreatmentBriefHistoryCurrent(dir: string, held: ReturnType<typeof readTreatmentBriefHistory>): void {
  const pending = readTreatmentRevisionReservation(dir, held.currentBrief.treatmentAdmissionHash);
  if ((pending?.sha256 ?? null) !== held.pendingReservationHash) throw new Error("Treatment revision reservation changed during status observation");
}
