import { existsSync, lstatSync, renameSync, rmSync } from "fs";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { autoEditRequestKey } from "./auto-edit-hash";
import { withAutoEditJobLock } from "./auto-edit-job-lock";
import {
  captureProcessIdentity,
  durableProcessAlive,
  durableProcessGroupAlive,
} from "./process-liveness";
import { activateManagedQualityPolicy } from "./auto-edit-quality-policy";
import {
  autoEditJobPath,
  readAutoEditJob,
  requiredJob,
  requiredRunningJob,
  StaleAutoEditWorkerError,
  writeJobUnlocked,
} from "./auto-edit-job-persistence";
import { freshJob, resumedJob } from "./auto-edit-job-builders";
import {
  AUTO_EDIT_CHECKPOINTS,
  type AutoEditCheckpoint,
  type AutoEditJob,
  type AutoEditJobStatus,
  type CheckpointUpdate,
  type NewAutoEditJobArgs,
} from "./auto-edit-job-types";
export { autoEditRequestKey, fileSha256 } from "./auto-edit-hash";
export {
  durableProcessAlive,
  durableProcessGroupAlive,
  processAlive,
  processGroupAlive,
} from "./process-liveness";
export { AUTO_EDIT_CHECKPOINTS } from "./auto-edit-job-types";
export type { AutoEditCheckpoint, AutoEditJob, AutoEditJobEvent,
  AutoEditJobStatus, CheckpointUpdate } from "./auto-edit-job-types";

const MAX_EVENTS = 256;
const MAX_EVENT_BYTES = 16_000;
const STARTUP_GRACE_MS = 15_000;

export {
  AUTO_EDIT_JOB_FILE,
  autoEditJobPath,
  readAutoEditJob,
  StaleAutoEditWorkerError,
} from "./auto-edit-job-persistence";

function interruptionMessage(job: AutoEditJob): string {
  return `Auto Edit was interrupted during ${job.phase.replaceAll("_", " ")}. Its completed checkpoints were saved; Resume will continue from ${job.checkpoint.replaceAll("_", " ")}.`;
}

export function recoverAutoEditJob(jobPath: string): AutoEditJob | null {
  const job = readAutoEditJob(jobPath);
  if (!job || job.status !== "running") return job;
  const waitingForWorker = !job.workerPid && Date.now() - Date.parse(job.updatedAt) < STARTUP_GRACE_MS;
  if (waitingForWorker || durableProcessAlive(
    job.workerPid, job.workerIdentity, job.updatedAt,
  )) return job;
  const orphanedGroup = durableProcessGroupAlive(
    job.workerPid, job.workerIdentity, job.updatedAt,
  )
    ? job.workerPid
    : undefined;
  return interruptAutoEditJob(jobPath, job.token, interruptionMessage(job), orphanedGroup);
}

export function resumableAutoEditJob(ctx: AutoEditCtx): AutoEditJob | null {
  const job = recoverAutoEditJob(autoEditJobPath(ctx.dir));
  if (!job || !["failed", "interrupted"].includes(job.status)) return null;
  return job.requestKey === autoEditRequestKey(ctx) ? job : null;
}

/**
 * A fresh launch must never clobber the prior journal: dead (failed or
 * interrupted), completed, or unreadable journals are renamed alongside
 * (.sniper-auto-edit-job.<timestamp>.json) so their evidence survives Retry.
 */
function archiveSupersededJournal(jobPath: string): void {
  if (!existsSync(jobPath) || !lstatSync(jobPath).isFile()) return;
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  renameSync(jobPath, `${jobPath.replace(/\.json$/, "")}.${stamp}.json`);
}

export function startAutoEditJob(args: NewAutoEditJobArgs): AutoEditJob {
  const jobPath = autoEditJobPath(args.ctx.dir);
  return withAutoEditJobLock(jobPath, () => {
    const current = readAutoEditJob(jobPath);
    if (args.resume && (!current || current.token !== args.resume.token || current.status === "running")) {
      throw new StaleAutoEditWorkerError("The resumable Auto Edit checkpoint changed before launch");
    }
    if (!args.resume && current?.status === "running") {
      throw new Error("A durable Auto Edit job is already running for this project");
    }
    if (!args.resume) archiveSupersededJournal(jobPath);
    const now = new Date().toISOString();
    const job = args.resume ? resumedJob(args, current!, now) : freshJob(args, now);
    activateManagedQualityPolicy(args.ctx.dir, job.requestKey, args.ctx);
    return writeJobUnlocked(jobPath, job);
  });
}

export function markAutoEditWorker(jobPath: string, token: string, workerPid: number): AutoEditJob {
  return withAutoEditJobLock(jobPath, () => {
    const job = requiredRunningJob(jobPath, token);
    return writeJobUnlocked(jobPath, {
      ...job,
      workerPid,
      workerIdentity: captureProcessIdentity(workerPid),
      orphanedWorkerGroup: undefined,
      orphanedWorkerIdentity: undefined,
      updatedAt: new Date().toISOString(),
    });
  });
}

function compactPayload(payload: Record<string, unknown>): Record<string, unknown> {
  if (Buffer.byteLength(JSON.stringify(payload)) <= MAX_EVENT_BYTES) return payload;
  return {
    event: payload.event ?? "log",
    phase: payload.phase,
    stage: payload.stage,
    status: payload.status,
    note: payload.note,
    message: payload.message,
    truncated: true,
  };
}

export function appendAutoEditJobEvent(
  jobPath: string,
  token: string,
  payload: Record<string, unknown>,
): AutoEditJob {
  return withAutoEditJobLock(jobPath, () => {
    const job = requiredRunningJob(jobPath, token);
    const now = new Date().toISOString();
    const item = { id: job.nextEventId, at: now, payload: compactPayload(payload) };
    return writeJobUnlocked(jobPath, {
      ...job,
      updatedAt: now,
      nextEventId: job.nextEventId + 1,
      events: [...job.events, item].slice(-MAX_EVENTS),
    });
  });
}

/** Refresh live status/liveness without growing the bounded diagnostic event trail. */
export function heartbeatAutoEditJob(
  jobPath: string,
  token: string,
  message: string,
): AutoEditJob {
  return withAutoEditJobLock(jobPath, () => {
    const job = requiredRunningJob(jobPath, token);
    return writeJobUnlocked(jobPath, {
      ...job,
      message,
      updatedAt: new Date().toISOString(),
    });
  });
}

export function advanceAutoEditJob(
  jobPath: string,
  token: string,
  update: CheckpointUpdate,
): AutoEditJob {
  return withAutoEditJobLock(jobPath, () => {
    const job = requiredRunningJob(jobPath, token);
    const current = AUTO_EDIT_CHECKPOINTS.indexOf(job.checkpoint);
    const requested = AUTO_EDIT_CHECKPOINTS.indexOf(update.checkpoint);
    const checkpoint = requested >= current ? update.checkpoint : job.checkpoint;
    return writeJobUnlocked(jobPath, {
      ...job,
      checkpoint,
      phase: update.phase,
      message: update.message,
      updatedAt: new Date().toISOString(),
      ...(update.planHash ? { planHash: update.planHash } : {}),
      ...(update.manifestHash ? { manifestHash: update.manifestHash } : {}),
      ...(update.referenceProfileHash ? { referenceProfileHash: update.referenceProfileHash } : {}),
      ...(update.authorityDigest ? { authorityDigest: update.authorityDigest } : {}),
      ...(update.planningRound !== undefined ? { planningRound: update.planningRound } : {}),
      ...(update.planningCycles !== undefined ? { planningCycles: update.planningCycles } : {}),
      ...(update.planningRoundsRequired !== undefined
        ? { planningRoundsRequired: update.planningRoundsRequired } : {}),
      ...(update.planningCleanRounds !== undefined
        ? { planningCleanRounds: update.planningCleanRounds } : {}),
      ...(update.planningCleanPlanHash
        ? { planningCleanPlanHash: update.planningCleanPlanHash } : {}),
      ...(update.planningCleanAuthorityDigest
        ? { planningCleanAuthorityDigest: update.planningCleanAuthorityDigest } : {}),
      ...(update.reviewedPlanHash ? { reviewedPlanHash: update.reviewedPlanHash } : {}),
      ...(update.reviewedAuthorityDigest
        ? { reviewedAuthorityDigest: update.reviewedAuthorityDigest } : {}),
      ...(update.renderedPlanHash ? { renderedPlanHash: update.renderedPlanHash } : {}),
      ...(update.renderedManifestHash ? { renderedManifestHash: update.renderedManifestHash } : {}),
      ...(update.renderedAuthorityDigest
        ? { renderedAuthorityDigest: update.renderedAuthorityDigest } : {}),
      ...(update.qcRound !== undefined ? { qcRound: update.qcRound } : {}),
      ...(update.qcRoundsMax !== undefined ? { qcRoundsMax: update.qcRoundsMax } : {}),
      ...(update.candidatePath ? { candidatePath: update.candidatePath } : {}),
      ...(update.candidateHash ? { candidateHash: update.candidateHash } : {}),
      ...(update.unresolvedFindingIds
        ? { unresolvedFindingIds: update.unresolvedFindingIds } : {}),
      ...(update.finalHash ? { finalHash: update.finalHash } : {}),
    });
  });
}

export function invalidateAutoEditJob(
  jobPath: string,
  token: string,
  update: CheckpointUpdate,
): AutoEditJob {
  return withAutoEditJobLock(jobPath, () => {
    const job = requiredRunningJob(jobPath, token);
    return writeJobUnlocked(jobPath, {
      ...job,
      checkpoint: update.checkpoint,
      phase: update.phase,
      message: update.message,
      updatedAt: new Date().toISOString(),
      planHash: update.planHash,
      manifestHash: update.manifestHash,
      referenceProfileHash: update.referenceProfileHash,
      authorityDigest: update.authorityDigest,
      planningRound: update.planningRound ?? job.planningRound,
      planningCycles: update.planningCycles ?? job.planningCycles,
      planningRoundsRequired: update.planningRoundsRequired ?? job.planningRoundsRequired,
      planningCleanRounds: update.planningCleanRounds ?? job.planningCleanRounds,
      planningCleanPlanHash: update.planningCleanPlanHash,
      planningCleanAuthorityDigest: update.planningCleanAuthorityDigest,
      reviewedPlanHash: update.reviewedPlanHash,
      reviewedAuthorityDigest: update.reviewedAuthorityDigest,
      renderedPlanHash: undefined,
      renderedManifestHash: undefined,
      renderedAuthorityDigest: undefined,
      qcRound: update.qcRound ?? job.qcRound,
      qcRoundsMax: update.qcRoundsMax ?? job.qcRoundsMax,
      candidatePath: undefined,
      candidateHash: undefined,
      unresolvedFindingIds: update.unresolvedFindingIds,
      finalHash: undefined,
    });
  });
}

function finishJob(
  jobPath: string,
  token: string,
  update: { status: AutoEditJobStatus; message: string; orphanedWorkerGroup?: number },
): AutoEditJob {
  return withAutoEditJobLock(jobPath, () => {
    const job = requiredJob(jobPath, token);
    if (job.status !== "running") {
      if (job.status === update.status) return job;
      throw new StaleAutoEditWorkerError(
        `Auto Edit is already ${job.status}; stale worker cannot mark it ${update.status}`,
      );
    }
    const orphanedWorkerGroup = update.orphanedWorkerGroup
      ?? (update.status === "failed" || update.status === "interrupted" ? job.workerPid : undefined);
    return writeJobUnlocked(jobPath, {
      ...job,
      status: update.status,
      message: update.message,
      error: update.status === "complete" ? undefined : update.message,
      updatedAt: new Date().toISOString(),
      ...(orphanedWorkerGroup ? { orphanedWorkerGroup } : {}),
      ...(orphanedWorkerGroup && job.workerIdentity
        ? { orphanedWorkerIdentity: job.workerIdentity } : {}),
      ...(update.status === "complete" ? { checkpoint: "complete" as const } : {}),
    });
  });
}

export function failAutoEditJob(jobPath: string, token: string, message: string): AutoEditJob {
  return finishJob(jobPath, token, { status: "failed", message });
}

export function interruptAutoEditJob(
  jobPath: string,
  token: string,
  message: string,
  orphanedWorkerGroup?: number,
): AutoEditJob {
  return finishJob(jobPath, token, { status: "interrupted", message, orphanedWorkerGroup });
}

export function completeAutoEditJob(jobPath: string, token: string): AutoEditJob {
  return finishJob(jobPath, token, { status: "complete", message: "Auto Edit completed successfully." });
}

export function checkpointReached(current: AutoEditCheckpoint, target: AutoEditCheckpoint): boolean {
  return AUTO_EDIT_CHECKPOINTS.indexOf(current) >= AUTO_EDIT_CHECKPOINTS.indexOf(target);
}

export function clearAutoEditJob(jobPath: string): void {
  withAutoEditJobLock(jobPath, () => rmSync(jobPath, { force: true }));
}
