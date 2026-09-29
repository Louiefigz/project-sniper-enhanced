import type {
  AutoEditJob,
  CheckpointUpdate,
} from "@/lib/server/auto-edit-job-store";
import type { Send, SendRaw } from "./stream";
import type { CutApprovalPauseOutcome } from "./cut-approval-request";
import type { CreativeRouteDispatchOutcome } from "./creative-route-dispatch";

export type PipelineOutcome = { status: "completed" } | CutApprovalPauseOutcome
  | Extract<CreativeRouteDispatchOutcome, { status: "awaiting_native_author" }>;

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
