import {
  appendAutoEditJobEvent,
  autoEditJobPath,
  interruptAutoEditJob,
  readAutoEditJob,
  StaleAutoEditWorkerError,
  type AutoEditJob,
} from "./auto-edit-job-store";
import {
  durableProcessGroupAlive,
  type ProcessIdentity,
} from "./process-liveness";
import { interruptProducerRun } from "./producer-run-registry";

export class AutoEditStopConflictError extends Error {}
export class AutoEditStopSignalError extends Error {}

export const AUTO_EDIT_STOP_GRACE_MS = 6_000;

export interface AutoEditStopInput {
  dir: string;
  token: string;
}

export interface AutoEditStopResult {
  status: "interrupted";
  checkpoint: AutoEditJob["checkpoint"];
  phase: AutoEditJob["phase"];
  workerPid: number;
  signaled: boolean;
  message: string;
}

type KillProcess = (pid: number, signal: NodeJS.Signals) => void;
type StopTimer = ReturnType<typeof setTimeout> & { unref?: () => void };
type ScheduleStop = (callback: () => void, delayMs: number) => StopTimer;

interface StopDependencies {
  kill?: KillProcess;
  groupAlive?: (pid: number, identity: ProcessIdentity | undefined, updatedAt: string) => boolean;
  schedule?: ScheduleStop;
  graceMs?: number;
}

interface EscalationInput {
  pid: number;
  job: AutoEditJob;
  kill: KillProcess;
  groupAlive: NonNullable<StopDependencies["groupAlive"]>;
  dependencies: StopDependencies;
}

/** Negative PID addresses the detached POSIX group; Windows addresses its worker. */
export function workerSignalTarget(pid: number, platform: NodeJS.Platform): number {
  if (!Number.isInteger(pid) || pid < 1) throw new Error("worker PID must be a positive integer");
  return platform === "win32" ? pid : -pid;
}

function requiredTarget(input: AutoEditStopInput): { jobPath: string; job: AutoEditJob; pid: number } {
  const jobPath = autoEditJobPath(input.dir);
  const job = readAutoEditJob(jobPath);
  if (!job) throw new AutoEditStopConflictError("Auto Edit job is missing or invalid");
  if (job.ctx.dir !== input.dir) {
    throw new AutoEditStopConflictError("Auto Edit job does not belong to this project");
  }
  if (job.token !== input.token) {
    throw new AutoEditStopConflictError("Auto Edit attempt changed; refresh before stopping it");
  }
  if (job.status !== "running") {
    throw new AutoEditStopConflictError(`Auto Edit is already ${job.status}`);
  }
  if (!job.workerPid) throw new AutoEditStopConflictError("Detached worker has not started yet");
  return { jobPath, job, pid: job.workerPid };
}

function interruptionMessage(job: AutoEditJob): string {
  return `Stopped by the operator during ${job.phase.replaceAll("_", " ")}. `
    + "Completed checkpoints are saved; Resume Edit will continue from the latest safe checkpoint.";
}

function scheduleStopEscalation(input: EscalationInput): void {
  const { pid, job, kill, groupAlive, dependencies } = input;
  const schedule = dependencies.schedule ?? setTimeout;
  const timer = schedule(() => {
    if (!groupAlive(pid, job.workerIdentity, job.updatedAt)) return;
    try {
      kill(workerSignalTarget(pid, process.platform), "SIGKILL");
    } catch (error) {
      if (groupAlive(pid, job.workerIdentity, job.updatedAt)) {
        console.error(`[SNIPER:auto-edit-stop] worker ${pid} survived SIGKILL`, error);
      }
    }
  }, dependencies.graceMs ?? AUTO_EDIT_STOP_GRACE_MS);
  timer.unref?.();
}

/** Fence the durable attempt first, then terminate only its recorded worker group. */
export function stopAutoEdit(
  input: AutoEditStopInput,
  dependencies: StopDependencies = {},
): AutoEditStopResult {
  const { jobPath, job, pid } = requiredTarget(input);
  const message = interruptionMessage(job);
  let interrupted: AutoEditJob;
  try {
    appendAutoEditJobEvent(jobPath, input.token, {
      event: "stop_requested",
      checkpoint: job.checkpoint,
      phase: job.phase,
      message,
    });
    interrupted = interruptAutoEditJob(jobPath, input.token, message, pid);
  } catch (error) {
    if (error instanceof StaleAutoEditWorkerError) {
      throw new AutoEditStopConflictError(error.message);
    }
    throw error;
  }
  interruptProducerRun(input.dir, input.token, message);

  const kill = dependencies.kill ?? ((target, signal) => { process.kill(target, signal); });
  const groupAlive = dependencies.groupAlive ?? durableProcessGroupAlive;
  // Tests may inject a synthetic PID/kill pair. Production must prove the
  // recorded group still belongs to this attempt before signaling it.
  const targetCurrent = dependencies.groupAlive
    ? true
    : groupAlive(pid, job.workerIdentity, job.updatedAt);
  let signaled = targetCurrent;
  try {
    if (targetCurrent) kill(workerSignalTarget(pid, process.platform), "SIGTERM");
  } catch (error) {
    signaled = false;
    if (groupAlive(pid, job.workerIdentity, job.updatedAt)) {
      throw new AutoEditStopSignalError(
        `Checkpoint was saved, but worker ${pid} could not be stopped: ${(error as Error).message}`,
      );
    }
  }
  if (signaled) {
    scheduleStopEscalation({ pid, job, kill, groupAlive, dependencies });
  }
  return {
    status: "interrupted",
    checkpoint: interrupted.checkpoint,
    phase: interrupted.phase,
    workerPid: pid,
    signaled,
    message,
  };
}
