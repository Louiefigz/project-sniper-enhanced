import { parseGuidedWorkflowV2 } from "@/lib/producer/contracts/guided-workflow-v2";
import { GUIDED_OPENING_STATUS_SCOPE, type GuidedOpeningStatusV1, type GuidedOpeningTimingV1 } from "@/lib/producer/contracts/guided-opening-status-v1";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { readGuidedOpeningExecutionClaim } from "./guided-opening-claim";
import { ownershipUnresolved, readStoppedOpeningProcess } from "./guided-opening-process";
import { readCommittedOpeningCleanup, readPendingOpeningCleanup, assertPendingOpeningCleanupRead } from "./guided-opening-cleanup-store";
import { assertOpeningSelectionMetadata, openingMediaDescriptors, readSelectedOpeningMedia } from "./guided-opening-selection";
import { assertSourceColorOpeningApprovalSummaryMetadata, readGuidedOpeningApproval } from "./guided-opening-approval";

const UNAVAILABLE_TIMING: GuidedOpeningTimingV1 = { generationStartedAt: null, engineElapsedMs: null,
  cleanupElapsedMs: null, elapsedStatus: "unavailable", coverage: "unavailable" };
const sourceStatusProofs = new WeakMap<object, () => void>();

/** Read-only dependency seam. No success/approval or raw artifact paths are projected through this initial observer. */
export const guidedOpeningStatusReads = { job: observeHumanCutJob, claim: readGuidedOpeningExecutionClaim,
  stopped: readStoppedOpeningProcess, cleanup: readCommittedOpeningCleanup, pendingCleanup: readPendingOpeningCleanup,
  selection: readSelectedOpeningMedia, approval: readGuidedOpeningApproval };

function common() {
  return { ok: true as const, schemaVersion: 1 as const, scope: GUIDED_OPENING_STATUS_SCOPE,
    openingApproved: false as const, deliveryApproved: false as const, subjectiveListening: "not-performed-by-system" as const };
}

function claimed(held: ReturnType<typeof readGuidedOpeningExecutionClaim>, reads: typeof guidedOpeningStatusReads): GuidedOpeningStatusV1 {
  const identity = { requestId: held.claim.requestId, executionId: held.claim.executionId, claimHash: held.claimHash };
  const unknown: GuidedOpeningStatusV1 = { ...common(), ...identity, state: "pending-owned-execution",
    detail: "This opening owns unresolved resources. Worker-stop or nested-process evidence is missing or unreadable; this does not prove the worker is running or stopped. If the attempt was interrupted, manual recovery is required before another render.",
    timing: { ...UNAVAILABLE_TIMING, generationStartedAt: held.claim.generationStartedAt } };
  try {
    const stopped = reads.stopped(held);
    if (ownershipUnresolved(stopped)) {
      const live = (stopped.liveDescendants ?? []).map((row) => `pid ${row.pid} ${row.argv0}`).join(", ");
      const unrecorded = (stopped.unrecordedSpawns ?? []).join(", ");
      const unknown = (stopped.unknownDescendants ?? []).map((row) => `pid ${row.pid} ${row.argv0}: ${row.reason}`).join("; ");
      const tail = "Ownership stays unresolved: exact Docker cleanup may run, but no media from this attempt is selectable and manual resolution is required.";
      return { ...common(), ...identity, state: "pending-owned-execution",
        detail: stopped.receipt.forcedStop === true
          ? "The owned outer worker group was force-stopped by its deadline or output bound. Nested local probe ownership was never observed, so this claim stays unresolved: exact Docker cleanup may run, but no media from this attempt is selectable and manual resolution is required."
          : live ? `A process the owned worker itself recorded is still alive after the worker stopped (${live}). ${tail}`
          : unknown ? `A process the owned worker recorded could not be observed (${unknown}); unknown is not absent. ${tail}`
          : `The owned worker recorded an intent to start ${unrecorded} but never recorded its pid; that child is unknown, not absent. ${tail}`,
        timing: { generationStartedAt: held.claim.generationStartedAt, engineElapsedMs: Number(stopped.receipt.elapsedMs),
          cleanupElapsedMs: null, elapsedStatus: "completed", coverage: "recorded-owned-attempt-only" } };
    }
    return { ...common(), ...identity, state: "pending-cleanup", detail: stopped.receipt.status === "failed"
      ? "The private opening attempt failed. Exact owned-resource cleanup is still required; no media is selectable."
      : "The owned worker stopped. Exact resource cleanup and strong media verification remain required before playback.",
    timing: { generationStartedAt: held.claim.generationStartedAt, engineElapsedMs: Number(stopped.receipt.elapsedMs),
      cleanupElapsedMs: null, elapsedStatus: "completed", coverage: "recorded-owned-attempt-only" } };
  } catch { return unknown; } // Unreadable/forged/missing stop proof cannot become liveness or cleanup permission.
}

/** Only a failed current-claim read may try the distinct, fully joined current prepared record. */
function pending(dir: string, reads: typeof guidedOpeningStatusReads) {
  let held: ReturnType<typeof readGuidedOpeningExecutionClaim>;
  try { held = reads.claim(dir); }
  catch {
    const proof = reads.pendingCleanup(dir), original = proof.held;
    assertPendingOpeningCleanupRead(proof);
    const status: GuidedOpeningStatusV1 = { ...common(), state: "pending-cleanup", requestId: original.claim.requestId,
      executionId: original.claim.executionId, claimHash: original.claimHash,
      detail: "Exact cleanup evidence is retained. Source-color reservation retirement and the final cleanup commit remain pending; no media is selectable or approved. Use explicit cleanup recovery to finish this pending retirement, not another render or cleanup attempt.",
      timing: { generationStartedAt: original.claim.generationStartedAt, engineElapsedMs: Number(proof.attempt.stop.receipt.elapsedMs),
        cleanupElapsedMs: null, elapsedStatus: "completed", coverage: "recorded-owned-attempt-only" } };
    return { status, proof };
  }
  return { status: claimed(held, reads), proof: undefined };
}

function cleaned(dir: string, reads: typeof guidedOpeningStatusReads): GuidedOpeningStatusV1 {
  const observed = reads.cleanup(dir), held = observed.held, failed = observed.evidence.stop.receipt.status === "failed";
  return { ...common(), state: failed ? "failed" : "unavailable", requestId: held.claim.requestId,
    executionId: held.claim.executionId, claimHash: held.claimHash,
    detail: failed ? "The private opening attempt failed; exact owned resources were reconciled. No opening, body or final is approved."
      : "Exact owned resources were reconciled. Current media selection is not yet qualified; no opening is available for review.",
    timing: { generationStartedAt: held.claim.generationStartedAt, engineElapsedMs: Number(observed.evidence.stop.receipt.elapsedMs),
      cleanupElapsedMs: Number(observed.evidence.output.elapsedMs), elapsedStatus: "completed", coverage: "recorded-owned-attempt-only" } };
}

function ready(dir: string, reads: typeof guidedOpeningStatusReads): GuidedOpeningStatusV1 {
  let selected: ReturnType<typeof readSelectedOpeningMedia>;
  try { selected = reads.selection(dir); }
  catch (error) {
    return { ...common(), state: "unavailable", requestId: null, executionId: null, claimHash: null,
      detail: `A retained opening selection could not be verified against the current journal/cleanup/result lineage; no media is selectable. ${String(error).slice(0, 300)}`,
      timing: { ...UNAVAILABLE_TIMING } };
  }
  const { held, observed } = selected, sourceColor = selected.fact.schemaVersion === 2;
  let approval: ReturnType<typeof readGuidedOpeningApproval>;
  try { approval = reads.approval(dir, selected.selectionHash, selected); }
  catch (error) {
    return { ...common(), state: "unavailable", requestId: null, executionId: null, claimHash: null,
      detail: `A retained opening approval does not bind the current exact selection; nothing is approved or selectable until it is resolved. ${String(error).slice(0, 300)}`,
      timing: { ...UNAVAILABLE_TIMING } };
  }
  const journal = reads.job(dir);
  const status: GuidedOpeningStatusV1 = { ...common(), state: "ready-for-review", requestId: held.claim.requestId, executionId: held.claim.executionId, claimHash: held.claimHash,
    openingApproved: approval !== null, approval: approval ? { approvalHash: approval.approvalHash, approvedAt: approval.approvedAt } : null,
    journal: { token: journal.job.token, sha256: journal.sha256 },
    selectionHash: selected.selectionHash, receiptHash: selected.receiptHash, receiptSha256: selected.receiptSha256,
    selectionQualifiedAt: selected.selectionQualifiedAt, sourceFreshness: selected.sourceFreshness,
    media: openingMediaDescriptors(dir, selected.selectionHash, selected.rows),
    detail: approval
      ? "The operator approved this exact opening. Full-body generation, independent visual/listening review of the whole program, and delivery remain separate, unstarted work."
      : "Exact verified private opening media is available for mechanical review playback. Source bytes were not rechecked by this status; human opening review, independent visual/listening review, body generation and delivery remain separate.",
    timing: { generationStartedAt: held.claim.generationStartedAt, engineElapsedMs: Number(observed.evidence.stop.receipt.elapsedMs),
      cleanupElapsedMs: Number(observed.evidence.output.elapsedMs), elapsedStatus: "completed", coverage: "recorded-owned-attempt-only" } };
  if (sourceColor) {
    const check = () => {
      assertOpeningSelectionMetadata(selected);
      if (journal.sha256 !== observed.sha256) throw new Error("Source-color opening status journal changed");
      if (approval) assertSourceColorOpeningApprovalSummaryMetadata(approval);
    };
    check(); sourceStatusProofs.set(status, check);
  }
  return status;
}

/** Existing unclaimed selection/cleanup ordering; neither route is a fallback for current ownership. */
function unclaimed(dir: string, reads: typeof guidedOpeningStatusReads, before: ReturnType<typeof observeHumanCutJob>): GuidedOpeningStatusV1 {
  if (before.job.guidedHandoffV2?.openingMediaSelectionHash) return ready(dir, reads);
  if (before.job.guidedHandoffV2?.openingCleanupHash) return cleaned(dir, reads);
  return { ...common(), state: "unavailable", requestId: null, executionId: null, claimHash: null,
    detail: "No current verified opening media has been selected. Check opening launch eligibility; full-body generation is a separate unfinished step.", timing: { ...UNAVAILABLE_TIMING } };
}

/** Honest current ownership/status only. A newer claim always outranks any older selection or cleanup. */
export function readGuidedOpeningStatus(dir: string, reads = guidedOpeningStatusReads): GuidedOpeningStatusV1 {
  const before = reads.job(dir), beforeHash = before.sha256, beforeClaimHash = before.job.guidedHandoffV2?.openingExecutionClaimHash;
  parseGuidedWorkflowV2(before.job.ctx.workflowV2);
  let result: GuidedOpeningStatusV1;
  let pendingProof: ReturnType<typeof readPendingOpeningCleanup> | undefined;
  if (beforeClaimHash) {
    const observed = pending(dir, reads); result = observed.status; pendingProof = observed.proof;
  } else result = unclaimed(dir, reads, before);
  const current = reads.job(dir);
  if (before.sha256 !== beforeHash || before.job.guidedHandoffV2?.openingExecutionClaimHash !== beforeClaimHash
      || current.sha256 !== beforeHash) throw new Error("Opening status changed during observation");
  sourceStatusProofs.get(result)?.();
  if (pendingProof) {
    if (pendingProof.pendingJournalHash !== beforeHash || pendingProof.held.claimHash !== beforeClaimHash
        || pendingProof.fact.claimHash !== beforeClaimHash) throw new Error("Opening status pending cleanup names another original journal or claim");
    assertPendingOpeningCleanupRead(pendingProof);
  }
  return result;
}
