import { AsyncLocalStorage } from "node:async_hooks";
import { randomUUID } from "node:crypto";

/** Telemetry identity only; never an edit-approval or mutation authority. */
export interface StageTimingContext {
  runId: string;
  attemptId: string;
  attemptNo: number;
  parentSpanId?: string;
}

export interface StageTimingMetadata {
  provider?: string;
  model?: string;
  effort?: string;
  phase?: string;
  cache?: "hit" | "miss" | "unproved";
  round?: number;
  packetBytes?: number;
  promptBytes?: number;
  deadlineMs?: number;
  lens?: string;
  evidenceImages?: number;
  exitCode?: number;
}

const context = new AsyncLocalStorage<StageTimingContext>();
const writerId = randomUUID();

/** Scope identity to this async call tree, isolating concurrent projects. */
export function withStageTimingContext<T>(value: StageTimingContext, run: () => T): T {
  return context.run({ ...value }, run);
}

/** Standalone helpers may supply a job identity, but must not overwrite an
 * enclosing execution UUID or sever its parent span when invoked by a stage. */
export function withStageTimingFallback<T>(value: StageTimingContext, run: () => T): T {
  return context.getStore() ? run() : withStageTimingContext(value, run);
}

/** Read stable attempt lineage or explicitly identify standalone execution. */
export function stageTimingContext(): StageTimingContext {
  return context.getStore() ?? {
    runId: `standalone:${writerId}`,
    attemptId: writerId,
    attemptNo: 1,
  };
}

/** A process incarnation is the only domain where monotonic subtraction is valid. */
export function stageTimingWriter() {
  return { writerId, writerPid: process.pid, clock: "process-monotonic" } as const;
}

/** Pass explicit parent context to a child, without mutating global process.env. */
export function stageTimingEnv(): NodeJS.ProcessEnv {
  const value = stageTimingContext();
  return {
    ...process.env,
    SNIPER_TIMING_RUN_ID: value.runId,
    SNIPER_TIMING_ATTEMPT_ID: value.attemptId,
    SNIPER_TIMING_ATTEMPT_NO: String(value.attemptNo),
    SNIPER_TIMING_PARENT_SPAN_ID: value.parentSpanId ?? "",
  };
}

/** Only bounded diagnostic scalars; never prompts, transcripts or error payloads. */
export function timingMetadata(value: StageTimingMetadata = {}): StageTimingMetadata {
  const result: Record<string, string | number> = {};
  for (const key of ["provider", "model", "effort", "phase", "cache", "lens"] as const) {
    const item = value[key];
    if (typeof item === "string" && item.length <= 128) result[key] = item;
  }
  for (const key of ["round", "packetBytes", "promptBytes", "deadlineMs", "evidenceImages", "exitCode"] as const) {
    const item = value[key];
    if (typeof item === "number" && Number.isFinite(item)) result[key] = item;
  }
  return result;
}
