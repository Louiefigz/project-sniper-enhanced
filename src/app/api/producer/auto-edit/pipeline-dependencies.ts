import { existsSync } from "node:fs";
import { autoEditAuthoritySnapshot } from
  "@/lib/server/auto-edit-authority-snapshot";
import { fileSha256, type AutoEditJob } from
  "@/lib/server/auto-edit-job-store";
import { runAssemble, runBaseGuard } from "./chain";
import {
  runAuthoring,
  type AuthoringSessionMode,
  type AuthoringStage,
} from "./authoring";
import { runProducerRevision } from "./brain-review-runner";
import {
  approveSavedPlanCut,
  approvePrevisualCut,
  validateSavedPlanCut,
  validatePrevisualCut,
  verifyApprovedCut,
} from "./cut-approval";
import { runCutReviewLoop } from "./cut-review-loop";
import { verifyCutReviewApproval } from "./cut-review-approval";
import { mintCompatibilityPictureLock } from "./compatibility-picture-lock";
import { markAuthoringSessionEstablished } from "./authoring-session-state";
import { runPlanningReviewLoop } from "./planning-loop";
import type { GuidedCutDependencies } from "./guided-cut-boundary";
import { runQualityReviewRound } from "./quality-loop";
import {
  publishApprovedPalmierMirror,
  publishPalmierWorkingCheckpoint,
} from "./palmier-checkpoints";
import { runPalmierPrimaryAutoEdit } from "./palmier-primary";
import type { Send } from "./stream";
import { approvedRenderGraphReady } from
  "@/lib/server/current-render-graph-candidate";
import { assertAutoEditPromotionReadySync } from
  "@/lib/server/auto-edit-promotion-readiness";
import { initializeAutoEditProducerAuthoritySync } from
  "@/lib/server/producer-auto-edit-genesis";
import { approvedProducerRevisionReady } from
  "@/lib/server/producer-approved-revision-authority";

export interface PipelineDependencies {
  exists: typeof existsSync;
  hashFile: typeof fileSha256;
  author: (
    ctx: AutoEditJob["ctx"],
    send: Send,
    stage: AuthoringStage,
    sessionMode: AuthoringSessionMode,
  ) => ReturnType<typeof runAuthoring>;
  validateCut: typeof validatePrevisualCut;
  validateSavedCut: typeof validateSavedPlanCut;
  reviewCut: typeof runCutReviewLoop;
  verifyReviewCut: typeof verifyCutReviewApproval;
  approveCut: typeof approvePrevisualCut;
  approveSavedCut: typeof approveSavedPlanCut;
  verifyCut: typeof verifyApprovedCut;
  lockCut: typeof mintCompatibilityPictureLock;
  cutApprovalAccepted?: GuidedCutDependencies["cutApprovalAccepted"];
  prepareCutPreview?: GuidedCutDependencies["prepareCutPreview"];
  bindSession: typeof markAuthoringSessionEstablished;
  planning: typeof runPlanningReviewLoop;
  revise: typeof runProducerRevision;
  baseGuard: typeof runBaseGuard;
  assemble: typeof runAssemble;
  quality: typeof runQualityReviewRound;
  authority: typeof autoEditAuthoritySnapshot;
  checkpoint: typeof publishPalmierWorkingCheckpoint;
  approvedMirror: typeof publishApprovedPalmierMirror;
  palmierPrimary: typeof runPalmierPrimaryAutoEdit;
  renderGraphReady: typeof approvedRenderGraphReady;
  approvedRevisionReady: typeof approvedProducerRevisionReady;
  reconciliationReady: typeof assertAutoEditPromotionReadySync;
  initializeAuthority: typeof initializeAutoEditProducerAuthoritySync;
}

export const DEFAULT_PIPELINE_DEPENDENCIES: PipelineDependencies = {
  exists: existsSync,
  hashFile: fileSha256,
  author: (ctx, send, stage, sessionMode) => runAuthoring(
    ctx, send, {}, { stage, sessionMode },
  ),
  validateCut: validatePrevisualCut,
  validateSavedCut: validateSavedPlanCut,
  reviewCut: runCutReviewLoop,
  verifyReviewCut: verifyCutReviewApproval,
  approveCut: approvePrevisualCut,
  approveSavedCut: approveSavedPlanCut,
  verifyCut: verifyApprovedCut,
  lockCut: mintCompatibilityPictureLock,
  bindSession: markAuthoringSessionEstablished,
  planning: runPlanningReviewLoop,
  revise: runProducerRevision,
  baseGuard: runBaseGuard,
  assemble: runAssemble,
  quality: runQualityReviewRound,
  authority: autoEditAuthoritySnapshot,
  checkpoint: publishPalmierWorkingCheckpoint,
  approvedMirror: publishApprovedPalmierMirror,
  palmierPrimary: runPalmierPrimaryAutoEdit,
  renderGraphReady: approvedRenderGraphReady,
  approvedRevisionReady: approvedProducerRevisionReady,
  reconciliationReady: assertAutoEditPromotionReadySync,
  initializeAuthority: initializeAutoEditProducerAuthoritySync,
};
