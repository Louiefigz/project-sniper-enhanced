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
import { parseAutoEditDeliveryPolicy } from
  "@/lib/producer/auto-edit-delivery-policy";
import { validCutApprovalRequest, validCutPreviewPointer } from "@/lib/producer/contracts/cut-approval-request";
import { validHumanCutAcceptancePointer, validHumanCutAcceptanceAttempt } from "@/lib/producer/contracts/human-cut-acceptance";
import { validGuidedWorkflowV2, validGuidedHandoffPointerV2 } from "@/lib/producer/contracts/guided-workflow-v2";
import { hasGuidedBootstrap, validExistingCutContext } from "./guided-project-bootstrap-contract";

export const AUTO_EDIT_JOB_FILE = ".sniper-auto-edit-job.json";

export class StaleAutoEditWorkerError extends Error {}

export function autoEditJobPath(dir: string): string {
  return path.join(dir.replace(/\/$/, ""), AUTO_EDIT_JOB_FILE);
}

/** A cut-only bootstrap never owns a rendered candidate or delivery checkpoint. */
function validBootstrapProgress(job: Partial<AutoEditJob>): boolean {
  if (job.status === "complete" || !["queued", "authoring", "cut_reviewed"].includes(String(job.checkpoint))) return false;
  return [job.renderedPlanHash, job.renderedManifestHash, job.renderedAuthorityDigest,
    job.candidatePath, job.candidateHash, job.finalHash].every(value => value === undefined);
}

function validJob(value: unknown): value is AutoEditJob {
  if (!value || typeof value !== "object") return false;
  const job = value as Partial<AutoEditJob>;
  let deliveryPolicyValid = true;
  try {
    parseAutoEditDeliveryPolicy(job.ctx?.deliveryPolicy);
  } catch {
    deliveryPolicyValid = false;
  }
  return deliveryPolicyValid
    && job.version === 1
    && typeof job.token === "string"
    && typeof job.requestKey === "string"
    && typeof job.ctx?.dir === "string"
    && validExistingCutContext(job.ctx)
    && (!hasGuidedBootstrap(job.ctx) || validBootstrapProgress(job))
    && (!hasGuidedBootstrap(job.ctx) || (!job.reviewSavedPlan && job.attempts === 1))
    && (job.bootstrapQuiescenceHash === undefined || (hasGuidedBootstrap(job.ctx)
      && /^[0-9a-f]{64}$/.test(job.bootstrapQuiescenceHash)))
    && (!hasGuidedBootstrap(job.ctx) || !["awaiting_cut_approval", "awaiting_treatment_brief", "treatment_admitted"].includes(String(job.status))
      || job.bootstrapQuiescenceHash !== undefined)
    && typeof job.logPath === "string"
    && job.requestKey === autoEditRequestKey(job.ctx)
    && AUTO_EDIT_CHECKPOINTS.includes(job.checkpoint as AutoEditCheckpoint)
    && ["running", "failed", "interrupted", "complete", "awaiting_cut_approval", "cut_accepted",
      "awaiting_treatment_brief", "treatment_admitted"].includes(String(job.status))
    && (job.ctx.workflowPolicy === undefined || (job.ctx.workflowPolicy === "cut-first" && job.ctx.deliveryPolicy === "mp4-only"))
    && (job.ctx.workflowV2 === undefined || (validGuidedWorkflowV2(job.ctx.workflowV2)
      && job.ctx.workflowPolicy === "cut-first" && job.ctx.deliveryPolicy === "mp4-only" && !job.cutAcceptance && !job.cutAcceptanceAttempt))
    && (job.guidedHandoffV2 === undefined || (job.ctx.workflowV2 !== undefined && validGuidedHandoffPointerV2(job.guidedHandoffV2)
      && ["awaiting_treatment_brief", "treatment_admitted"].includes(String(job.status))
      && job.cutPreview !== undefined && job.cutApprovalRequest !== undefined && job.cutApprovalWaitStartedAt !== undefined))
    && (!["awaiting_treatment_brief", "treatment_admitted"].includes(String(job.status)) || (job.guidedHandoffV2 !== undefined
      && job.checkpoint === "cut_reviewed" && job.workerPid === undefined && job.workerIdentity === undefined))
    && (job.status !== "awaiting_treatment_brief" || job.guidedHandoffV2?.treatmentAdmissionHash === undefined)
    && (job.status !== "treatment_admitted" || job.guidedHandoffV2?.treatmentAdmissionHash !== undefined)
    && (job.cutApprovalRequest === undefined || validCutApprovalRequest(job.cutApprovalRequest, job.requestKey))
    && (job.cutPreview === undefined || (job.cutApprovalRequest !== undefined && validCutPreviewPointer(job.cutPreview)))
    && (job.cutAcceptance === undefined || (job.cutPreview !== undefined && validHumanCutAcceptancePointer(job.cutAcceptance)))
    && (job.cutAcceptanceAttempt === undefined || (job.cutApprovalRequest !== undefined && validHumanCutAcceptanceAttempt(job.cutAcceptanceAttempt)))
    && (job.cutApprovalWaitStartedAt === undefined || (typeof job.cutApprovalWaitStartedAt === "string"
      && Number.isFinite(Date.parse(job.cutApprovalWaitStartedAt)) && new Date(job.cutApprovalWaitStartedAt).toISOString() === job.cutApprovalWaitStartedAt))
    && (job.status !== "cut_accepted" || (job.ctx.workflowPolicy === "cut-first" && job.cutAcceptance !== undefined
      && job.checkpoint === "cut_reviewed" && job.workerPid === undefined && job.workerIdentity === undefined))
    && (job.status !== "awaiting_cut_approval" || job.cutAcceptance === undefined)
    && (job.status !== "awaiting_cut_approval" || (job.ctx.workflowPolicy === "cut-first"
      && job.checkpoint === "cut_reviewed" && job.cutApprovalRequest !== undefined))
    && (job.reviewSavedPlan === undefined || job.reviewSavedPlan === true)
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

/** Validate already observed journal bytes without reopening a potentially changed path. */
export function parseAutoEditJobRecord(value: unknown): AutoEditJob {
  if (!validJob(value)) throw new Error("Auto Edit journal is malformed or incompatible");
  return value;
}

export function writeJobUnlocked(jobPath: string, job: AutoEditJob): AutoEditJob {
  if (hasGuidedBootstrap(job.ctx) && (!validExistingCutContext(job.ctx) || !validBootstrapProgress(job))) {
    throw new Error("Guided cut bootstrap cannot persist completion, visual checkpoints, or delivery artifacts");
  }
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
