/** Deterministic second cleanup CAS data. No acknowledgement, lease, process or retirement authority. */
import { parsePreparedSourceColorCleanupFact, parseFinalSourceColorCleanupFact,
  type PreparedSourceColorCleanupFact, type FinalSourceColorCleanupFact } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";
import { sha256 } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import type { AutoEditJob } from "./auto-edit-job-types";
import { strictGuidedTimestamp } from "./guided-cut-v2-store";

export interface SourceColorCleanupRetiredJobInput {
  job: AutoEditJob;
  pendingJournalHash: string;
  prepared: PreparedSourceColorCleanupFact;
}
const MESSAGE = "Exact opening resources are clean and the source-color reservation is retired. No media is selected or approved.";
const BLOCKED = ["openingMediaSelectionHash", "openingApprovalHash", "bodyExecutionClaimHash",
  "bodyActivationHash", "bodyProcessOutcomeHash", "bodyCleanupHash", "bodyCandidateHash"];

function assertPendingJob(job: AutoEditJob, prepared: PreparedSourceColorCleanupFact): void {
  const pointer = job.guidedHandoffV2;
  if (job.status !== "treatment_admitted" || !pointer?.openingProcessOutcomeHash
      || pointer.openingExecutionClaimHash !== prepared.claimHash
      || pointer.openingCleanupHash !== canonicalJsonSha256(prepared)
      || BLOCKED.some(key => Object.hasOwn(pointer, key))) {
    throw new Error("Source color retirement requires its exact unselected pending claim and process outcome");
  }
  if (!Number.isSafeInteger(job.nextEventId) || job.nextEventId < 1 || !Number.isSafeInteger(job.nextEventId + 1)) {
    throw new Error("Source color retirement event sequence is invalid or exhausted");
  }
}

function assertFinalIdentity(input: SourceColorCleanupRetiredJobInput, fact: FinalSourceColorCleanupFact): void {
  const { prepared, job } = input;
  if (fact.pendingJournalHash !== input.pendingJournalHash || fact.preparedFactHash !== canonicalJsonSha256(prepared)
      || fact.claimHash !== prepared.claimHash || fact.executionId !== prepared.executionId
      || fact.cleanupAttemptId !== prepared.cleanupAttemptId || fact.clockHash !== prepared.clockHash
      || fact.generationStartedAt !== prepared.generationStartedAt
      || fact.createdAt < prepared.createdAt || fact.createdAt < strictGuidedTimestamp(job.updatedAt)) {
    throw new Error("Source color retirement fact differs from its exact pending parent, prepared identity or original clock");
  }
}

function retiredEvent(job: AutoEditJob, fact: FinalSourceColorCleanupFact, finalHash: string) {
  return { id: job.nextEventId, at: fact.createdAt, payload: {
    event: "opening_source_color_cleanup_retired", executionId: fact.executionId,
    cleanupHash: finalHash, preparedFactHash: fact.preparedFactHash, pendingJournalHash: fact.pendingJournalHash,
    retirementAckSha256: fact.retirementAck.sha256, claimRetained: false, clockHash: fact.clockHash,
    generationStartedAt: fact.generationStartedAt, mediaSelected: false, openingApproved: false, deliveryApproved: false,
  } };
}

/** Callers must authenticate actual ack bytes and the exact pending journal edge separately. */
export function buildSourceColorCleanupRetiredJob(input: SourceColorCleanupRetiredJobInput,
  value: FinalSourceColorCleanupFact): AutoEditJob {
  const prepared = parsePreparedSourceColorCleanupFact(input.prepared), fact = parseFinalSourceColorCleanupFact(value);
  const pendingJournalHash = sha256(input.pendingJournalHash, "pendingJournalHash");
  const original = structuredClone(parseAutoEditJobRecord(input.job));
  assertPendingJob(original, prepared); assertFinalIdentity({ job: original, pendingJournalHash, prepared }, fact);
  const { openingExecutionClaimHash: claim, openingProcessOutcomeHash: outcome, ...pointer } = original.guidedHandoffV2!;
  void claim; void outcome;
  const finalHash = canonicalJsonSha256(fact);
  return parseAutoEditJobRecord({ ...original, updatedAt: fact.createdAt, message: MESSAGE,
    guidedHandoffV2: { ...pointer, openingCleanupHash: finalHash }, nextEventId: original.nextEventId + 1,
    events: [...original.events, retiredEvent(original, fact, finalHash)].slice(-256) });
}
