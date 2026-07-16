import type {
  AutoEditJob,
  CheckpointUpdate,
} from "@/lib/server/auto-edit-job-store";
import type { Send, SendRaw } from "./stream";

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
