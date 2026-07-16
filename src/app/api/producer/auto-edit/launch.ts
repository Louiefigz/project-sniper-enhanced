import { existsSync, readFileSync, statSync } from "node:fs";
import { derror, dlog } from "@/lib/debug";
import {
  autoEditJobPath,
  durableProcessGroupAlive,
  failAutoEditJob,
  fileSha256,
  readAutoEditJob,
  recoverAutoEditJob,
  resumableAutoEditJob,
  startAutoEditJob,
  type AutoEditJob,
} from "@/lib/server/auto-edit-job-store";
import { prepareAutoEditRunContext } from "@/lib/server/auto-edit-pipeline-authority";
import { launchDetachedAutoEditWorker } from "@/lib/server/auto-edit-worker-launcher";
import {
  beginProducerRunWithToken,
  failProducerRun,
  newProducerRunToken,
  producerRun,
  producerRunActive,
} from "@/lib/server/producer-run-registry";
import { snapshotPlan } from "../../_lib/plan-snapshots";
import { retainedClaudeSessionId } from "./authoring-session";
import { type PreparedRequest } from "./request";
import { RequestFailure } from "./request-failure";
import { refitSavedPlanBeforeReview } from "./saved-plan-request";
import { type AutoEditCtx } from "./stream";

export interface StartedRun {
  jobPath: string;
  token: string;
}

interface RunSource {
  job?: AutoEditJob;
  bootstrapPlanHash?: string;
  snapshots: number;
}

export function legacyPlanHash(
  ctx: AutoEditCtx,
  existing: AutoEditJob | null,
): string | undefined {
  if (existing || !existsSync(ctx.planPath)) return undefined;
  const run = producerRun(ctx.dir);
  if (!run || run.kind !== "auto_edit" || run.status !== "interrupted") return undefined;
  if (statSync(ctx.planPath).mtimeMs < Date.parse(run.startedAt)) return undefined;
  return fileSha256(ctx.planPath);
}

/**
 * Fresh Retry over a dead (failed/interrupted) journal: a parseable saved
 * edit_plan.json bootstraps the new job at plan_authored instead of paying
 * re-authoring. The worker still re-runs the deterministic cut wall before
 * trusting it and falls back to the cut writer if the wall rejects the plan.
 */
function deadJournalPlanHash(
  ctx: AutoEditCtx,
  durable: AutoEditJob | null,
): string | undefined {
  if (!durable || !["failed", "interrupted"].includes(durable.status)) return undefined;
  if (!existsSync(ctx.planPath)) return undefined;
  try {
    const plan: unknown = JSON.parse(readFileSync(ctx.planPath, "utf8"));
    if (!plan || typeof plan !== "object" || Array.isArray(plan)) return undefined;
  } catch {
    return undefined;
  }
  return fileSha256(ctx.planPath);
}

function resumeSource(ctx: AutoEditCtx): { job?: AutoEditJob; bootstrapPlanHash?: string } {
  const jobPath = autoEditJobPath(ctx.dir);
  const existing = recoverAutoEditJob(jobPath);
  if (existsSync(jobPath) && !readAutoEditJob(jobPath)) {
    throw new RequestFailure(
      "The saved Auto Edit journal is invalid; preserve it for diagnosis and start a fresh edit.",
      409,
    );
  }
  const job = resumableAutoEditJob(ctx);
  if (existing && !job) {
    throw new RequestFailure("The interrupted job does not match this request, or is not resumable.", 409);
  }
  const bootstrapPlanHash = legacyPlanHash(ctx, existing);
  if (!job && !bootstrapPlanHash) {
    throw new RequestFailure("No interrupted Auto Edit checkpoint matches this request.", 409);
  }
  return { job: job ?? undefined, bootstrapPlanHash };
}

function inactiveDurableJob(ctx: AutoEditCtx): AutoEditJob | null {
  const durable = recoverAutoEditJob(autoEditJobPath(ctx.dir));
  if (producerRunActive(ctx.dir) || durable?.status === "running") {
    throw new RequestFailure("Auto Edit is already running for this project.", 409);
  }
  return durable;
}

function guardStoppedPrevious(previous: AutoEditJob | null | undefined): void {
  const orphanGroup = previous?.orphanedWorkerGroup
    ?? (["failed", "interrupted"].includes(previous?.status ?? "") ? previous?.workerPid : undefined);
  const orphanIdentity = previous?.orphanedWorkerIdentity ?? previous?.workerIdentity;
  if (previous && durableProcessGroupAlive(orphanGroup, orphanIdentity, previous.updatedAt)) {
    throw new RequestFailure(
      "Previous Auto Edit worker processes are still stopping. Wait, then choose Resume Edit again.",
      409,
    );
  }
}

async function preparedRunSource(
  request: PreparedRequest,
  durable: AutoEditJob | null,
): Promise<RunSource> {
  const { ctx, resume } = request;
  let bootstrapPlanHash = request.bootstrapPlanHash;
  let refitSnapshots: number | undefined;
  const resumed = resume ? resumeSource(ctx) : {};
  guardStoppedPrevious(resumed.job ?? durable);
  if (request.reviewSavedPlan) {
    const refit = await refitSavedPlanBeforeReview(ctx);
    refitSnapshots = refit.snapshots;
    bootstrapPlanHash = fileSha256(ctx.planPath);
    if (!bootstrapPlanHash) throw new RequestFailure("The refitted saved timeline disappeared", 409);
  }
  const source: { job?: AutoEditJob; bootstrapPlanHash?: string } = resume
    ? resumed
    : { bootstrapPlanHash: bootstrapPlanHash ?? deadJournalPlanHash(ctx, durable) };
  const snapshots = source.job?.snapshots
    ?? (resume ? 0 : refitSnapshots ?? snapshotPlan(ctx.planPath));
  return { ...source, snapshots };
}

function pinnedRunContext(ctx: AutoEditCtx, source: RunSource, token: string): AutoEditCtx {
  try {
    const pinned = prepareAutoEditRunContext({
      ctx, runId: token, resume: Boolean(source.job),
      savedDoctrine: source.job?.ctx.doctrine, savedPipeline: source.job?.ctx.pipeline,
    });
    return { ...pinned,
      brainSessionId: retainedClaudeSessionId(source.job?.ctx.brainSessionId),
      brainSessionEstablished: source.job?.ctx.brainSessionEstablished === true };
  } catch (error) {
    const action = source.job
      ? "The saved checkpoint's pinned Producer authority is missing or invalid; preserve it for diagnosis and start a fresh edit."
      : "Producer doctrine and pipeline could not be pinned before launch.";
    throw new RequestFailure(`${action} ${(error as Error).message}`, 409);
  }
}

function runDescription(source: RunSource, resume: boolean): {
  phase: AutoEditJob["phase"];
  message: string;
} {
  const phase = source.job
    ? source.job.phase : source.bootstrapPlanHash ? "planning_review" : "authoring";
  const message = resume ? "Resuming Auto Edit from its last safe checkpoint."
    : source.bootstrapPlanHash
      ? "Reviewing the saved timeline before rendering an isolated candidate."
      : "Starting Auto Edit in a detached worker.";
  return { phase, message };
}

interface WorkerLaunch {
  ctx: AutoEditCtx;
  pinnedCtx: AutoEditCtx;
  source: RunSource;
  token: string;
  phase: AutoEditJob["phase"];
  message: string;
}

async function launchWorker(input: WorkerLaunch): Promise<void> {
  const { ctx, pinnedCtx, source, token, phase, message } = input;
  let job: AutoEditJob | undefined;
  try {
    job = startAutoEditJob({ ctx: pinnedCtx, token, snapshots: source.snapshots,
      resume: source.job, bootstrapPlanHash: source.bootstrapPlanHash });
    beginProducerRunWithToken({ dir: ctx.dir, kind: "auto_edit", phase, message, token });
    const workerPid = await launchDetachedAutoEditWorker(autoEditJobPath(ctx.dir));
    dlog("producer:auto-edit", "detached worker launched", {
      dir: ctx.dir, workerPid, checkpoint: job.checkpoint, logPath: job.logPath,
    });
  } catch (error) {
    const message = `Detached Auto Edit worker failed to launch: ${(error as Error).message}`;
    if (job) {
      try { failAutoEditJob(autoEditJobPath(ctx.dir), token, message); } catch {}
    }
    failProducerRun(ctx.dir, token, message);
    derror("producer:auto-edit", message, error);
    throw new RequestFailure(message, 500);
  }
}

export async function startDetachedRun(request: PreparedRequest): Promise<StartedRun> {
  const { ctx, resume } = request;
  const source = await preparedRunSource(request, inactiveDurableJob(ctx));
  const token = newProducerRunToken();
  const pinnedCtx = pinnedRunContext(ctx, source, token);
  await launchWorker({ ctx, pinnedCtx, source, token, ...runDescription(source, resume) });
  return { jobPath: autoEditJobPath(ctx.dir), token };
}
