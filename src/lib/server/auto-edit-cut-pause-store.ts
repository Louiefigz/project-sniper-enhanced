import { assertCutApprovalRequestCurrent } from "@/app/api/producer/auto-edit/cut-approval-request";
import { parseCutPreviewPointer, type CutApprovalRequestV1, type CutPreviewPointer } from "@/lib/producer/contracts/cut-approval-request";
import { withAutoEditJobLock } from "./auto-edit-job-lock";
import { requiredJob, StaleAutoEditWorkerError, writeJobUnlocked } from "./auto-edit-job-persistence";
import type { AutoEditJob } from "./auto-edit-job-types";
import { bootstrapPauseHash } from "./guided-project-bootstrap-quiescence";

export const CUT_APPROVAL_WAIT_MESSAGE =
  "The exact cut passed deterministic checks and two independent reviews. Waiting for separate cut acceptance; visual authoring has not started.";

function waitingJob(job: AutoEditJob, request: CutApprovalRequestV1, preview?: CutPreviewPointer): AutoEditJob {
  const now = new Date().toISOString();
  return {
    ...job,
    bootstrapQuiescenceHash: bootstrapPauseHash(job, request, preview),
    status: "awaiting_cut_approval",
    checkpoint: "cut_reviewed",
    phase: "authoring",
    cutApprovalRequest: request,
    cutPreview: preview,
    cutApprovalWaitStartedAt: now,
    message: CUT_APPROVAL_WAIT_MESSAGE,
    updatedAt: now,
    nextEventId: job.nextEventId + 1,
    events: [...job.events, { id: job.nextEventId, at: now, payload: {
      event: "awaiting_cut_approval", requestHash: request.requestHash,
      planHash: request.planHash, message: CUT_APPROVAL_WAIT_MESSAGE,
      ...(preview ? { previewExecutionKey: preview.executionKey, previewReceiptHash: preview.receiptHash } : {}),
    } }].slice(-256),
    error: undefined,
    workerPid: undefined,
    workerIdentity: undefined,
    orphanedWorkerGroup: undefined,
    orphanedWorkerIdentity: undefined,
    reviewedPlanHash: undefined,
    reviewedAuthorityDigest: undefined,
    renderedPlanHash: undefined,
    renderedManifestHash: undefined,
    renderedAuthorityDigest: undefined,
    candidatePath: undefined,
    candidateHash: undefined,
    finalHash: undefined,
  };
}

/** Atomically stop one fenced worker at its exact reviewed cut; never accept it. */
export function pauseAutoEditForCutApproval(
  jobPath: string,
  token: string,
  value: CutApprovalRequestV1,
  previewValue?: CutPreviewPointer,
): AutoEditJob {
  return withAutoEditJobLock(jobPath, () => {
    const job = requiredJob(jobPath, token);
    const request = assertCutApprovalRequestCurrent(job, value);
    const preview = previewValue === undefined ? undefined : parseCutPreviewPointer(previewValue);
    bootstrapPauseHash(job, request, preview);
    if (job.status === "awaiting_cut_approval" && job.cutApprovalRequest?.requestHash === request.requestHash) {
      if (job.cutPreview?.executionKey !== preview?.executionKey || job.cutPreview?.receiptHash !== preview?.receiptHash) {
        throw new StaleAutoEditWorkerError("waiting preview cannot be replaced by a late worker");
      }
      return job;
    }
    if (job.status !== "running") throw new StaleAutoEditWorkerError("only the current running worker may wait for cut approval");
    return writeJobUnlocked(jobPath, waitingJob(job, request, preview));
  });
}
