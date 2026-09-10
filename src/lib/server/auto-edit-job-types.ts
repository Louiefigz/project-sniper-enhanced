import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import type { ProducerRunPhase } from "@/lib/producer/project-state";
import type { ProcessIdentity } from "./process-liveness";
import type { CutApprovalRequestV1, CutPreviewPointer } from "@/lib/producer/contracts/cut-approval-request";
import type { HumanCutAcceptanceAttempt, HumanCutAcceptancePointer } from "@/lib/producer/contracts/human-cut-acceptance";
import type { GuidedHandoffPointerV2 } from "@/lib/producer/contracts/guided-workflow-v2";

export const AUTO_EDIT_CHECKPOINTS = [
  "queued", "authoring", "cut_reviewed", "plan_authored", "planning_review", "plan_reviewed",
  "validating", "validated", "rendering", "rendered", "quality_check",
  "repairing", "complete",
] as const;

export type AutoEditCheckpoint = (typeof AUTO_EDIT_CHECKPOINTS)[number];
export type AutoEditJobStatus = "running" | "failed" | "interrupted" | "complete" | "awaiting_cut_approval" | "cut_accepted"
  | "awaiting_treatment_brief" | "treatment_admitted";

export interface AutoEditJobEvent {
  id: number;
  at: string;
  payload: Record<string, unknown>;
}

export interface AutoEditJob {
  version: 1;
  qualityPolicyVersion?: 1;
  token: string;
  /** Stable evidence namespace retained when a resumed worker receives a new fencing token. */
  artifactToken?: string;
  requestKey: string;
  ctx: AutoEditCtx;
  status: AutoEditJobStatus;
  checkpoint: AutoEditCheckpoint;
  phase: ProducerRunPhase;
  message: string;
  snapshots: number;
  attempts: number;
  /** The exact reviewed cut awaiting a separate operator acceptance transaction. */
  cutApprovalRequest?: CutApprovalRequestV1;
  /** Exact private preview attempt, atomically recorded when user wait begins. */
  cutPreview?: CutPreviewPointer;
  /** Current human-wait interval; engine verification never silently consumes it. */
  cutApprovalWaitStartedAt?: string;
  cutAcceptanceAttempt?: HumanCutAcceptanceAttempt;
  /** Activates one immutable human-cut-only fact; never final-video authority. */
  cutAcceptance?: HumanCutAcceptancePointer;
  /** V2 cut/treatment authority; never interprets a v1 human acceptance as a new brief. */
  guidedHandoffV2?: GuidedHandoffPointerV2;
  /** Explicit GUI/API saved-plan review; preserves a complete plan through cut authority. */
  reviewSavedPlan?: true;
  /** Bootstrap-only exact process-quiescence fact; never a human acceptance. */
  bootstrapQuiescenceHash?: string;
  requestedAt: string;
  updatedAt: string;
  workerPid?: number;
  workerIdentity?: ProcessIdentity;
  orphanedWorkerGroup?: number;
  orphanedWorkerIdentity?: ProcessIdentity;
  logPath: string;
  planHash?: string;
  manifestHash?: string;
  referenceProfileHash?: string;
  authorityDigest?: string;
  planningRound?: number;
  /** Paid review cycles against MAX_PLANNING_REVIEW_ROUNDS; planningRound
   * stays the per-critic artifact-dir high-water used by review evidence. */
  planningCycles?: number;
  planningRoundsRequired?: number;
  planningCleanRounds?: number;
  planningCleanPlanHash?: string;
  planningCleanAuthorityDigest?: string;
  reviewedPlanHash?: string;
  reviewedAuthorityDigest?: string;
  renderedPlanHash?: string;
  renderedManifestHash?: string;
  renderedAuthorityDigest?: string;
  qcRound?: number;
  qcRoundsMax?: number;
  candidatePath?: string;
  candidateHash?: string;
  unresolvedFindingIds?: string[];
  finalHash?: string;
  error?: string;
  nextEventId: number;
  activeEventStartId: number;
  events: AutoEditJobEvent[];
}

export interface NewAutoEditJobArgs {
  ctx: AutoEditCtx;
  token: string;
  snapshots: number;
  resume?: AutoEditJob;
  bootstrapPlanHash?: string;
  reviewSavedPlan?: boolean;
}

export interface CheckpointUpdate {
  checkpoint: AutoEditCheckpoint;
  phase: ProducerRunPhase;
  message: string;
  planHash?: string;
  manifestHash?: string;
  referenceProfileHash?: string;
  authorityDigest?: string;
  planningRound?: number;
  planningCycles?: number;
  planningRoundsRequired?: number;
  planningCleanRounds?: number;
  planningCleanPlanHash?: string;
  planningCleanAuthorityDigest?: string;
  reviewedPlanHash?: string;
  reviewedAuthorityDigest?: string;
  renderedPlanHash?: string;
  renderedManifestHash?: string;
  renderedAuthorityDigest?: string;
  qcRound?: number;
  qcRoundsMax?: number;
  candidatePath?: string;
  candidateHash?: string;
  unresolvedFindingIds?: string[];
  finalHash?: string;
}
