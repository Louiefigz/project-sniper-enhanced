import type { AutoEditJob } from "@/lib/server/auto-edit-job-store";
import { withAutoEditJobLock } from "@/lib/server/auto-edit-job-lock";
import {
  autoEditJobPath,
  requiredRunningJob,
  writeJobUnlocked,
} from "@/lib/server/auto-edit-job-persistence";

/** Persist proof that the allocated UUID names a real Claude conversation. */
export function markAuthoringSessionEstablished(job: AutoEditJob): AutoEditJob {
  const jobPath = autoEditJobPath(job.ctx.dir);
  return withAutoEditJobLock(jobPath, () => {
    const current = requiredRunningJob(jobPath, job.token);
    if (current.ctx.brainSessionEstablished) return current;
    return writeJobUnlocked(jobPath, {
      ...current,
      ctx: { ...current.ctx, brainSessionEstablished: true },
      updatedAt: new Date().toISOString(),
    });
  });
}
