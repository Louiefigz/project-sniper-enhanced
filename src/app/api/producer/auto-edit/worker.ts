import {
  appendAutoEditJobEvent,
  failAutoEditJob,
  interruptAutoEditJob,
  markAutoEditWorker,
  heartbeatAutoEditJob,
  durableProcessAlive,
  durableProcessGroupAlive,
  readAutoEditJob,
  type CheckpointUpdate,
  type AutoEditJob,
} from "@/lib/server/auto-edit-job-store";
import { createBrainHeartbeat } from "@/lib/server/auto-edit-heartbeat";
import { boundAutoEditLog } from "@/lib/server/auto-edit-log";
import { boundedAutoEditProgressMessage } from "@/lib/producer/project-state";
import { eventElapsedSuffix } from "@/lib/producer/auto-edit-progress";
import {
  appendProducerRunEvent,
  failProducerRun,
  heartbeatProducerRun,
  interruptProducerRun,
  updateProducerRun,
} from "@/lib/server/producer-run-registry";
import { runAutoEditPipeline } from "./pipeline";
import { diskCheckpointWriter, diskInvalidationWriter } from "./pipeline-writers";
import {
  PROCESS_TERM_GRACE_MS,
  terminateTrackedProcessTrees,
} from "../../_lib/child-process-lifecycle";
import { brainProvider, brainProviderLabel, type BrainProvider } from "../../_lib/ai-provider";
import { settleWorkerExecution, withWorkerMutationLease } from "./worker-outcome";
import { timedStage } from "@/lib/server/stage-timing";
import { withStageTimingContext } from "@/lib/server/stage-timing-context";
import type { ProjectMutationLease } from "@/lib/server/project-mutation-lease";
import { renderPrivateCutPreview } from "./cut-preview";
import { verifyHumanAcceptedCut } from "@/lib/server/human-cut-acceptance-store";
import { verifyHumanAcceptedSourceBytes } from "@/lib/server/human-cut-source-verification";
import { runBootstrapWorker } from "@/lib/server/guided-project-bootstrap-worker";
import { retainBootstrapFailure } from "@/lib/server/guided-project-bootstrap-store";
import { hasGuidedBootstrap } from "@/lib/server/guided-project-bootstrap-contract";
import { authoredPreparationRemainingMs, withAuthoredPreparationDeadline,
  AUTHORED_PREPARATION_LIMIT_MS } from "@/lib/server/guided-project-preparation-deadline";

const TRACKED_TREE_GRACE_MS = PROCESS_TERM_GRACE_MS - 1_000;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function claimJob(jobPath: string, token: string) {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    const job = readAutoEditJob(jobPath);
    if (job?.status === "cut_accepted" && job.token === token) { await delay(25); continue; }
    if (!job || job.status !== "running") throw new Error(`No runnable Auto Edit job at ${jobPath}`);
    if (job.token !== token) throw new Error(`Auto Edit worker token ${token} is stale`);
    if (job.workerPid === process.pid) {
      if (durableProcessAlive(job.workerPid, job.workerIdentity, job.updatedAt)) return job;
      throw new Error(`Auto Edit worker ${process.pid} does not match its durable process identity`);
    }
    if (durableProcessGroupAlive(job.workerPid, job.workerIdentity, job.updatedAt)) {
      throw new Error(`Auto Edit job is already owned by worker ${job.workerPid}`);
    }
    await delay(25);
  }
  const current = readAutoEditJob(jobPath);
  if (current?.cutAcceptance || (current && hasGuidedBootstrap(current.ctx))) throw new Error("Cut worker did not receive the exact parent ownership handoff");
  return markAutoEditWorker(jobPath, token, process.pid);
}

function progressMessage(payload: Record<string, unknown>): string | null {
  const bounded = boundedAutoEditProgressMessage(payload);
  if (bounded) return bounded;
  const event = typeof payload.event === "string" ? payload.event : "";
  const provider = payload.provider === "legacy" || payload.provider === "codex"
    ? payload.provider as BrainProvider
    : brainProvider();
  const brain = brainProviderLabel(provider);
  if (event === "cut_preview_started") return "Rendering and verifying the exact cut preview; visual authoring has not started.";
  if ((event === "palmier_native_progress" || event === "candidate_qc_progress"
      || event === "palmier_primary_blocked")
      && typeof payload.message === "string") return payload.message;
  if (event === "palmier_primary_selected") {
    const limits = Array.isArray(payload.limitations) ? payload.limitations : [];
    const lanes = limits.map((item) => item && typeof item === "object"
      ? (item as Record<string, unknown>).lane : null).filter(Boolean).join(", ");
    return `Palmier-native editable build selected${lanes ? `; declared limits: ${lanes}` : ""}.`;
  }
  if (event === "start") {
    const workbench = payload.workbench === "MP4" ? "MP4 delivery" : "Palmier";
    return `${brain} started Auto Edit in its detached worker; ${workbench} is the workbench.`;
  }
  if (event === "authoring_started" && payload.stage === "cut") {
    return `${brain} is authoring the transcript-first cut.`;
  }
  if (event === "authoring_started") return `${brain} is authoring the governed visual plan.`;
  if (event === "authoring_thread.started" || event === "authoring_turn.started") {
    return `${brain} authoring session started.`;
  }
  if (event === "authoring_done" && payload.stage === "cut") {
    return `${brain} finished the transcript cut${eventElapsedSuffix(payload)}; independent cut review is next.`;
  }
  if (event === "authoring_done") {
    return `${brain} finished the visual edit plan${eventElapsedSuffix(payload)}; deterministic gates and planning review are next.`;
  }
  if (event === "lint") return payload.ok ? "Edit plan passed lint." : "Edit plan failed lint.";
  if (event === "reference_lint") {
    return payload.ok ? "Edit plan passed the reference-profile gate." : "Edit plan failed the reference-profile gate.";
  }
  if (event === "outputs" && payload.approved === true
      && payload.mode === "palmier-native-initial") {
    return "Approved editable Palmier timeline is ready.";
  }
  if (event === "outputs" && payload.approved === true) return "Approved final video is ready.";
  if (event === "outputs") return "Final video was written to disk.";
  if (event === "resume") return String(payload.message ?? "Resuming Auto Edit.");
  const status = typeof payload.status === "string" ? payload.status.replaceAll("_", " ") : "";
  return status ? [payload.stage, status, payload.note].filter(Boolean).join(" · ") : null;
}

function parsedLine(line: string): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(line);
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return value as Record<string, unknown>;
    }
  } catch {
    // Non-JSON worker output remains visible as a bounded log event.
  }
  return { event: "log", stream: "stdout", text: line.slice(0, 2_000) };
}

async function runOwnedWorker(
  jobPath: string,
  token: string,
  initialJob: AutoEditJob,
  lease: ProjectMutationLease,
): Promise<void> {
  let job = initialJob;
  const heartbeat = createBrainHeartbeat((message) => {
    const updated = heartbeatAutoEditJob(jobPath, token, message);
    heartbeatProducerRun(updated.ctx.dir, updated.token, updated.phase, message);
    job = updated;
  });

  const send = (payload: Record<string, unknown>) => {
    appendAutoEditJobEvent(jobPath, token, payload);
    const progress = progressMessage(payload);
    if (progress) appendProducerRunEvent(job!.ctx.dir, job!.token, progress);
    heartbeat.observe(payload);
  };
  const advanceOnDisk = diskCheckpointWriter(jobPath, token);
  const invalidateOnDisk = diskInvalidationWriter(jobPath, token);
  const advance = (update: CheckpointUpdate) => {
    const updated = advanceOnDisk(update);
    updateProducerRun(updated.ctx.dir, updated.token, update.phase, update.message);
    job = updated;
    return updated;
  };

  await settleWorkerExecution({
    jobPath, token, send, stopHeartbeat: heartbeat.stop,
    run: () => runAutoEditPipeline({
      job,
      io: {
        send,
        sendRaw: (line) => send(parsedLine(line)),
        advance,
        invalidate: (update) => {
          const updated = invalidateOnDisk(update);
          updateProducerRun(updated.ctx.dir, updated.token, update.phase, update.message);
          job = updated;
          return updated;
        },
      },
    }, { cutApprovalAccepted: async (currentJob, verified) => {
      verifyHumanAcceptedCut(currentJob, verified);
      await verifyHumanAcceptedSourceBytes({ job: currentJob, lease });
      return true;
    }, prepareCutPreview: async (currentJob, request) => {
      const { receipt } = await renderPrivateCutPreview({ job: currentJob, request, lease });
      return { executionKey: receipt.executionKey, receiptHash: receipt.receiptHash };
    } }),
  });
}

async function runWorker(jobPath: string, token: string, expire: (job: AutoEditJob) => void): Promise<void> {
  const job = await claimJob(jobPath, token);
  await withAuthoredPreparationDeadline(job, () => expire(job), () => withStageTimingContext({
    runId: job.artifactToken ?? job.token, attemptId: job.token, attemptNo: job.attempts,
  }, () => timedStage(job.ctx.dir, "worker_run", () => runClaimedWorker(jobPath, token, job))));
}

async function runClaimedWorker(jobPath: string, token: string, job: AutoEditJob): Promise<void> {
  await withWorkerMutationLease(job, (lease) => runBootstrapWorker(job, lease, () => runOwnedWorker(jobPath, token, job, lease)));
}

function markInterrupted(jobPath: string, token: string, signal: string): void {
  const job = readAutoEditJob(jobPath);
  if (job?.token === token && hasGuidedBootstrap(job.ctx)) {
    try { retainBootstrapFailure(job.ctx.dir, `Bootstrap worker received ${signal}; nested cleanup is unknown`, { verified: false, forcedStop: true }); }
    catch { console.error("[SNIPER:bootstrap] Unable to retain shutdown uncertainty; no recovery is authorized"); }
  }
  if (!job || job.token !== token || job.status !== "running") return;
  const message = `Detached Auto Edit worker received ${signal} during ${job.phase}; resume from ${job.checkpoint}.`;
  try { appendAutoEditJobEvent(jobPath, token, { event: "interrupted", signal, message }); } catch {}
  try { interruptAutoEditJob(jobPath, token, message, process.pid); } catch {}
  try { interruptProducerRun(job.ctx.dir, token, message); } catch {}
}

/** Retain the deadline cause and uncertainty before invoking the existing signal shutdown. */
function markPreparationExpired(jobPath: string, token: string, job: AutoEditJob): void {
  let message = "Authored cut PREPARATION expired; cleanup remains unknown";
  try { authoredPreparationRemainingMs(job.ctx); }
  catch (error) { message = error instanceof Error ? error.message : String(error); }
  try { retainBootstrapFailure(job.ctx.dir, message, { verified: false, forcedStop: true }); }
  catch { console.error("[SNIPER:bootstrap] Unable to retain preparation deadline uncertainty; no recovery is authorized"); }
  try { appendAutoEditJobEvent(jobPath, token, { event: "authored_preparation_deadline", message,
    limitMs: AUTHORED_PREPARATION_LIMIT_MS, cleanup: "unknown", retryable: false }); } catch {}
}

function terminateOwnProcessGroup(signal: "SIGINT" | "SIGTERM"): never {
  process.removeAllListeners("SIGINT");
  process.removeAllListeners("SIGTERM");
  if (process.platform !== "win32") {
    try { process.kill(-process.pid, signal); } catch {}
  }
  process.exit(signal === "SIGINT" ? 130 : 143);
}

async function main(): Promise<void> {
  const jobPath = process.argv[2];
  const token = process.argv[3];
  if (!jobPath || !token) throw new Error("Usage: worker.ts <absolute-job-path> <token>");
  let stopping = false;
  const onSignal = (signal: "SIGINT" | "SIGTERM") => {
    if (stopping) return;
    stopping = true;
    markInterrupted(jobPath, token, signal);
    terminateTrackedProcessTrees(TRACKED_TREE_GRACE_MS);
    // Remain alive long enough to hard-kill detached brain/gate subgroups.
    // The outer Stop escalation has a longer grace and remains the final fence.
    setTimeout(() => terminateOwnProcessGroup(signal), TRACKED_TREE_GRACE_MS + 250);
  };
  process.once("SIGINT", () => onSignal("SIGINT"));
  process.once("SIGTERM", () => onSignal("SIGTERM"));
  try {
    await runWorker(jobPath, token, (job) => { markPreparationExpired(jobPath, token, job); onSignal("SIGTERM"); });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const job = readAutoEditJob(jobPath);
    try { appendAutoEditJobEvent(jobPath, token, { event: "error", message }); } catch {}
    try { failAutoEditJob(jobPath, token, message); } catch {}
    if (job?.token === token && job.status === "running") {
      failProducerRun(job.ctx.dir, token, message);
    }
    console.error(`[SNIPER:auto-edit-worker] ${message}`);
    if (error instanceof Error && error.stack) console.error(error.stack);
    process.exitCode = 1;
  } finally {
    const job = readAutoEditJob(jobPath);
    if (job?.token === token) {
      try { boundAutoEditLog(job.logPath); } catch {}
    }
  }
}

void main();
