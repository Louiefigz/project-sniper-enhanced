import type { PipelineDependencies } from "./pipeline";
import type { PipelineRuntime } from "./pipeline-types";
import type { QualityLoopResult } from "./quality-loop";

/**
 * The approved mirror still fails loudly (palmier_checkpoint_failed), but by
 * the time it runs the deliverable final.mp4 already exists and the outputs
 * event has fired — so a mirror failure fails the PUSH step, never the job.
 */
export async function publishApprovedMirror(
  run: PipelineRuntime,
  deps: PipelineDependencies,
): Promise<void> {
  try {
    await deps.approvedMirror(run.job.ctx, run.io.send);
  } catch (error) {
    run.io.send({
      event: "palmier_mirror_failed", stage: "qc-approved", status: "failed",
      message: (error as Error).message,
    });
  }
}

/**
 * The render→Palmier courtesy checkpoint overlaps only QC's READ-ONLY phase
 * (Audit B + the visual critics). The checkpoint subprocess reads
 * edit_plan.json and the candidate file, and QC's approval path MOVES that
 * candidate (promote) while its repair path REWRITES the plan (revise) and
 * opens its own Palmier publish — so the quality loop's
 * renderCheckpointSettled barrier settles this publish before its first
 * mutation. Failure semantics match the old serial await: courtesy outcomes
 * (committed/warned/deferred) stay non-fatal, a real checkpoint rejection
 * still fails the run and wins over a QC error, and the round never resolves
 * while the publish is still in flight.
 */
export async function qualityRoundWithRenderCheckpoint(
  run: PipelineRuntime,
  deps: PipelineDependencies,
): Promise<QualityLoopResult> {
  const renderCheckpoint = {
    stage: "render" as const, round: run.job.qcRound ?? 0,
    ...(run.job.candidatePath ? { mediaPath: run.job.candidatePath } : {}),
  };
  const checkpointFailure = deps.checkpoint(run.job.ctx, renderCheckpoint, run.io.send)
    .then(() => null, (error: unknown) => ({ error }));
  const renderCheckpointSettled = async (): Promise<void> => {
    const failure = await checkpointFailure;
    if (failure) throw failure.error;
  };
  const round = await deps.quality(run, { renderCheckpointSettled }).then(
    (result) => ({ result }),
    (error: unknown) => ({ error }),
  );
  const failure = await checkpointFailure;
  if (failure) throw failure.error;
  if (!("result" in round)) throw round.error;
  return round.result;
}
