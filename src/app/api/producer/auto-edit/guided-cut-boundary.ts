import type { AutoEditJob, CheckpointUpdate } from "@/lib/server/auto-edit-job-types";
import { CUT_APPROVAL_WAIT_MESSAGE } from "@/lib/server/auto-edit-cut-pause-store";
import type { CompatibilityPictureLockResult } from "./compatibility-picture-lock";
import {
  assertCutApprovalRequestCurrent, buildCutApprovalRequest,
  type CutApprovalPauseOutcome, type CutApprovalRequestV1,
} from "./cut-approval-request";
import { AutoEditError, type Send } from "./stream";
import { parseCutPreviewPointer, type CutPreviewPointer } from "@/lib/producer/contracts/cut-approval-request";

export interface GuidedCutDependencies {
  /** Must validate an independently stored acceptance receipt; absent means pending. */
  cutApprovalAccepted?: (job: AutoEditJob, verified: CompatibilityPictureLockResult) => boolean | Promise<boolean>;
  /** Production closure holds the actual worker lease; never render final media. */
  prepareCutPreview?: (job: AutoEditJob, request: CutApprovalRequestV1) => Promise<CutPreviewPointer>;
}

interface GuidedCutRuntime {
  job: AutoEditJob;
  io: {
    send: Send;
    invalidate: (update: CheckpointUpdate) => AutoEditJob;
  };
}

/** No versionless or system-policy approval is inferred for an explicit guided job. */
export function assertGuidedDelivery(job: AutoEditJob): void {
  const policy: unknown = job.ctx.workflowPolicy;
  if (policy === undefined) return;
  if (policy !== "cut-first" || job.ctx.deliveryPolicy !== "mp4-only") {
    throw new AutoEditError("guided cut approval requires explicit cut-first and MP4-only policies");
  }
}

/** Stop after both existing independent cut walls, before any visual authoring. */
export async function guidedCutBoundary(
  run: GuidedCutRuntime,
  deps: GuidedCutDependencies,
  verified: CompatibilityPictureLockResult,
): Promise<CutApprovalPauseOutcome | null> {
  assertGuidedDelivery(run.job);
  if (run.job.ctx.workflowPolicy === undefined) return null;
  if (run.job.cutAcceptance) {
    if (await deps.cutApprovalAccepted?.(run.job, verified) === true) return null;
    throw new AutoEditError("The saved human cut acceptance has not been independently verified");
  }
  const prior = run.job.cutApprovalRequest;
  if (prior) assertCutApprovalRequestCurrent(run.job, prior);
  const request = buildCutApprovalRequest(run.job, verified, prior?.createdAt);
  if (prior && prior.requestHash !== request.requestHash) throw new AutoEditError("guided cut request changed before continuation");
  if (!deps.prepareCutPreview) throw new AutoEditError("guided cut requires a qualified playable preview before operator review");
  run.io.send({ event: "cut_preview_started", message: "Rendering the exact reviewed cut preview; operator wait has not started." });
  const preview = parseCutPreviewPointer(await deps.prepareCutPreview(run.job, request));
  assertCutApprovalRequestCurrent(run.job, request);
  run.job = run.io.invalidate({
    checkpoint: "cut_reviewed", phase: "authoring", message: CUT_APPROVAL_WAIT_MESSAGE,
    planHash: request.planHash, authorityDigest: request.authorityDigest,
    planningRound: 0, planningCycles: 0,
  });
  return { status: "awaiting_cut_approval", request, preview };
}
