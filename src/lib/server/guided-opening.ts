import path from "node:path";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { verifyCutPreviewSources } from "@/app/api/producer/auto-edit/cut-preview-verification";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { GUIDED_OPENING_SCOPE, parseOpeningPreparationReceipt, parsePrepareGuidedOpening } from "@/lib/producer/contracts/guided-opening-v1";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { acquireGuidedMutation, guidedOperation, finishGuidedOperation, writeGuidedObject } from "./guided-cut-v2-store";
import { createHumanCutIndex, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { commitGuidedJob } from "./guided-cut-v2";
import { buildOpeningAuthority, assertOpeningSubmission, type OpeningReadiness } from "./guided-opening-authority";
import { readGuidedOpeningPreparation } from "./guided-opening-store";
import { timedStage } from "./stage-timing";
import { withStageTimingContext } from "./stage-timing-context";

interface Dependencies {
  /** Tripwire for the unavailable boundary; no source work is admitted until an actual adapter is wired. */
  verifySources: typeof verifyCutPreviewSources;
  fault?: (point: "after-authority-observation" | "after-receipt" | "after-commit") => void;
}
type Submission = ReturnType<typeof parsePrepareGuidedOpening>;
type Operation = ReturnType<typeof guidedOperation>;

/** Internal admission only; there is deliberately no injectable successful renderer or public launch. */
export async function prepareGuidedOpening(input: { dir: unknown; submission: unknown }, overrides: Partial<Dependencies> = {}) {
  const submission = parsePrepareGuidedOpening(structuredClone(input.submission)), receivedAt = new Date().toISOString();
  const dir = canonicalProducerDir(input.dir), proposal = readGuidedProposalReadiness(dir);
  if (proposal.pointer.openingExecutionClaimHash) throw new Error("Opening renderer ownership is unresolved; exact resource cleanup is required before prepare or replay");
  if (proposal.pointer.openingPreparationHash) {
    const prior = readGuidedOpeningPreparation(dir);
    if (prior.receipt.submission.idempotencyKey === submission.idempotencyKey) {
      if (canonicalJsonSha256(prior.receipt.submission) !== canonicalJsonSha256(submission)) throw new Error("Opening idempotency key conflicts with its exact original request");
      return { ...prior, replayed: true };
    }
  }
  assertOpeningSubmission(proposal, submission);
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "prepare-guided-opening", expectedStatus: "treatment_admitted",
    expectedToken: submission.expectedToken, expectedJournalHash: submission.expectedJournalHash });
  try {
    const operation = guidedOperation({ dir, id: submission.idempotencyKey, submission, receivedAt });
    return await withStageTimingContext({ runId: proposal.fact.runId, attemptId: `opening-preparation:${operation.executionId}`, attemptNo: proposal.job.attempts },
      () => timedStage(dir, "guided_opening_preparation", () => prepareUnderLease({ proposal, submission, operation, lease }, { verifySources: verifyCutPreviewSources, ...overrides })));
  } finally { lease.release(); }
}

function retained(dir: string, operation: Operation, name: string, value: unknown) {
  createHumanCutIndex(path.join(operation.execution, name), value); return writeGuidedObject(dir, value);
}

function observationDeadline() {
  const wall = Date.now(), mono = performance.now();
  return () => {
    const left = Math.floor(120_000 - Math.max(Date.now() - wall, performance.now() - mono));
    if (Date.now() < wall || left <= 0) throw new Error("Opening metadata observation deadline exceeded");
    return left;
  };
}

async function prepareUnderLease(input: { proposal: OpeningReadiness; submission: Submission; operation: Operation;
  lease: Awaited<ReturnType<typeof acquireGuidedMutation>> }, deps: Dependencies) {
  const { proposal, submission, operation, lease } = input, dir = proposal.job.ctx.dir;
  const leaseGuard = cutPreviewLeaseGuard(dir, lease), remainingMs = observationDeadline();
  const guard = () => { leaseGuard(); remainingMs(); };
  try {
    guard(); buildOpeningAuthority(proposal);
    // Known-unavailable cannot benefit from a full source rehash. No freshness or media claim is emitted.
    guard(); deps.fault?.("after-authority-observation");
    const current = readGuidedProposalReadiness(dir); assertOpeningSubmission(current, submission);
    const authority = buildOpeningAuthority(current); saveHumanCutJobSnapshot(dir, current);
    const inputHash = retained(dir, operation, "input.json", authority.input);
    const implementationHash = retained(dir, operation, "implementation.json", authority.implementation);
    const frameBindingsHash = authority.bindings ? retained(dir, operation, "frame-bindings.json", authority.bindings) : null;
    const receipt = parseOpeningPreparationReceipt({ schemaVersion: 1, kind: "guided-opening-preparation", scope: GUIDED_OPENING_SCOPE,
      submission, beforeJournalHash: current.sha256, executionId: operation.executionId,
      executionStartHash: readCutPreviewObject(path.join(operation.execution, "start.json")).sha256,
      inputHash, implementationHash, frameBindingsHash, clockHash: current.clock.hash, generationStartedAt: current.generationStartedAt,
      createdAt: new Date().toISOString(), state: "unsupported-before-render", blockerCodes: authority.blockerCodes,
      sourceObservation: "not-run-known-unsupported", renderBudget: "not-admitted-renderer-unavailable", media: null, executable: false, approved: false });
    const preparationHash = writeGuidedObject(dir, receipt); deps.fault?.("after-receipt"); guard();
    commitOpeningAttempt({ current, preparationHash, createdAt: receipt.createdAt, guard });
    finishGuidedOperation(operation, { state: receipt.state, preparationHash, generationStartedAt: current.generationStartedAt,
      excludedUserWaitMs: null, rendererStarted: false, renderBudget: receipt.renderBudget });
    deps.fault?.("after-commit"); return { ...readGuidedOpeningPreparation(dir), replayed: false };
  } catch (error) {
    try { finishGuidedOperation(operation, { state: "failed-or-incomplete", error: String(error).slice(0, 2000),
      generationStartedAt: proposal.generationStartedAt, excludedUserWaitMs: null, rendererStarted: false }); } catch { /* preserve immutable terminal outcome */ }
    throw error;
  }
}

function commitOpeningAttempt(input: { current: OpeningReadiness; preparationHash: string; createdAt: string; guard: () => void }) {
  const { current, preparationHash, createdAt, guard } = input, job = current.job;
  return commitGuidedJob({ beforeHash: current.sha256, guard, job: { ...job, updatedAt: createdAt,
    guidedHandoffV2: { ...current.pointer, openingPreparationHash: preparationHash },
    message: "Opening preparation retained as unsupported: the qualified private renderer is not connected. No preview, opening approval or body generation exists.",
    nextEventId: job.nextEventId + 1, events: [...job.events, { id: job.nextEventId, at: createdAt,
      payload: { event: "opening_preparation_unsupported", preparationHash, media: null, executable: false, acceptedRootUnchanged: true } }].slice(-256) } });
}
