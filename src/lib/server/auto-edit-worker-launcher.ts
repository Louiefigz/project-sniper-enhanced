import { spawn, type ChildProcess, type SpawnOptions } from "child_process";
import { closeSync, existsSync } from "fs";
import path from "path";
import { prepareAutoEditLog } from "./auto-edit-log";
import {
  markAutoEditWorker,
  readAutoEditJob,
} from "./auto-edit-job-store";
import { setProducerRunOwner } from "./producer-run-registry";
import { markHumanCutWorker } from "./human-cut-continuation";

type SpawnWorker = (command: string, args: readonly string[], options: SpawnOptions) => ChildProcess;

export interface WorkerInvocation {
  command: string;
  args: string[];
  cwd: string;
}

interface LauncherDependencies {
  repoRoot?: string;
  nodePath?: string;
  spawnWorker?: SpawnWorker;
}

export function detachedWorkerInvocation(
  jobPath: string,
  token: string,
  repoRoot = process.cwd(),
  nodePath = process.execPath,
): WorkerInvocation {
  const worker = path.join(repoRoot, "src", "app", "api", "producer", "auto-edit", "worker.ts");
  return { command: nodePath, args: ["--import", "tsx", worker, jobPath, token], cwd: repoRoot };
}

export async function launchDetachedAutoEditWorker(
  jobPath: string,
  dependencies: LauncherDependencies = {},
): Promise<number> {
  const job = readAutoEditJob(jobPath);
  if (!job || !["running", "cut_accepted"].includes(job.status)) throw new Error(`No runnable Auto Edit job at ${jobPath}`);
  if (job.orphanedWorkerGroup) throw new Error("Previous Auto Edit worker processes are still stopping");
  const invocation = detachedWorkerInvocation(
    jobPath,
    job.token,
    dependencies.repoRoot,
    dependencies.nodePath,
  );
  const tsxPackage = path.join(invocation.cwd, "node_modules", "tsx", "package.json");
  if (!dependencies.spawnWorker && !existsSync(tsxPackage)) {
    throw new Error(`Detached worker runtime is missing: ${tsxPackage}`);
  }
  const logFd = prepareAutoEditLog(job.logPath, job.attempts);
  let child: ChildProcess;
  try {
    child = (dependencies.spawnWorker ?? spawn)(invocation.command, invocation.args, {
      cwd: invocation.cwd,
      env: {
        ...process.env,
        ...(job.ctx.pipeline ? { SNIPER_PIPELINE_ROOT: job.ctx.pipeline.snapshotRoot } : {}),
        SNIPER_RUNTIME_REPO_ROOT: invocation.cwd,
      },
      detached: true,
      stdio: ["ignore", logFd, logFd],
    });
  } finally {
    closeSync(logFd);
  }
  if (job.cutAcceptance) child.once("error", () => { /* The durable PID/identity owns failure recovery after handoff. */ });
  if (!child.pid) throw new Error("Detached Auto Edit worker started without a PID");
  if (job.status === "cut_accepted") markHumanCutWorker(jobPath, job.token, child.pid);
  else markAutoEditWorker(jobPath, job.token, child.pid);
  try { setProducerRunOwner(job.ctx.dir, job.token, child.pid, true); }
  catch { /* The durable job is authoritative; a status-mirror write cannot undo its handoff. */ }
  child.unref();
  return child.pid;
}
