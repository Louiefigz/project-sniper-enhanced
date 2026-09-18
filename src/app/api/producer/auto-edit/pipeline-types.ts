import type {
  AutoEditJob,
  CheckpointUpdate,
} from "@/lib/server/auto-edit-job-store";
import type { Send, SendRaw } from "./stream";
import type { CutApprovalPauseOutcome } from "./cut-approval-request";

export type PipelineOutcome = { status: "completed" } | CutApprovalPauseOutcome;

export interface PipelineIo {
  send: Send;
  sendRaw: SendRaw;
  advance: (update: CheckpointUpdate) => AutoEditJob;
  invalidate: (update: CheckpointUpdate) => AutoEditJob;
}

export interface PipelineRuntime {
  job: AutoEditJob;
  io: PipelineIo;
}
