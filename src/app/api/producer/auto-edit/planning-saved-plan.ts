import type { AutoEditJob } from "@/lib/server/auto-edit-job-store";
import type { ProducerReview } from "./review-contract";
import { AutoEditError } from "./stream";

type HashFile = (filePath: string) => string | undefined;

/** Bind planning to the exact complete-plan bytes accepted at launch. */
export function savedPlanPlanningHash(
  job: AutoEditJob,
  hash: HashFile,
): string | undefined {
  if (!job.reviewSavedPlan) return undefined;
  const current = hash(job.ctx.planPath);
  if (!current || !job.planHash || current !== job.planHash) {
    throw new AutoEditError(
      "complete saved plan changed before planning review; no writer was launched",
    );
  }
  return current;
}

/** A saved plan is review-only: findings stop the run and bytes stay exact. */
export function protectSavedPlanPlanning(
  job: AutoEditJob,
  review: ProducerReview,
  expected: string | undefined,
  hash: HashFile,
): void {
  if (!expected) return;
  if (hash(job.ctx.planPath) !== expected) {
    throw new AutoEditError(
      "complete saved plan changed during planning review; no writer was launched",
    );
  }
  if (!review.materialIssues.length) return;
  const codes = review.materialIssues.map((issue) => issue.code).join(", ");
  throw new AutoEditError(
    `saved-plan planning review found material issues; `
      + `complete plan was not modified and no writer was launched: ${codes}`,
  );
}
