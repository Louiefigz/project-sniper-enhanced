import {
  completeAutoEditJob, readAutoEditJob, type AutoEditJob,
} from "@/lib/server/auto-edit-job-store";
import { pauseAutoEditForCutApproval } from "@/lib/server/auto-edit-cut-pause-store";
import {
  completeProducerRun, producerRun, setProducerRunOwner,
} from "@/lib/server/producer-run-registry";
import { acquireAutoEditWorkerMutationLease } from "@/lib/server/auto-edit-worker-mutation-lease";
import { timedStage } from "@/lib/server/stage-timing";
import { mutationProjectRoot } from "../../_lib/project-mutation";
import type { PipelineOutcome } from "./pipeline-types";
import type { Send } from "./stream";
import type { ProjectMutationLease } from "@/lib/server/project-mutation-lease";
import { parseCutPreviewPointer } from "@/lib/producer/contracts/cut-approval-request";
import { sealBootstrapPause } from "@/lib/server/guided-project-bootstrap-quiescence";
import { bootstrapMayReleaseLease } from "@/lib/server/guided-project-bootstrap-worker";
import { hasGuidedBootstrap } from "@/lib/server/guided-project-bootstrap-contract";

interface WorkerExecution {
  jobPath: string;
  token: string;
  run: () => Promise<PipelineOutcome>;
  send: Send;
  stopHeartbeat: () => void;
}

/** A normal guided pause is neither a failed attempt nor completed delivery. */
export async function settleWorkerExecution(input: WorkerExecution): Promise<void> {
  try {
    const result = await input.run();
    input.stopHeartbeat();
    if (result.status === "awaiting_cut_approval") {
      const preview = parseCutPreviewPointer(result.preview);
      const current = readAutoEditJob(input.jobPath);
      if (!current || current.token !== input.token) throw new Error("Cut PAUSE lost its exact worker");
      await sealBootstrapPause(current, result.request, preview);
      const job = pauseAutoEditForCutApproval(input.jobPath, input.token, result.request, preview);
      producerRun(job.ctx.dir); // Project the durable waiting state into the run mirror.
      return;
    }
    if (result.status !== "completed") throw new Error("Auto Edit pipeline returned no explicit terminal outcome");
    const job = readAutoEditJob(input.jobPath);
    if (!job || job.token !== input.token) throw new Error("Auto Edit completion lost its job fence");
    if (hasGuidedBootstrap(job.ctx)) throw new Error("Guided cut bootstrap cannot approve delivery");
    input.send({ event: "complete", outDir: job.ctx.dir });
    completeAutoEditJob(input.jobPath, input.token);
    completeProducerRun(job.ctx.dir, input.token);
  } finally {
    input.stopHeartbeat();
  }
}

/** Legacy release is unchanged; bootstrap unknown cleanup retains its writer fence. */
export async function withWorkerMutationLease(
  job: AutoEditJob,
  run: (lease: ProjectMutationLease) => Promise<void>,
  acquire = acquireAutoEditWorkerMutationLease,
): Promise<void> {
  setProducerRunOwner(job.ctx.dir, job.token, process.pid, true);
  const lease = await timedStage(job.ctx.dir, "mutation_lease_wait", () =>
    acquire(mutationProjectRoot(job.ctx.dir)));
  try { await run(lease); }
  finally { if (bootstrapMayReleaseLease(job)) lease.release(); }
}
