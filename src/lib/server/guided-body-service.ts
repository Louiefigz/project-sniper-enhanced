import path from "node:path";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { parseContinueApprovedOpening } from "@/lib/producer/contracts/guided-body-v1";
import { parseGuidedBodyRunResult, type GuidedBodyRunResult } from "@/lib/producer/contracts/guided-body-command-v1";
import { withFreshGuidedBodyAdmission, bodyClaimServices, type FreshBodyAdmission } from "./guided-body-claim";
import { captureBodyAttemptStart } from "./guided-body-deadline";
import { activateFreshGuidedBody } from "./guided-body-activation";
import { runActivatedBodyMedia, readOwnedBodyProcess } from "./guided-body-process";
import { reconcileGuidedBodyUnderLease } from "./guided-body-cleanup";
import { qualifyGuidedBodyUnderLease, readQualifiedBodyCandidate } from "./guided-body-readback";
import { readRecordedBodyAdmission, readGuidedBodyStatus } from "./guided-body-status";
import { createOpeningRecord } from "./guided-opening-process-activation";
import { canonicalJsonSha256 as hash } from "./auto-edit-hash";

export class BodyRequestConflictError extends Error { readonly code = "BODY_REQUEST_CONFLICT"; }

async function runFresh(context: FreshBodyAdmission) {
  const began = performance.now();
  try {
    const held = activateFreshGuidedBody(context);
    const phase = await runActivatedBodyMedia({ held, lease: context.lease, remainingMs: context.budget.remainingMs });
    const stopped = readOwnedBodyProcess(phase);
    // Mandatory cleanup runs after normal complete OR failed returns, with protected time and no new render credit.
    const cleanup = await reconcileGuidedBodyUnderLease(context.dir, context.lease);
    if (cleanup.state !== "cleanup-verified") throw new Error("Known Docker resources reconciled, but local ownership remains unresolved; retain the body claim");
    if (stopped.receipt.status !== "complete") throw new Error("Body worker failed; resources were reconciled but no candidate is qualified");
    context.budget.remainingMs();
    const candidate = await qualifyGuidedBodyUnderLease({ dir: context.dir, lease: context.lease, remainingMs: context.budget.remainingMs });
    const selected = readQualifiedBodyCandidate(context.dir); context.budget.remainingMs();
    return parseGuidedBodyRunResult({ ok: true, state: "private-candidate-qualified", replayed: false,
      requestId: held.activation.requestId, executionId: held.activation.executionId, admissionClaimHash: held.admission.claimHash,
      activationHash: held.activationHash, cleanupHash: cleanup.factHash, candidateHash: candidate.factHash,
      journalHash: candidate.current.sha256, candidate: selected.candidate, bodyApproved: false, deliveryApproved: false });
  } catch (error) {
    let clock: unknown;
    try { clock = context.budget.observe(); } catch (failure) { clock = { state: "unverified", error: String(failure).slice(0, 2000) }; }
    createOpeningRecord(path.join(context.operation.execution, "body-command-failed.json"), { schemaVersion: 1,
      kind: "guided-body-command-failure", error: String(error).slice(0, 4000), observedAt: new Date().toISOString(),
      elapsedMs: performance.now() - began, clock, claimRetained: true, bodyApproved: false, deliveryApproved: false });
    throw error;
  }
}

/** Foreground skill/CLI only. Exact request replay is read-only; no automatic retry, detached worker or new approval. */
export async function runGuidedBody(input: { dir: unknown; submission: unknown }): Promise<GuidedBodyRunResult> {
  const submission = parseContinueApprovedOpening(structuredClone(input.submission)), start = captureBodyAttemptStart();
  const dir = canonicalProducerDir(input.dir), existing = readRecordedBodyAdmission(dir);
  if (existing) {
    if (hash(existing.input.submission) !== hash(submission)) throw new BodyRequestConflictError("Another body request owns this checkpoint; no fresh execution permitted");
    return parseGuidedBodyRunResult({ ok: true, replayed: true, status: readGuidedBodyStatus(dir) });
  }
  const result = await withFreshGuidedBodyAdmission({ dir, submission }, runFresh, bodyClaimServices, start);
  if (!result.continuation) return parseGuidedBodyRunResult({ ok: true, replayed: true, status: readGuidedBodyStatus(dir) });
  return result.continuation;
}
