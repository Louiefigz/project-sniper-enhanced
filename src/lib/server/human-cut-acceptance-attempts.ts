import path from "node:path";
import { randomUUID } from "node:crypto";
import { atomicWriteJsonSync } from "./atomic-file";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { withAutoEditJobLock } from "./auto-edit-job-lock";
import { autoEditJobPath, parseAutoEditJobRecord, StaleAutoEditWorkerError } from "./auto-edit-job-persistence";
import type { AutoEditJob } from "./auto-edit-job-types";
import { captureProcessIdentity } from "./process-liveness";
import { resumedJob } from "./auto-edit-job-builders";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseHumanCutAcceptanceAttempt, type HumanCutSubmissionV1, type HumanCutAcceptanceAttempt } from "@/lib/producer/contracts/human-cut-acceptance";
import { createHumanCutIndex, humanCutDirectory, observeHumanCutJob,
  readHumanCutAcceptance, saveHumanCutJobSnapshot, writeHumanCutActivation } from "./human-cut-acceptance-store";

export interface HumanCutAttempt {
  dir: string; directory: string; submissionDirectory: string;
  before: ReturnType<typeof observeHumanCutJob>; attempt: HumanCutAcceptanceAttempt;
  startedMono: number; waitStartedAt: string;
}

function eventJob(job: AutoEditJob, at: string, payload: Record<string, unknown>): AutoEditJob {
  return { ...job, updatedAt: at, nextEventId: job.nextEventId + 1,
    events: [...job.events, { id: job.nextEventId, at, payload }].slice(-256) };
}

export function humanCutWaitStartedAt(job: AutoEditJob): string {
  const at = job.cutApprovalWaitStartedAt ?? job.updatedAt;
  if (!Number.isFinite(Date.parse(at)) || new Date(at).toISOString() !== at) throw new Error("Human cut waiting clock is invalid");
  return at;
}

function sameJournal(dir: string, expectedHash: string): AutoEditJob {
  const observed = observeHumanCutJob(dir);
  if (observed.sha256 !== expectedHash) throw new StaleAutoEditWorkerError("Human cut checkpoint changed before its exact compare-and-swap");
  return observed.job;
}

export function humanCutSubmissionDirectory(dir: string, submission: HumanCutSubmissionV1): string {
  const root = humanCutDirectory(dir, "human-cut-attempts");
  const directory = humanCutDirectory(root, submission.idempotencyKey);
  createHumanCutIndex(path.join(directory, "submission.json"), {
    schemaVersion: 1, kind: "human-cut-submission", producerDir: dir,
    decisionHash: canonicalJsonSha256(submission), submission,
  });
  return directory;
}

/** Only the short journal CAS is locked; no source/media hashing or await occurs inside it. */
export function beginHumanCutAttempt(input: {
  dir: string; submission: HumanCutSubmissionV1; receivedAt: string;
  before: ReturnType<typeof observeHumanCutJob>;
}): HumanCutAttempt {
  const prior = input.before.job.cutAcceptanceAttempt;
  const orphan = prior?.state === "verifying" ? prior : null;
  const decisionHash = canonicalJsonSha256(input.submission);
  if (orphan && (orphan.idempotencyKey !== input.submission.idempotencyKey || orphan.decisionHash !== decisionHash
      || orphan.startedAt > input.receivedAt)) throw new Error("Incomplete verification can only retry its exact retained decision; a new decision cannot replace it");
  const submissionDirectory = humanCutSubmissionDirectory(input.dir, input.submission);
  const executionId = randomUUID(), startedAt = new Date().toISOString();
  const waitStartedAt = humanCutWaitStartedAt(input.before.job);
  if (input.receivedAt < waitStartedAt || input.receivedAt > startedAt) throw new Error("Human cut submission clock is stale or skewed");
  const attempt = parseHumanCutAcceptanceAttempt({ idempotencyKey: input.submission.idempotencyKey, executionId,
    decisionHash, receivedAt: orphan?.receivedAt ?? input.receivedAt, startedAt,
    state: "verifying", completedAt: null, error: null });
  const directory = humanCutDirectory(humanCutDirectory(submissionDirectory, "executions"), executionId);
  saveHumanCutJobSnapshot(input.dir, input.before);
  createHumanCutIndex(path.join(directory, "start.json"), { schemaVersion: 1, kind: "human-cut-verification-start",
    ...attempt, waitStartedAt, originalJobHash: input.before.sha256, owner: captureProcessIdentity(process.pid),
    ...(orphan ? { retryReceivedAt: input.receivedAt, priorIncompleteExecutionId: orphan.executionId,
      priorExecutionStatus: "incomplete-not-reclassified", gapClassification: "unobserved-not-human-wait" } : {}) });
  withAutoEditJobLock(autoEditJobPath(input.dir), () => {
    const job = sameJournal(input.dir, input.before.sha256);
    if (job.status !== "awaiting_cut_approval" || job.token !== input.submission.expectedToken || job.cutAcceptance) {
      throw new StaleAutoEditWorkerError("Only the exact waiting cut can begin human acceptance");
    }
    const updated = eventJob({ ...job, cutAcceptanceAttempt: attempt, cutApprovalWaitStartedAt: waitStartedAt,
      message: "Verifying the submitted cut and all admitted source bytes; the cut is not yet accepted." }, startedAt,
    { event: "cut_acceptance_submitted", executionId, requestHash: input.submission.requestHash,
      operatorSubmittedAt: attempt.receivedAt, waitStartedAt, userWaitEndedAt: attempt.receivedAt,
      ...(orphan ? { retryReceivedAt: input.receivedAt, priorIncompleteExecutionId: orphan.executionId,
        gapClassification: "unobserved-not-human-wait" } : {}) });
    atomicWriteJsonSync(autoEditJobPath(input.dir), updated);
  });
  return { dir: input.dir, directory, submissionDirectory, before: input.before, attempt,
    startedMono: performance.now(), waitStartedAt };
}

export function finishHumanCutAttempt(attempt: HumanCutAttempt, result: Record<string, unknown>): void {
  createHumanCutIndex(path.join(attempt.directory, "result.json"), { schemaVersion: 1,
    kind: "human-cut-verification-result", executionId: attempt.attempt.executionId,
    decisionHash: attempt.attempt.decisionHash, completedAt: new Date().toISOString(),
    elapsedMs: Math.max(0, performance.now() - attempt.startedMono), ...result });
}

/** Failed verification restarts a separate human wait, never a resumable failed worker. */
export function failHumanCutAttempt(attempt: HumanCutAttempt, error: unknown): void {
  const completedAt = new Date().toISOString(), message = String(error instanceof Error ? error.message : error).slice(0, 1000) || "Cut verification failed";
  finishHumanCutAttempt(attempt, { state: "failed", error: message });
  withAutoEditJobLock(autoEditJobPath(attempt.dir), () => {
    const current = observeHumanCutJob(attempt.dir).job;
    if (current.status !== "awaiting_cut_approval" || current.token !== attempt.before.job.token
        || current.cutAcceptanceAttempt?.executionId !== attempt.attempt.executionId) return;
    const failed = parseHumanCutAcceptanceAttempt({ ...attempt.attempt, state: "failed", completedAt, error: message });
    const updated = eventJob({ ...current, cutAcceptanceAttempt: failed, cutApprovalWaitStartedAt: completedAt,
      message: "The cut was not accepted. Verification failed; review the error before submitting again." }, completedAt,
    { event: "cut_acceptance_verification_failed", executionId: failed.executionId, error: message,
      verificationStartedAt: failed.startedAt, verificationCompletedAt: completedAt, userWaitStartedAt: completedAt });
    atomicWriteJsonSync(autoEditJobPath(attempt.dir), updated);
  });
}

/** The immutable acceptance fact must already exist; its journal reference alone activates it. */
export function commitHumanCutAcceptance(input: {
  attempt: HumanCutAttempt; expectedJournalHash: string; acceptanceHash: string;
}): AutoEditJob {
  const { attempt } = input;
  const fact = readHumanCutAcceptance(attempt.dir, input.acceptanceHash);
  const observed = observeHumanCutJob(attempt.dir), now = new Date().toISOString();
  if (observed.sha256 !== input.expectedJournalHash) throw new StaleAutoEditWorkerError("Human cut activation lost its verifying journal");
  const activationHash = writeHumanCutActivation({ observed, fact, acceptanceHash: input.acceptanceHash, recordedAt: now });
  return withAutoEditJobLock(autoEditJobPath(attempt.dir), () => {
    const current = sameJournal(attempt.dir, input.expectedJournalHash);
    if (current.status !== "awaiting_cut_approval" || current.token !== fact.originalJobToken
        || current.cutAcceptanceAttempt?.executionId !== attempt.attempt.executionId
        || current.cutApprovalRequest?.requestHash !== fact.request.requestHash
        || current.attempts + 1 !== fact.continuationAttempt
        || canonicalJsonSha256(current.ctx) !== fact.acceptedContextHash) {
      throw new StaleAutoEditWorkerError("Human cut acceptance lost the exact waiting checkpoint");
    }
    const resumed = resumedJob({ ctx: current.ctx, token: fact.continuationToken, snapshots: current.snapshots }, current, now);
    const accepted = eventJob({ ...resumed, status: "cut_accepted", checkpoint: "cut_reviewed", phase: "authoring",
      cutAcceptance: { acceptanceHash: input.acceptanceHash, activationHash }, cutAcceptanceAttempt: undefined,
      message: "Cut accepted. The visual continuation is waiting for a confirmed worker; this is not an approved final." }, now,
    { event: "human_cut_accepted", acceptanceHash: input.acceptanceHash, activationHash, requestHash: fact.request.requestHash,
      operatorSubmittedAt: attempt.attempt.receivedAt, decisionSubmittedAt: fact.submittedAt,
      waitStartedAt: attempt.waitStartedAt, userWaitEndedAt: attempt.attempt.receivedAt,
      verificationExecutionId: attempt.attempt.executionId, acceptedAt: now, previewAttempt: fact.preview.previewAttempt,
      continuationAttempt: fact.continuationAttempt });
    parseAutoEditJobRecord(accepted);
    atomicWriteJsonSync(autoEditJobPath(attempt.dir), accepted);
    return accepted;
  });
}

export function committedSubmissionHash(directory: string): string | null {
  try {
    const row = readCutPreviewObject(path.join(directory, "accepted.json")).value;
    if (Object.keys(row).length !== 1 || typeof row.acceptanceHash !== "string" || !/^[a-f0-9]{64}$/.test(row.acceptanceHash)) {
      throw new Error("Human cut submission acceptance index is malformed");
    }
    return row.acceptanceHash;
  } catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return null; throw error; }
}
