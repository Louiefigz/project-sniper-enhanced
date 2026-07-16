import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import type { ProducerRunPhase } from "@/lib/producer/project-state";
import type { ProcessIdentity } from "./process-liveness";

export const AUTO_EDIT_CHECKPOINTS = [
  "queued", "authoring", "plan_authored", "planning_review", "plan_reviewed",
  "validating", "validated", "rendering", "rendered", "quality_check",
  "repairing", "complete",
] as const;

export type AutoEditCheckpoint = (typeof AUTO_EDIT_CHECKPOINTS)[number];
export type AutoEditJobStatus = "running" | "failed" | "interrupted" | "complete";

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
