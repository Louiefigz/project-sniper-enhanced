import { randomUUID } from "crypto";
import { lstatSync, readFileSync, renameSync, rmSync, writeFileSync } from "fs";
import path from "path";
import { autoEditRequestKey } from "./auto-edit-hash";
import { validAutoEditPipelineAuthority } from "./auto-edit-pipeline-authority";
import { validProcessIdentity } from "./process-liveness";
import { validTemplateUsageAuthority } from "./template-usage-history";
import {
  AUTO_EDIT_CHECKPOINTS,
  type AutoEditCheckpoint,
  type AutoEditJob,
} from "./auto-edit-job-types";

export const AUTO_EDIT_JOB_FILE = ".sniper-auto-edit-job.json";

export class StaleAutoEditWorkerError extends Error {}

export function autoEditJobPath(dir: string): string {
  return path.join(dir.replace(/\/$/, ""), AUTO_EDIT_JOB_FILE);
}

function validJob(value: unknown): value is AutoEditJob {
  if (!value || typeof value !== "object") return false;
  const job = value as Partial<AutoEditJob>;
  return job.version === 1
    && typeof job.token === "string"
    && typeof job.requestKey === "string"
    && typeof job.ctx?.dir === "string"
    && typeof job.logPath === "string"
    && job.requestKey === autoEditRequestKey(job.ctx)
    && AUTO_EDIT_CHECKPOINTS.includes(job.checkpoint as AutoEditCheckpoint)
    && ["running", "failed", "interrupted", "complete"].includes(String(job.status))
    && typeof job.activeEventStartId === "number"
    && (!job.ctx?.doctrine || (
      typeof job.ctx.doctrine.runId === "string"
      && /^[0-9a-f]{64}$/.test(job.ctx.doctrine.doctrineHash)
      && path.isAbsolute(job.ctx.doctrine.snapshotPath)
      && typeof job.ctx.doctrine.files === "object"
    ))
    && (!job.ctx?.pipeline || validAutoEditPipelineAuthority(job.ctx.pipeline))
    && (!job.ctx?.templateUsage || validTemplateUsageAuthority(job.ctx.templateUsage))
    && (job.workerIdentity === undefined || validProcessIdentity(job.workerIdentity))
    && (job.orphanedWorkerIdentity === undefined
      || validProcessIdentity(job.orphanedWorkerIdentity))
    && Array.isArray(job.events);
}

export function readAutoEditJob(jobPath: string): AutoEditJob | null {
  try {
    if (!lstatSync(jobPath).isFile()) return null;
    const value: unknown = JSON.parse(readFileSync(jobPath, "utf8"));
    return validJob(value) ? value : null;
  } catch {
    return null;
  }
}

export function writeJobUnlocked(jobPath: string, job: AutoEditJob): AutoEditJob {
  const temporary = `${jobPath}.${randomUUID()}.tmp`;
  try {
    writeFileSync(temporary, `${JSON.stringify(job, null, 2)}\n`, {
      flag: "wx", mode: 0o600,
    });
    renameSync(temporary, jobPath);
    return job;
  } finally {
    rmSync(temporary, { force: true });
  }
}

export function requiredJob(jobPath: string, expectedToken?: string): AutoEditJob {
  const job = readAutoEditJob(jobPath);
  if (!job) throw new Error(`Auto Edit job is missing or invalid: ${jobPath}`);
  if (expectedToken && job.token !== expectedToken) {
    throw new StaleAutoEditWorkerError(
      `Auto Edit job token changed; stale worker ${expectedToken} is fenced out`,
    );
  }
  return job;
}

export function requiredRunningJob(jobPath: string, expectedToken: string): AutoEditJob {
  const job = requiredJob(jobPath, expectedToken);
  if (job.status !== "running") {
    throw new StaleAutoEditWorkerError(
      `Auto Edit is ${job.status}; worker ${expectedToken} may not mutate its saved checkpoint`,
    );
  }
  return job;
}
