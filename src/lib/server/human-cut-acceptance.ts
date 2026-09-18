import path from "node:path";
import { randomUUID } from "node:crypto";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { currentCutReview, type CurrentCutReview } from "@/app/api/producer/cut-review/state";
import { verifyCutPreviewSources } from "@/app/api/producer/auto-edit/cut-preview-verification";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { assertCutApprovalRequestCurrent } from "@/app/api/producer/auto-edit/cut-approval-request";
import { guardProjectMutation, mutationProjectRoot, type CheckpointVerification } from "@/app/api/_lib/project-mutation";
import { parseHumanCutRetry, parseHumanCutSubmission, type HumanCutAcceptanceV1,
  type HumanCutSubmissionV1 } from "@/lib/producer/contracts/human-cut-acceptance";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { autoEditAuthoritySnapshot } from "./auto-edit-authority-snapshot";
import { acquireAutoEditLaunchLease } from "./auto-edit-launch-lock";
import { autoEditJobPath } from "./auto-edit-job-persistence";
import { launchDetachedAutoEditWorker } from "./auto-edit-worker-launcher";
import { timedStage } from "./stage-timing";
import { withStageTimingContext } from "./stage-timing-context";
import type { ProjectMutationLease } from "./project-mutation-lease";
import { activeHumanCutAcceptance, assertHumanCutContext, createHumanCutIndex, humanCutAuthorityContext,
  humanCutContinuationContextHash, observeHumanCutJob, readHumanCutAcceptance, readHumanCutActivation, verifyHumanCutPreview,
  writeHumanCutAcceptance } from "./human-cut-acceptance-store";
import { beginHumanCutAttempt, commitHumanCutAcceptance, committedSubmissionHash, failHumanCutAttempt,
  finishHumanCutAttempt, type HumanCutAttempt } from "./human-cut-acceptance-attempts";
import { prepareHumanCutContinuation, recordHumanCutLaunchResult } from "./human-cut-continuation";

export class HumanCutAcceptanceError extends Error {
  constructor(message: string, readonly status = 409, readonly cutAccepted = false) { super(message); }
}

interface AcceptanceDependencies {
  review: typeof currentCutReview;
  verifySources: typeof verifyCutPreviewSources;
  launch: typeof launchDetachedAutoEditWorker;
  fault?: (point: "after-fact" | "after-commit" | "before-launch") => void;
}
const defaults: AcceptanceDependencies = { review: currentCutReview,
  verifySources: verifyCutPreviewSources, launch: launchDetachedAutoEditWorker };

/** Verified historical acceptance + current exact context, not a fresh source-byte or final-quality claim. */
export function readAcceptedCutStatus(value: unknown) {
  const dir = canonicalProducerDir(value), observed = observeHumanCutJob(dir);
  const fact = activeHumanCutAcceptance(observed.job);
  const activation = readHumanCutActivation(observed.job, fact);
  verifyHumanCutPreview(observed.job, fact);
  if (observeHumanCutJob(dir).sha256 !== observed.sha256) throw new HumanCutAcceptanceError("Accepted cut changed during status readback");
  return { ok: true as const, cutAccepted: true as const, state: observed.job.status,
    acceptanceHash: observed.job.cutAcceptance!.acceptanceHash, requestHash: fact.request.requestHash,
    expectedToken: observed.job.token, previewAttempt: fact.preview.previewAttempt,
    continuationAttempt: observed.job.attempts, workerPid: observed.job.workerPid ?? null,
    canRetryContinuation: observed.job.status === "cut_accepted", scope: fact.scope,
    waitStoppedAt: activation?.waitStoppedAt ?? null, decisionSubmittedAt: fact.submittedAt,
    timingState: activation ? "verified-activation" as const : "unavailable-legacy-activation" as const,
    acceptanceState: "accepted" as const,
    caveat: "Historical human acceptance of the bound cut only, not final approval or a fresh source-byte check. Current cut identity and source bytes are reverified before continuation; all visual, audio and delivery gates remain required." };
}

/** Recover only the already recorded human submission; reading cannot create or accept a decision. */
export function readPendingHumanCutDecision(value: unknown) {
  const dir = canonicalProducerDir(value), observed = observeHumanCutJob(dir), prior = observed.job.cutAcceptanceAttempt;
  if (observed.job.status !== "awaiting_cut_approval" || observed.job.cutAcceptance || prior?.state !== "verifying") {
    throw new HumanCutAcceptanceError("Only a pending, previously submitted cut decision can be recovered");
  }
  const review = currentCutReview(dir);
  const file = path.join(dir, "human-cut-attempts", prior.idempotencyKey, "submission.json");
  const stored = readCutPreviewObject(file), row = stored.value;
  if (Object.keys(row).sort().join(",") !== "decisionHash,kind,producerDir,schemaVersion,submission"
      || row.schemaVersion !== 1 || row.kind !== "human-cut-submission" || row.producerDir !== dir
      || row.decisionHash !== prior.decisionHash) throw new HumanCutAcceptanceError("The recorded human submission is malformed or no longer bound");
  const submission = parseHumanCutSubmission(row.submission);
  if (submission.idempotencyKey !== prior.idempotencyKey || canonicalJsonSha256(submission) !== prior.decisionHash) {
    throw new HumanCutAcceptanceError("The recorded human decision identity changed; no replacement is inferred");
  }
  matchSubmission(review, submission);
  if (observeHumanCutJob(dir).sha256 !== observed.sha256 || readCutPreviewObject(file).sha256 !== stored.sha256) {
    throw new HumanCutAcceptanceError("The pending human decision changed during recovery readback");
  }
  return { ok: true as const, scope: "previously-submitted-human-cut-decision-not-new-approval" as const,
    requestHash: review.request.requestHash, submission };
}

function postResult(dir: string, replayed: boolean, verified?: HumanCutAcceptanceV1) {
  const observed = observeHumanCutJob(dir), fact = verified ?? activeHumanCutAcceptance(observed.job);
  if (verified && observed.job.cutAcceptance?.acceptanceHash !== canonicalJsonSha256(verified)) {
    throw new HumanCutAcceptanceError("Accepted worker handoff changed its immutable decision", 409, true);
  }
  if (observed.job.status !== "cut_accepted" && observed.job.status !== "running") {
    throw new HumanCutAcceptanceError(`The cut remains accepted, but its worker is ${observed.job.status}. Refresh project status and use its explicit recovery action.`, 409, true);
  }
  return { ok: true as const, cutAccepted: true as const, state: observed.job.status, scope: fact.scope,
    acceptanceHash: observed.job.cutAcceptance!.acceptanceHash, requestHash: fact.request.requestHash,
    previewAttempt: fact.preview.previewAttempt, continuationAttempt: observed.job.attempts, replayed };
}

function matchSubmission(review: CurrentCutReview, submission: HumanCutSubmissionV1): void {
  if (review.job.token !== submission.expectedToken || review.request.requestHash !== submission.requestHash
      || review.receipt.executionKey !== submission.executionKey || review.receipt.receiptHash !== submission.receiptHash
      || review.receipt.media.sha256 !== submission.mediaSha256) {
    throw new HumanCutAcceptanceError("This submission does not name the exact current paused cut and playable preview");
  }
}

function acquireMutation(dir: string, checkpointVerification: CheckpointVerification): ProjectMutationLease {
  const launch = acquireAutoEditLaunchLease(dir);
  if (!launch) throw new HumanCutAcceptanceError("Another Auto Edit launch is changing this project; retry after it finishes");
  try {
    const guarded = guardProjectMutation({ projectRoot: mutationProjectRoot(dir), producerDir: dir,
      operation: "accepting the reviewed cut", checkpointVerification });
    if (!guarded.lease) throw new HumanCutAcceptanceError("The project is busy or requires reconciliation; cut acceptance cannot start");
    return guarded.lease;
  } finally { launch.release(); } // Never carry this expiring lock across asynchronous source hashing.
}

function acceptanceFact(attempt: HumanCutAttempt, review: CurrentCutReview, decision: HumanCutSubmissionV1): HumanCutAcceptanceV1 {
  const { job, request, receipt } = review, now = new Date().toISOString();
  return { schemaVersion: 1, kind: "human-cut-acceptance", policyVersion: 1, scope: "human-cut-only-not-delivery",
    actor: "local-operator", producerDir: job.ctx.dir, decision, decisionHash: canonicalJsonSha256(decision),
    originalJobToken: attempt.before.job.token, originalJobHash: attempt.before.sha256,
    acceptedContextHash: canonicalJsonSha256(job.ctx), continuationContextHash: humanCutContinuationContextHash(job.ctx),
    request, authorityContext: humanCutAuthorityContext(autoEditAuthoritySnapshot(job.ctx)),
    preview: { executionKey: receipt.executionKey, receiptHash: receipt.receiptHash, mediaSha256: receipt.media.sha256,
      runId: receipt.runId, previewAttempt: receipt.attempt, manifestHash: receipt.manifestHash,
      sourceSetDigest: receipt.sourceSetDigest, sourceSetReceiptHash: receipt.sourceSetReceiptHash,
      toolchainHash: receipt.toolchainHash, audioClockHash: receipt.audioClockHash },
    sourceVerification: "fresh-admitted-bytes-passed", waitStartedAt: attempt.waitStartedAt,
    submittedAt: attempt.attempt.receivedAt, verificationStartedAt: attempt.attempt.startedAt,
    verifiedAt: now, acceptedAt: now, verificationExecutionId: attempt.attempt.executionId,
    continuationToken: randomUUID(), continuationAttempt: receipt.attempt + 1 };
}

async function launchPending(dir: string, dependencies: AcceptanceDependencies) {
  const job = prepareHumanCutContinuation(dir), started = performance.now();
  try {
    dependencies.fault?.("before-launch");
    const workerPid = await timedStage(dir, "human_cut_continuation_launch", () => dependencies.launch(autoEditJobPath(dir)));
    try { recordHumanCutLaunchResult(job, { state: "running", workerPid, elapsedMs: performance.now() - started }); } catch { /* telemetry only */ }
    return { state: "running" as const, workerPid };
  } catch (error) {
    try { recordHumanCutLaunchResult(job, { state: "launch-pending", error: String(error), elapsedMs: performance.now() - started }); } catch { /* retain original error */ }
    throw new HumanCutAcceptanceError(`The cut is accepted, but continuation was not confirmed: ${String(error)}. Use Retry continuation.`, 409, true);
  }
}

async function verifyAndCommit(input: { dir: string; submission: HumanCutSubmissionV1; receivedAt: string;
  lease: ProjectMutationLease }, dependencies: AcceptanceDependencies) {
  const guard = cutPreviewLeaseGuard(input.dir, input.lease);
  const initial = dependencies.review(input.dir); matchSubmission(initial, input.submission);
  const before = observeHumanCutJob(input.dir);
  const attempt = beginHumanCutAttempt({ ...input, before });
  let committed = false;
  try {
    const verifyingHash = observeHumanCutJob(input.dir).sha256;
    await dependencies.verifySources({ job: before.job, request: initial.request,
      executionKey: initial.receipt.executionKey, lease: input.lease });
    guard();
    const reviewed = dependencies.review(input.dir); matchSubmission(reviewed, input.submission);
    if (observeHumanCutJob(input.dir).sha256 !== verifyingHash) throw new HumanCutAcceptanceError("Paused cut changed while verifying sources");
    const priorHash = committedSubmissionHash(attempt.submissionDirectory);
    const fact = priorHash ? readHumanCutAcceptance(input.dir, priorHash) : acceptanceFact(attempt, reviewed, input.submission);
    if (fact.decisionHash !== canonicalJsonSha256(input.submission)) throw new HumanCutAcceptanceError("The immutable decision differs from this submission");
    assertHumanCutContext(reviewed.job, fact); verifyHumanCutPreview(reviewed.job, fact);
    const acceptanceHash = priorHash ?? writeHumanCutAcceptance(input.dir, fact);
    createHumanCutIndex(path.join(attempt.submissionDirectory, "accepted.json"), { acceptanceHash });
    dependencies.fault?.("after-fact"); guard();
    const launch = acquireAutoEditLaunchLease(input.dir);
    if (!launch) throw new HumanCutAcceptanceError("Another launch is active; the acceptance fact is inert until its exact checkpoint can be committed");
    try {
      commitHumanCutAcceptance({ attempt, expectedJournalHash: verifyingHash, acceptanceHash }); committed = true;
      finishHumanCutAttempt(attempt, { state: "accepted", acceptanceHash });
      dependencies.fault?.("after-commit");
      await launchPending(input.dir, dependencies);
      return postResult(input.dir, false, fact); // No whole-media/pipeline rehash while the child waits for our lease.
    } finally { launch.release(); }
  } catch (error) {
    // A rename/fsync error may be reported after the durable pointer became visible.
    // Reobserve before classifying failure; never turn an activated cut into a new waiting attempt.
    const current = observeHumanCutJob(input.dir).job;
    if (current.cutAcceptance) committed = activeHumanCutAcceptance(current).decisionHash === attempt.attempt.decisionHash;
    if (committed) throw new HumanCutAcceptanceError(
      `Cut accepted; continuation requires Retry continuation: ${error instanceof Error ? error.message : String(error)}`, 409, true);
    guard(); failHumanCutAttempt(attempt, error); throw error;
  }
}

async function withAcceptanceLease<T>(dir: string, verification: CheckpointVerification,
  action: (lease: ProjectMutationLease) => Promise<T>): Promise<T> {
  const lease = acquireMutation(dir, verification);
  let release = true;
  try { return await action(lease); }
  catch (error) {
    if (error instanceof CutPreviewProcessError && !error.details.groupStopped) release = false;
    throw error instanceof HumanCutAcceptanceError ? error
      : new HumanCutAcceptanceError(`${String(error)}${release ? "" : "; source verifier cleanup is unresolved; project lease retained for recovery"}`);
  } finally { if (release) lease.release(); }
}

/** Exact-v1 only: no edited plan, new treatment brief, implicit playback attestation or approval upgrade. */
export async function acceptGuidedCut(input: { dir: unknown; submission: unknown }, overrides: Partial<AcceptanceDependencies> = {}) {
  const submission = parseHumanCutSubmission(structuredClone(input.submission)), receivedAt = new Date().toISOString();
  const dir = canonicalProducerDir(input.dir), before = observeHumanCutJob(dir), dependencies = { ...defaults, ...overrides };
  if (before.job.ctx.workflowV2) throw new HumanCutAcceptanceError("V2 requires its explicit accept-cut-and-await-treatment action; v1 saved-brief acceptance is unavailable");
  if (before.job.cutAcceptance) {
    const fact = activeHumanCutAcceptance(before.job);
    if (canonicalJsonSha256(fact.decision) !== canonicalJsonSha256(submission)) throw new HumanCutAcceptanceError("A different human decision is already active");
    readAcceptedCutStatus(dir);
    return postResult(dir, true); // Lost-response replay is read-only and never spawns again.
  }
  return withStageTimingContext({ runId: before.job.artifactToken ?? before.job.token,
    attemptId: `human-cut:${randomUUID()}`, attemptNo: before.job.attempts }, () => timedStage(dir, "human_cut_acceptance",
    () => withAcceptanceLease(dir, { workflowVersion: 1, action: "accept-cut-and-continue",
      expectedStatus: "awaiting_cut_approval", expectedToken: submission.expectedToken, expectedJournalHash: before.sha256 },
    (lease) => verifyAndCommit({ dir, submission, receivedAt, lease }, dependencies))));
}

export async function retryAcceptedCutContinuation(input: { dir: unknown; submission: unknown }, overrides: Partial<AcceptanceDependencies> = {}) {
  const submission = parseHumanCutRetry(input.submission), dir = canonicalProducerDir(input.dir);
  const before = observeHumanCutJob(dir), fact = activeHumanCutAcceptance(before.job), dependencies = { ...defaults, ...overrides };
  if (before.job.cutAcceptance!.acceptanceHash !== submission.acceptanceHash || fact.request.requestHash !== submission.requestHash) {
    throw new HumanCutAcceptanceError("This retry does not name the active immutable cut acceptance");
  }
  if (before.job.status !== "cut_accepted") { readAcceptedCutStatus(dir); return postResult(dir, true); }
  try { return await withStageTimingContext({ runId: before.job.artifactToken ?? before.job.token,
    attemptId: `human-cut-retry:${randomUUID()}`, attemptNo: before.job.attempts }, () => timedStage(dir, "human_cut_continuation_retry",
    () => withAcceptanceLease(dir, { workflowVersion: 1, action: "retry-cut-continuation",
      expectedStatus: "cut_accepted", expectedToken: before.job.token, expectedJournalHash: before.sha256 }, async (lease) => {
      const guard = cutPreviewLeaseGuard(dir, lease), observed = observeHumanCutJob(dir);
      if (observed.sha256 !== before.sha256) throw new HumanCutAcceptanceError("Accepted continuation changed before retry");
      assertCutApprovalRequestCurrent(observed.job, fact.request); verifyHumanCutPreview(observed.job, fact);
      await dependencies.verifySources({ job: observed.job, request: fact.request, executionKey: fact.preview.executionKey, lease });
      guard(); assertCutApprovalRequestCurrent(observed.job, fact.request);
      if (observeHumanCutJob(dir).sha256 !== before.sha256) throw new HumanCutAcceptanceError("Accepted continuation changed during source verification");
      const launch = acquireAutoEditLaunchLease(dir);
      if (!launch) throw new HumanCutAcceptanceError("Another launch is active; retry continuation after it finishes", 409, true);
      try { await launchPending(dir, dependencies); return postResult(dir, false, fact); }
      finally { launch.release(); }
    }))); } catch (error) {
    throw new HumanCutAcceptanceError(error instanceof Error ? error.message : String(error),
      error instanceof HumanCutAcceptanceError ? error.status : 409, true);
  }
}
