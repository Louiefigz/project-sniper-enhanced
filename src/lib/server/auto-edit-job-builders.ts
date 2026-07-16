import { autoEditLogPath } from "./auto-edit-log";
import { autoEditRequestKey } from "./auto-edit-hash";
import type { AutoEditJob, NewAutoEditJobArgs } from "./auto-edit-job-types";

export function resumedJob(
  args: NewAutoEditJobArgs,
  current: AutoEditJob,
  now: string,
): AutoEditJob {
  const {
    orphanedWorkerGroup: _orphan,
    orphanedWorkerIdentity: _orphanIdentity,
    ...safe
  } = current;
  void _orphan;
  void _orphanIdentity;
  return {
    ...safe,
    qualityPolicyVersion: 1,
    token: args.token,
    artifactToken: current.artifactToken ?? current.token,
    requestKey: autoEditRequestKey(args.ctx),
    ctx: args.ctx,
    status: "running",
    snapshots: args.snapshots,
    attempts: current.attempts + 1,
    activeEventStartId: current.nextEventId,
    updatedAt: now,
    workerPid: undefined,
    workerIdentity: undefined,
    logPath: autoEditLogPath(args.ctx.dir),
    planningRound: current.planningRound ?? 0,
    // Pre-cycle journals counted spawns; treating that as the cycle floor is
    // conservative — resume can never widen a budget the old arithmetic spent.
    planningCycles: current.planningCycles ?? current.planningRound ?? 0,
    planningCleanRounds: current.planningCleanRounds ?? 0,
    qcRound: current.qcRound ?? 0,
    error: undefined,
  };
}

export function freshJob(args: NewAutoEditJobArgs, now: string): AutoEditJob {
  return {
    version: 1,
    qualityPolicyVersion: 1,
    token: args.token,
    artifactToken: args.token,
    requestKey: autoEditRequestKey(args.ctx),
    ctx: args.ctx,
    status: "running",
    checkpoint: args.bootstrapPlanHash ? "plan_authored" : "queued",
    phase: args.bootstrapPlanHash ? "planning_review" : "authoring",
    message: args.bootstrapPlanHash
      ? "Recovered the saved edit plan; bounded planning review will continue next."
      : "Auto Edit is queued in the detached worker.",
    snapshots: args.snapshots,
    attempts: 1,
    planningRound: 0,
    planningCycles: 0,
    planningCleanRounds: 0,
    qcRound: 0,
    requestedAt: now,
    updatedAt: now,
    logPath: autoEditLogPath(args.ctx.dir),
    ...(args.bootstrapPlanHash ? { planHash: args.bootstrapPlanHash } : {}),
    nextEventId: 1,
    activeEventStartId: 1,
    events: [],
  };
}
