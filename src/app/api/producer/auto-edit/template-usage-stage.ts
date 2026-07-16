import type { AutoEditJob } from "@/lib/server/auto-edit-job-store";
import { withAutoEditJobLock } from "@/lib/server/auto-edit-job-lock";
import {
  autoEditJobPath,
  requiredRunningJob,
  writeJobUnlocked,
} from "@/lib/server/auto-edit-job-persistence";
import {
  captureTemplateUsageAuthority,
  restoreTemplateUsageAuthority,
  type BoundTemplateUsage,
} from "@/lib/server/template-usage-history";

export interface BoundTemplateUsageJob extends BoundTemplateUsage {
  job: AutoEditJob;
}

interface TemplateUsageStageDependencies {
  capture?: typeof captureTemplateUsageAuthority;
}

/** Persist creative-memory authority in the durable job before any writer starts. */
export function bindTemplateUsageForJob(
  job: AutoEditJob,
  dependencies: TemplateUsageStageDependencies = {},
): BoundTemplateUsageJob {
  const capture = dependencies.capture ?? captureTemplateUsageAuthority;
  const provisional = job.ctx.templateUsage
    ? restoreTemplateUsageAuthority(job.ctx, job.ctx.templateUsage)
    : capture(job.ctx);
  const jobPath = autoEditJobPath(job.ctx.dir);
  return withAutoEditJobLock(jobPath, () => {
    const current = requiredRunningJob(jobPath, job.token);
    const usage = current.ctx.templateUsage
      ? restoreTemplateUsageAuthority(current.ctx, current.ctx.templateUsage)
      : provisional;
    const bound = current.ctx.templateUsage ? current : writeJobUnlocked(jobPath, {
      ...current, ctx: { ...current.ctx, templateUsage: usage.authority },
      updatedAt: new Date().toISOString(),
    });
    return { ...usage, job: bound };
  });
}
