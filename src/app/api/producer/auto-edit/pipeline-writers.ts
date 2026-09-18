import {
  advanceAutoEditJob,
  invalidateAutoEditJob,
  type AutoEditJob,
  type CheckpointUpdate,
} from "@/lib/server/auto-edit-job-store";

export function diskCheckpointWriter(jobPath: string, token: string) {
  return (update: CheckpointUpdate): AutoEditJob =>
    advanceAutoEditJob(jobPath, token, update);
}

export function diskInvalidationWriter(jobPath: string, token: string) {
  return (update: CheckpointUpdate): AutoEditJob =>
    invalidateAutoEditJob(jobPath, token, update);
}
