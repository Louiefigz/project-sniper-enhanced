/** One source-brief preparation allocation, not the later post-cut generation target. */
import { AsyncLocalStorage } from "node:async_hooks";
import { isDeepStrictEqual } from "node:util";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import type { AutoEditJob } from "./auto-edit-job-types";
import { deadlineTimestamp, finiteDeadlineClock } from "./generation-attempt-clock";
import { parseAuthoredCutPolicy, type AuthoredCutPolicy } from "./guided-project-bootstrap-contract";

export const AUTHORED_PREPARATION_LIMIT_MS = 120 * 60_000;
type FailureKind = "expired" | "clock-invalid" | "binding-invalid" | "scope-closed";
type Timer = ReturnType<typeof setTimeout>;

/** A deadline failure never attests that child processes or other resources stopped. */
export class AuthoredPreparationDeadlineError extends Error {
  readonly code = "AUTHORED_PREPARATION_DEADLINE";
  readonly cleanup = "unknown";
  shutdownError: string | null = null;
  constructor(readonly kind: FailureKind) {
    super(`Authored cut PREPARATION ${kind}; fixed 120-minute engineering bound, cleanup remains unknown`);
    this.name = "AuthoredPreparationDeadlineError";
  }
}

/** Fixed host services; the mutable seam exists for clock/scheduler tests, not request configuration. */
export const authoredPreparationRuntime = {
  wall: () => Date.now(),
  monotonic: () => performance.now(),
  schedule: (callback: () => void, delayMs: number): Timer => setTimeout(callback, delayMs),
  cancel: (timer: Timer): void => clearTimeout(timer),
};
type Runtime = typeof authoredPreparationRuntime;
interface HeldClock {
  policy: AuthoredCutPolicy;
  dir: string;
  deadlineWall: number;
  beganMono: number;
  initialRemaining: number;
  previousWall: number;
  previousMono: number;
  runtime: Runtime;
  expire: () => void;
  failure: AuthoredPreparationDeadlineError | null;
  closed: boolean;
}
const activeClock = new AsyncLocalStorage<HeldClock>();

/** Wall-only prelaunch observations do not require or invent a monotonic origin. */
function wallClock(runtime: Runtime): number {
  try {
    const wall = finiteDeadlineClock(runtime.wall());
    if (!Number.isSafeInteger(wall)) throw new Error("fractional wall clock");
    return wall;
  } catch { throw new AuthoredPreparationDeadlineError("clock-invalid"); }
}

/** Live clocks independently observe wall and monotonic elapsed time. */
function clocks(runtime: Runtime): { wall: number; mono: number } {
  try { return { wall: wallClock(runtime), mono: finiteDeadlineClock(runtime.monotonic()) }; }
  catch { throw new AuthoredPreparationDeadlineError("clock-invalid"); }
}

/** Parse the retained policy; its intake/source authority remains the caller's responsibility. */
function original(ctx: AutoEditCtx): { policy: AuthoredCutPolicy; deadlineWall: number } {
  try {
    const policy = parseAuthoredCutPolicy(ctx.authoredCut);
    const deadlineWall = deadlineTimestamp(policy.preparationStartedAt) + AUTHORED_PREPARATION_LIMIT_MS;
    if (!Number.isSafeInteger(deadlineWall)) throw new Error("invalid deadline");
    return { policy, deadlineWall };
  } catch { throw new AuthoredPreparationDeadlineError("binding-invalid"); }
}

/** Prelaunch reads use the original wall origin and do not invent a live monotonic origin. */
function wallRemaining(ctx: AutoEditCtx, runtime: Runtime): number {
  const held = original(ctx), wall = wallClock(runtime);
  if (wall < held.deadlineWall - AUTHORED_PREPARATION_LIMIT_MS) throw new AuthoredPreparationDeadlineError("clock-invalid");
  const remaining = held.deadlineWall - wall;
  if (remaining <= 0) throw new AuthoredPreparationDeadlineError("expired");
  return remaining;
}

/** Poison before requesting shutdown, including reentrant guards called by the owner callback. */
function stop(clock: HeldClock, kind: FailureKind): AuthoredPreparationDeadlineError {
  if (clock.failure) return clock.failure;
  clock.failure = new AuthoredPreparationDeadlineError(kind);
  try { clock.expire(); }
  catch (error) { clock.failure.shutdownError = String(error).slice(0, 400); }
  return clock.failure;
}

/** A copied context may rejoin the same origin; missing or changed policy cannot reset it. */
function assertBinding(clock: HeldClock, ctx: AutoEditCtx): void {
  if (clock.closed) throw new AuthoredPreparationDeadlineError("scope-closed");
  if (clock.failure) throw clock.failure;
  let policy: AuthoredCutPolicy;
  try { policy = original(ctx).policy; }
  catch { throw stop(clock, "binding-invalid"); }
  if (ctx.dir !== clock.dir || !isDeepStrictEqual(policy, clock.policy)) throw stop(clock, "binding-invalid");
}

/** Charge both original wall time and elapsed live monotonic time; rollbacks poison permanently. */
function liveRemaining(clock: HeldClock, ctx: AutoEditCtx): number {
  assertBinding(clock, ctx);
  let observed: ReturnType<typeof clocks>;
  try { observed = clocks(clock.runtime); }
  catch { throw stop(clock, "clock-invalid"); }
  if (observed.wall < clock.previousWall || observed.mono < clock.previousMono) throw stop(clock, "clock-invalid");
  clock.previousWall = observed.wall; clock.previousMono = observed.mono;
  const remaining = Math.floor(Math.min(clock.deadlineWall - observed.wall,
    clock.initialRemaining - (observed.mono - clock.beganMono)));
  if (remaining <= 0) throw stop(clock, "expired");
  return remaining;
}

/** Return null only for legacy contexts outside an active authored-preparation scope. */
export function authoredPreparationRemainingMs(ctx: AutoEditCtx): number | null {
  const live = activeClock.getStore();
  if (live) return liveRemaining(live, ctx);
  if (ctx.authoredCut === undefined) return null;
  return wallRemaining(ctx, authoredPreparationRuntime);
}

/** Capture one live origin after the worker's exact parent ownership claim. */
function capture(job: AutoEditJob, expire: () => void): HeldClock {
  const runtime = { ...authoredPreparationRuntime }, held = original(job.ctx), observed = clocks(runtime);
  const initialRemaining = held.deadlineWall - observed.wall;
  if (observed.wall < held.deadlineWall - AUTHORED_PREPARATION_LIMIT_MS) throw new AuthoredPreparationDeadlineError("clock-invalid");
  if (initialRemaining <= 0) throw new AuthoredPreparationDeadlineError("expired");
  return { policy: structuredClone(held.policy), dir: job.ctx.dir, deadlineWall: held.deadlineWall,
    beganMono: observed.mono, initialRemaining, previousWall: observed.wall, previousMono: observed.mono,
    runtime, expire, failure: null, closed: false };
}

/** Check final clock even when work fails before the scheduled timer can be delivered. */
function settledFailure(clock: HeldClock, ctx: AutoEditCtx, error: unknown): unknown {
  try { liveRemaining(clock, ctx); }
  catch (failure) { return clock.failure ?? failure; }
  return error;
}

/** Await actual settlement; expiry requests owned shutdown but never races away live work. */
async function execute<T>(clock: HeldClock, ctx: AutoEditCtx, run: () => Promise<T>): Promise<T> {
  let timer: Timer | undefined;
  try {
    timer = clock.runtime.schedule(() => { if (!clock.closed) stop(clock, "expired"); }, liveRemaining(clock, ctx));
    liveRemaining(clock, ctx);
    const result = await run();
    liveRemaining(clock, ctx);
    return result;
  } catch (error) { throw settledFailure(clock, ctx, error); }
  finally { clock.closed = true; if (timer !== undefined) clock.runtime.cancel(timer); }
}

/** One aggregate scope/timer, including lease waits and settlement; legacy work is unchanged. */
export async function withAuthoredPreparationDeadline<T>(job: AutoEditJob,
  expire: () => void, run: () => Promise<T>): Promise<T> {
  if (activeClock.getStore()) {
    authoredPreparationRemainingMs(job.ctx);
    const result = await run();
    authoredPreparationRemainingMs(job.ctx);
    return result;
  }
  if (job.ctx.authoredCut === undefined) return run();
  const clock = capture(job, expire);
  return activeClock.run(clock, () => execute(clock, job.ctx, run));
}
