import path from "node:path";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { verifyCutPreviewSources } from "@/app/api/producer/auto-edit/cut-preview-verification";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseGuidedCutSubmissionV2, parseGuidedHandoffPointerV2 } from "@/lib/producer/contracts/guided-workflow-v2";
import { exactKeys } from "@/lib/producer/contracts/validation";
import { atomicWriteJsonSync } from "./atomic-file";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { withAutoEditJobLock } from "./auto-edit-job-lock";
import { autoEditJobPath, parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import type { AutoEditJob } from "./auto-edit-job-types";
import type { ProjectMutationLease } from "./project-mutation-lease";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { timedStage } from "./stage-timing";
import { withStageTimingContext } from "./stage-timing-context";
import { acquireGuidedMutation, buildGuidedCutDecision, finishGuidedOperation, guidedOperation, observeGuidedCutV2, readGuidedExecution,
  parseGuidedCutDecision, readGuidedObject, strictGuidedTimestamp, writeGuidedObject,
  type GuidedCutObservation } from "./guided-cut-v2-store";
import { commitGuidedPictureLock, prepareGuidedPictureLock, readGuidedPictureLock } from "./guided-picture-lock-v2";
import { assertBootstrapQuiescence } from "./guided-project-bootstrap-quiescence";

interface GuidedCutDependencies {
  verifySources: typeof verifyCutPreviewSources;
  fault?: (point: "after-decision" | "after-genesis" | "after-activation" | "after-commit") => void;
}

function assertDecisionCurrent(cut: GuidedCutObservation) {
  const pointer = parseGuidedHandoffPointerV2(cut.job.guidedHandoffV2);
  const fact = parseGuidedCutDecision(readGuidedObject(cut.job.ctx.dir, pointer.cutDecisionHash));
  if (fact.producerDir !== cut.job.ctx.dir || fact.contextHash !== canonicalJsonSha256(cut.job.ctx)
      || fact.nextToken !== cut.job.token || fact.runId !== cut.receipt.runId || fact.previewAttempt !== cut.job.attempts
      || canonicalJsonSha256(fact.request) !== canonicalJsonSha256(cut.request)
      || fact.sourceSetDigest !== cut.receipt.sourceSetDigest || fact.sourceSetReceiptHash !== cut.receipt.sourceSetReceiptHash
      || fact.submission.executionKey !== cut.receipt.executionKey || fact.submission.receiptHash !== cut.receipt.receiptHash
      || fact.submission.mediaSha256 !== cut.receipt.media.sha256) throw new Error("Active v2 cut decision no longer binds the current cut");
  const original = readCutPreviewObject(path.join(cut.job.ctx.dir, "human-cut-job-snapshots", `${fact.originalJobHash}.json`));
  const prior = parseAutoEditJobRecord(original.value);
  if (original.sha256 !== fact.originalJobHash || prior.status !== "awaiting_cut_approval"
      || prior.token !== fact.submission.expectedToken || prior.guidedHandoffV2
      || canonicalJsonSha256(prior.ctx) !== fact.contextHash || strictGuidedTimestamp(prior.cutApprovalWaitStartedAt) > fact.submittedAt) {
    throw new Error("V2 cut decision lost its original journal evidence");
  }
  return { pointer, fact };
}

function activationCurrent(cut: GuidedCutObservation, identity: ReturnType<typeof assertDecisionCurrent>) {
  const { pointer, fact } = identity, row = readGuidedObject(cut.job.ctx.dir, pointer.cutActivationHash);
  const keys = ["schemaVersion", "kind", "decisionHash", "originalJobHash", "revisionHash", "executionId",
    "executionStartHash", "decisionSubmittedAt", "executionReceivedAt", "startedAt", "verifiedAt", "recordedAt", "sourceVerification"];
  exactKeys(row, keys, keys, "GuidedCutActivationV2");
  const clock = [row.decisionSubmittedAt, row.executionReceivedAt, row.startedAt, row.verifiedAt, row.recordedAt].map(strictGuidedTimestamp);
  if (row.schemaVersion !== 2 || row.kind !== "guided-cut-activation" || row.decisionHash !== pointer.cutDecisionHash
      || row.originalJobHash !== fact.originalJobHash || row.revisionHash !== pointer.pictureLockedRevisionHash
      || row.sourceVerification !== "fresh-full-admitted-bytes" || clock.some((at, index) => index > 0 && at < clock[index - 1])
      || clock[0] !== fact.submittedAt || clock[4] > cut.job.updatedAt) throw new Error("V2 cut activation is not exact execution evidence");
  const started = readGuidedExecution({ dir: cut.job.ctx.dir, id: fact.submission.idempotencyKey,
    executionId: row.executionId, hash: row.executionStartHash });
  if (started.submissionHash !== canonicalJsonSha256(fact.submission) || started.firstReceivedAt !== row.decisionSubmittedAt
      || started.receivedAt !== row.executionReceivedAt || started.startedAt !== row.startedAt) throw new Error("V2 cut activation execution changed");
  return row;
}

/** Strong read-only proof of accepted cut; no fresh source-byte claim and no migration. */
export function readGuidedCutV2(dir: string) {
  const cut = observeGuidedCutV2(dir);
  if (!["awaiting_treatment_brief", "treatment_admitted"].includes(cut.job.status)) throw new Error("V2 cut is not accepted for treatment");
  const identity = assertDecisionCurrent(cut), activation = activationCurrent(cut, identity);
  const revision = readGuidedPictureLock(dir, identity.pointer.pictureLockedRevisionHash, identity.pointer.cutDecisionHash, cut);
  if (revision.pictureLockHash !== cut.request.pictureLockHash || revision.timelineMapHash !== cut.request.timelineMapHash
      || revision.sourceSnapshotSetHash !== cut.receipt.sourceSetDigest || revision.manifestHash !== cut.manifest.sha256) {
    throw new Error("V2 cut revision no longer names the actual cut/source authority");
  }
  if (observeHumanCutJob(dir).sha256 !== cut.sha256) throw new Error("V2 cut changed during accepted readback");
  assertBootstrapQuiescence(cut.job);
  return { ...cut, ...identity, activation, revision };
}

/** Shared synchronous CAS only; caller keeps the real lease across all asynchronous work. */
export function commitGuidedJob(input: { beforeHash: string; job: AutoEditJob; guard: () => void }): AutoEditJob {
  return withAutoEditJobLock(autoEditJobPath(input.job.ctx.dir), () => {
    input.guard();
    assertBootstrapQuiescence(input.job);
    if (observeHumanCutJob(input.job.ctx.dir).sha256 !== input.beforeHash) throw new Error("V2 guided journal compare-and-swap lost");
    const parsed = parseAutoEditJobRecord(input.job);
    input.guard();
    assertBootstrapQuiescence(parsed);
    atomicWriteJsonSync(autoEditJobPath(parsed.ctx.dir), parsed);
    return parsed;
  });
}

function cutSubmissionMatches(cut: GuidedCutObservation, submission: ReturnType<typeof parseGuidedCutSubmissionV2>): void {
  if (cut.job.status !== "awaiting_cut_approval" || cut.job.guidedHandoffV2 || cut.sha256 !== submission.expectedJournalHash
      || cut.job.token !== submission.expectedToken || cut.request.requestHash !== submission.requestHash
      || cut.receipt.executionKey !== submission.executionKey || cut.receipt.receiptHash !== submission.receiptHash
      || cut.receipt.media.sha256 !== submission.mediaSha256) throw new Error("V2 cut submission is stale or names another checkpoint");
}

async function acceptNewV2Cut(input: { cut: GuidedCutObservation; submission: ReturnType<typeof parseGuidedCutSubmissionV2>;
  lease: ProjectMutationLease; receivedAt: string }, deps: GuidedCutDependencies) {
  const { cut, submission } = input, dir = cut.job.ctx.dir, guard = cutPreviewLeaseGuard(dir, input.lease);
  cutSubmissionMatches(cut, submission);
  const operation = guidedOperation({ dir, id: submission.idempotencyKey, submission, receivedAt: input.receivedAt });
  try {
    await deps.verifySources({ job: cut.job, request: cut.request, executionKey: cut.receipt.executionKey, lease: input.lease });
    guard(); const current = observeGuidedCutV2(dir); cutSubmissionMatches(current, submission);
    const verifiedAt = new Date().toISOString(), fact = buildGuidedCutDecision(current, submission, operation);
    const cutDecisionHash = writeGuidedObject(dir, fact); deps.fault?.("after-decision");
    const prepared = prepareGuidedPictureLock(current, cutDecisionHash);
    guard(); if (observeHumanCutJob(dir).sha256 !== current.sha256) throw new Error("V2 cut changed before genesis");
    const pictureLockedRevisionHash = withAutoEditJobLock(autoEditJobPath(dir), () => {
      guard(); if (observeHumanCutJob(dir).sha256 !== current.sha256) throw new Error("V2 genesis journal CAS lost");
      return commitGuidedPictureLock(prepared);
    });
    deps.fault?.("after-genesis");
    const now = new Date().toISOString(), start = readCutPreviewObject(path.join(operation.execution, "start.json"));
    const cutActivationHash = writeGuidedObject(dir, { schemaVersion: 2, kind: "guided-cut-activation",
      decisionHash: cutDecisionHash, originalJobHash: current.sha256, revisionHash: pictureLockedRevisionHash,
      executionId: operation.executionId, executionStartHash: start.sha256, decisionSubmittedAt: fact.submittedAt,
      executionReceivedAt: input.receivedAt,
      startedAt: operation.startedAt, verifiedAt, recordedAt: now, sourceVerification: "fresh-full-admitted-bytes" });
    deps.fault?.("after-activation");
    const job = commitGuidedJob({ beforeHash: current.sha256, guard, job: { ...current.job,
      token: fact.nextToken, artifactToken: current.job.artifactToken ?? current.job.token,
      status: "awaiting_treatment_brief", updatedAt: now, workerPid: undefined, workerIdentity: undefined,
      guidedHandoffV2: { schemaVersion: 2, cutDecisionHash, cutActivationHash, pictureLockedRevisionHash },
      message: "Cut accepted for a new treatment brief. Intro/body generation is not connected; no final is approved.",
      nextEventId: current.job.nextEventId + 1, events: [...current.job.events, { id: current.job.nextEventId, at: now,
        payload: { event: "guided_cut_accepted_v2", cutDecisionHash, cutActivationHash, userWaitEndedAt: fact.submittedAt,
          decisionSubmittedAt: fact.submittedAt, activationExecutionReceivedAt: input.receivedAt,
          retryGapClassification: "unclassified-not-human-wait", treatmentStarted: false } }].slice(-256) } });
    finishGuidedOperation(operation, { state: "accepted-cut-await-treatment", cutDecisionHash, cutActivationHash });
    deps.fault?.("after-commit");
    return { job, replayed: false };
  } catch (error) {
    try { finishGuidedOperation(operation, { state: "failed-or-incomplete", error: String(error).slice(0, 1000) }); } catch { /* retain primary error and earlier immutable result */ }
    throw error;
  }
}

/** Internal-only explicit v2 human decision; never launches, modifies intent, or approves delivery. */
export async function acceptGuidedCutV2(input: { dir: unknown; submission: unknown },
  overrides: Partial<GuidedCutDependencies> = {}) {
  const submission = parseGuidedCutSubmissionV2(structuredClone(input.submission)), receivedAt = new Date().toISOString();
  const dir = canonicalProducerDir(input.dir);
  const cut = observeGuidedCutV2(dir);
  if (cut.job.guidedHandoffV2) {
    const accepted = readGuidedCutV2(dir);
    if (canonicalJsonSha256(accepted.fact.submission) !== canonicalJsonSha256(submission)) throw new Error("Another v2 cut decision is already active");
    return { job: accepted.job, replayed: true }; // Historical exact replay; later treatment admission freshly rechecks all sources.
  }
  cutSubmissionMatches(cut, submission);
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "accept-cut-await-treatment",
    expectedStatus: "awaiting_cut_approval", expectedToken: submission.expectedToken, expectedJournalHash: submission.expectedJournalHash });
  try { return await withStageTimingContext({ runId: cut.receipt.runId, attemptId: `guided-v2-cut:${submission.idempotencyKey}`,
    attemptNo: cut.job.attempts }, () => timedStage(dir, "guided_v2_cut_acceptance", () =>
    acceptNewV2Cut({ cut, submission, lease, receivedAt }, { verifySources: verifyCutPreviewSources, ...overrides })));
  } finally { lease.release(); }
}
