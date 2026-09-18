import path from "node:path";
import { randomUUID } from "node:crypto";
import { atomicWriteJsonSync } from "./atomic-file";
import { autoEditJobPath, StaleAutoEditWorkerError } from "./auto-edit-job-persistence";
import { withAutoEditJobLock } from "./auto-edit-job-lock";
import { resumedJob } from "./auto-edit-job-builders";
import { captureProcessIdentity, durableProcessAlive } from "./process-liveness";
import { activeHumanCutAcceptance, createHumanCutIndex, humanCutDirectory, observeHumanCutJob } from "./human-cut-acceptance-store";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import type { AutoEditJob } from "./auto-edit-job-types";

function intentPath(job: AutoEditJob): string {
  if (!/^[0-9a-f-]{36}$/.test(job.token)) throw new Error("Accepted continuation requires its server-generated fencing token");
  return path.join(job.ctx.dir, "human-cut-launches", `${job.token}.json`);
}

function existingIntent(job: AutoEditJob): boolean {
  try {
    const row = readCutPreviewObject(intentPath(job)).value;
    if (row.kind !== "human-cut-launch-intent" || row.token !== job.token || row.attempt !== job.attempts
        || row.acceptanceHash !== job.cutAcceptance?.acceptanceHash) throw new Error("Accepted cut launch intent is malformed");
    return true;
  } catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return false; throw error; }
}

/** A prior possible spawn is never replayed with the same token. Its child is fenced, not blindly killed. */
export function prepareHumanCutContinuation(dir: string): AutoEditJob {
  const observed = observeHumanCutJob(dir);
  activeHumanCutAcceptance(observed.job);
  if (observed.job.status !== "cut_accepted") throw new Error("Only an accepted launch-pending cut can continue here");
  humanCutDirectory(dir, "human-cut-launches");
  const priorIntent = existingIntent(observed.job);
  return withAutoEditJobLock(autoEditJobPath(dir), () => {
    const current = observeHumanCutJob(dir);
    if (current.sha256 !== observed.sha256) throw new StaleAutoEditWorkerError("Accepted cut changed before launch preparation");
    const now = new Date().toISOString();
    const job: AutoEditJob = priorIntent ? { ...resumedJob({ ctx: current.job.ctx, token: randomUUID(),
      snapshots: current.job.snapshots }, current.job, now), status: "cut_accepted" } : current.job;
    if (priorIntent) atomicWriteJsonSync(autoEditJobPath(dir), job);
    createHumanCutIndex(intentPath(job), { schemaVersion: 1, kind: "human-cut-launch-intent",
      token: job.token, attempt: job.attempts, acceptanceHash: job.cutAcceptance!.acceptanceHash,
      createdAt: now, owner: captureProcessIdentity(process.pid) });
    return job;
  });
}

/** The parent alone activates this exact pending attempt after observing a real live child identity. */
export function markHumanCutWorker(jobPath: string, token: string, workerPid: number): AutoEditJob {
  const identity = captureProcessIdentity(workerPid), now = new Date().toISOString();
  if (!identity.startToken || !durableProcessAlive(workerPid, identity, now)) {
    throw new Error("Accepted continuation child has no confirmed live process identity");
  }
  return withAutoEditJobLock(jobPath, () => {
    const { job } = observeHumanCutJob(path.dirname(jobPath));
    if (job.token !== token || job.status !== "cut_accepted" || !job.cutAcceptance
        || job.workerPid || !existingIntent(job)) throw new StaleAutoEditWorkerError("Accepted worker handoff lost its fenced pending attempt");
    const running: AutoEditJob = { ...job, status: "running", workerPid, workerIdentity: identity, updatedAt: now,
      message: "Human cut accepted; the confirmed worker is continuing visual authoring. Final quality gates remain required." };
    atomicWriteJsonSync(jobPath, running);
    return running;
  });
}

/** This log is diagnostic, not permission to spawn, retry, or approve a final. */
export function recordHumanCutLaunchResult(job: AutoEditJob, result: Record<string, unknown>): void {
  createHumanCutIndex(path.join(job.ctx.dir, "human-cut-launches", `${job.token}-result.json`), {
    schemaVersion: 1, kind: "human-cut-launch-result", token: job.token, attempt: job.attempts,
    acceptanceHash: job.cutAcceptance!.acceptanceHash, completedAt: new Date().toISOString(), ...result,
  });
}
