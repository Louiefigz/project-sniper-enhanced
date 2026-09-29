import type { PipelineDependencies } from "./pipeline-dependencies";
import type { PipelineOutcome, PipelineRuntime } from "./pipeline-types";

/** Persist one exact native handoff; ordinary routing continues in the caller. */
export function dispatchPipelineCreativeRoute(
  run: PipelineRuntime,
  deps: PipelineDependencies,
): PipelineOutcome | null {
  const dispatched = deps.dispatchRoute(run.job.ctx);
  if (dispatched.status !== "awaiting_native_author") return null;
  run.job = run.io.advance({
    checkpoint: "route_dispatched", phase: "planning_review",
    message: "Native route inputs are frozen; waiting for the native scene author.",
    nativeHandoff: dispatched.handoff,
  });
  run.io.send({ event: "awaiting_native_author", route: dispatched.route,
    handoff: dispatched.handoff, message: run.job.message });
  return dispatched;
}
