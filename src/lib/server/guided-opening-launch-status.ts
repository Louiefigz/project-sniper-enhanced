import path from "node:path";
import { exactKeys, sha256, uuid } from "@/lib/producer/contracts/validation";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { openingMediaAuthority } from "./guided-opening-media-input";
import { openingDeadlineAdmission } from "./opening-deadline";
import { readGuidedOpeningStatus } from "./guided-opening-status";
import { readGuidedOpeningExecutionClaim } from "./guided-opening-claim";
import { readCommittedOpeningCleanup } from "./guided-opening-cleanup-store";
import { strictGuidedTimestamp } from "./guided-cut-v2-store";
import { readOpeningLaunchIntent, optionalLaunchRecord, openingControllerFiles, assertOpeningControllerTools } from "./guided-opening-launch-store";

export interface GuidedOpeningLaunchStatus {
  ok: true; state: "eligible" | "unavailable" | "launch-recorded" | "failed"; detail: string;
  request: null | { expectedToken: string; expectedJournalHash: string; proposalReadinessHash: string; treatmentDraftRevisionHash: string };
  receivedAt: string | null;
}

function unavailable(detail: string): GuidedOpeningLaunchStatus {
  return { ok: true, state: "unavailable", detail, request: null, receivedAt: null };
}

function recorded(held: NonNullable<ReturnType<typeof readOpeningLaunchIntent>>): GuidedOpeningLaunchStatus {
  const outcome = optionalLaunchRecord(path.join(held.root, "outcome.json"));
  if (!outcome) return { ok: true, state: "launch-recorded", request: null, receivedAt: held.intent.receivedAt,
    detail: "The opening launch is recorded. Its controller outcome is not confirmed; this is not proof it is running. Do not launch a duplicate. An interrupted attempt may require manual recovery." };
  const row = outcome.value, keys = ["schemaVersion", "kind", "intentHash", "executionId", "completedAt", "elapsedMs", "state", "error", "selectionHash"];
  exactKeys(row, keys, keys, "opening controller outcome"); strictGuidedTimestamp(row.completedAt);
  if (row.executionId !== null) uuid(row.executionId, "opening controller execution");
  if (row.schemaVersion !== 1 || row.kind !== "guided-opening-controller-outcome" || row.intentHash !== held.hash
      || String(row.completedAt) < held.intent.receivedAt || typeof row.elapsedMs !== "number" || !Number.isFinite(row.elapsedMs) || row.elapsedMs < 0) {
    throw new Error("Opening controller outcome is unbound");
  }
  if (row.state === "failed" && row.selectionHash === null && typeof row.error === "string" && row.error.length <= 2048) {
    return { ok: true, state: "failed", request: null, receivedAt: held.intent.receivedAt,
      detail: `Opening controller failed. Any unresolved resource claim remains locked; no automatic retry. ${row.error}`.slice(0, 2048) };
  }
  if (row.state !== "selected-not-approved" || row.error !== null || row.executionId === null) throw new Error("Unknown opening controller outcome");
  sha256(row.selectionHash, "controller selection");
  return unavailable("The controller returned, but no current independently verified selection is available. Recheck opening evidence; this record cannot approve media.");
}

/** Metadata only: no source rehash, renderer, cleanup, retry or approval is invoked by polling. */
export function readGuidedOpeningLaunchStatus(dir: string): GuidedOpeningLaunchStatus {
  const before = observeHumanCutJob(dir), pointer = before.job.guidedHandoffV2;
  let result: GuidedOpeningLaunchStatus;
  if (!before.job.ctx.workflowV2 || before.job.status !== "treatment_admitted") {
    result = unavailable("First accept the exact cut, submit a treatment brief, and qualify its proposal. Full-body generation remains a separate step.");
  } else if (pointer?.openingMediaSelectionHash && !pointer.openingExecutionClaimHash) {
    const status = readGuidedOpeningStatus(dir);
    result = unavailable(status.state === "ready-for-review" ? "An opening is available below. Review it before requesting further changes; generation is not approval." : status.detail);
  } else result = currentLaunch(dir, before);
  if (observeHumanCutJob(dir).sha256 !== before.sha256) throw new Error("Opening launch status changed during observation");
  return result;
}

function currentLaunch(dir: string, before: ReturnType<typeof observeHumanCutJob>): GuidedOpeningLaunchStatus {
  const pointer = before.job.guidedHandoffV2;
  const journalHash = pointer?.openingExecutionClaimHash ? readGuidedOpeningExecutionClaim(dir).claim.beforeJournalHash
    : pointer?.openingCleanupHash ? readCommittedOpeningCleanup(dir).held.claim.beforeJournalHash : before.sha256;
  const held = readOpeningLaunchIntent(dir, journalHash);
  if (held) return recorded(held);
  if (pointer?.openingExecutionClaimHash || pointer?.openingCleanupHash) return unavailable("Existing opening ownership or cleanup requires explicit resolution; no new UI launch is available.");
  try {
    const proposal = readGuidedProposalReadiness(dir); openingControllerFiles(proposal); openingMediaAuthority(proposal); assertOpeningControllerTools();
    if (!proposal.draftRevision || proposal.readiness.verdict !== "clean" || !proposal.pointer.treatmentDraftRevisionHash) {
      return unavailable("The treatment proposal has not passed the required readiness checks.");
    }
    const admission = openingDeadlineAdmission({ clockHash: proposal.clock.hash, startedAt: proposal.generationStartedAt }, Date.now());
    if (!admission.admitted) return unavailable("The original request no longer has enough opening and finish time reserved. Rechecking does not restart its clock.");
    return { ok: true, state: "eligible", receivedAt: null,
      detail: "Generate the qualified opening and transition context for human review. This launch does not generate or approve the full body or delivery.",
      request: { expectedToken: proposal.job.token, expectedJournalHash: proposal.sha256, proposalReadinessHash: proposal.readinessHash,
        treatmentDraftRevisionHash: proposal.pointer.treatmentDraftRevisionHash } };
  } catch (error) { return unavailable(`Opening launch is not qualified: ${String(error).slice(0, 1800)}`); }
}
