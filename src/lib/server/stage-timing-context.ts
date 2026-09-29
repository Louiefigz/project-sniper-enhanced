import { AsyncLocalStorage } from "node:async_hooks";
import { randomUUID } from "node:crypto";

/** Telemetry identity only; never an edit-approval, claim or mutation authority. */
export interface StageTimingContext {
  runId: string;
  attemptId: string;
  attemptNo: number;
  parentSpanId?: string;
  /** Optional task lineage (generic until the task authority names rows). */
  taskId?: string;
  claimEpoch?: number;
  hostTurnId?: string;
  /** Inherited environment fields that were malformed and therefore not used. */
  lineageRejected?: string[];
}

/** Closed span attribution vocabulary read by scripts/producer/stage_timing_attribution.py. */
export const STAGE_TIMING_ACTIVITIES = ["model", "tool", "host-slot-wait", "native-queue-wait", "pressure-wait"] as const;
export type StageTimingActivity = typeof STAGE_TIMING_ACTIVITIES[number];

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
  activity?: StageTimingActivity;
}

/** The only timing variables a closed child environment receives (same names as Python). */
export const STAGE_TIMING_LINEAGE_ENV = {
  runId: "SNIPER_TIMING_RUN_ID", attemptId: "SNIPER_TIMING_ATTEMPT_ID",
  attemptNo: "SNIPER_TIMING_ATTEMPT_NO", parentSpanId: "SNIPER_TIMING_PARENT_SPAN_ID",
  taskId: "SNIPER_TIMING_TASK_ID", claimEpoch: "SNIPER_TIMING_CLAIM_EPOCH",
  hostTurnId: "SNIPER_TIMING_HOST_TURN_ID",
} as const;
type LineageField = keyof typeof STAGE_TIMING_LINEAGE_ENV;
const LINEAGE_VARIABLES = new Set<string>(Object.values(STAGE_TIMING_LINEAGE_ENV));

const context = new AsyncLocalStorage<StageTimingContext>();
const writerId = randomUUID();

/** An opaque 1-256 character printable ASCII identifier without whitespace. */
export function boundedTimingId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 256 && /^[\x21-\x7e]+$/.test(value);
}

/** A claim epoch is a nonnegative safe integer. */
export function validClaimEpoch(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function parseLineage(field: LineageField, raw: string): string | number | undefined {
  if (field === "attemptNo" || field === "claimEpoch") {
    const number = /^[0-9]{1,16}$/.test(raw) ? Number(raw) : Number.NaN;
    const low = field === "attemptNo" ? 1 : 0;
    return Number.isSafeInteger(number) && number >= low ? number : undefined;
  }
  return boundedTimingId(raw) ? raw : undefined;
}

function standalone(): StageTimingContext {
  return { runId: `standalone:${writerId}`, attemptId: writerId, attemptNo: 1 };
}

const OPTIONAL_LINEAGE = ["parentSpanId", "taskId", "claimEpoch", "hostTurnId"] as const;

function optionalLineageValid(value: StageTimingContext, key: typeof OPTIONAL_LINEAGE[number]): boolean {
  const item = value[key];
  if (item === undefined) return true;
  if (key === "claimEpoch") return validClaimEpoch(item) && boundedTimingId(value.taskId);
  if (key === "hostTurnId") return boundedTimingId(item) && boundedTimingId(value.taskId);
  return boundedTimingId(item);
}

/**
 * Validate a context the same way as scripts/producer/stage_timing_context.py: ids are
 * bounded printable ASCII, a claim epoch or host turn needs a valid task. Timing never
 * fails work, so a malformed value is dropped and named in lineageRejected, never thrown.
 */
function sanitizedContext(value: StageTimingContext): StageTimingContext {
  const base = standalone();
  const result: StageTimingContext = {
    runId: boundedTimingId(value.runId) ? value.runId : base.runId,
    attemptId: boundedTimingId(value.attemptId) ? value.attemptId : base.attemptId,
    attemptNo: Number.isSafeInteger(value.attemptNo) && value.attemptNo >= 1 ? value.attemptNo : 1,
  };
  const rejected = new Set(value.lineageRejected ?? []);
  for (const key of ["runId", "attemptId", "attemptNo"] as const) {
    if (result[key] !== value[key]) rejected.add(key);
  }
  for (const key of OPTIONAL_LINEAGE) {
    if (!optionalLineageValid(value, key)) rejected.add(key);
    else if (value[key] !== undefined) Object.assign(result, { [key]: value[key] });
  }
  if (rejected.size) result.lineageRejected = [...rejected];
  return result;
}

/** Lineage a parent process forwarded in the environment; malformed values are named. */
function inheritedLineage(): StageTimingContext | undefined {
  const fields: Partial<Record<LineageField, string | number>> = {};
  const rejected: string[] = [];
  for (const [field, name] of Object.entries(STAGE_TIMING_LINEAGE_ENV) as [LineageField, string][]) {
    const raw = process.env[name];
    if (!raw) continue;
    const value = parseLineage(field, raw);
    if (value === undefined) rejected.push(field); else fields[field] = value;
  }
  if (Object.keys(fields).length === 0 && rejected.length === 0) return undefined;
  const base = standalone();
  return sanitizedContext({ ...base, ...fields, lineageRejected: rejected } as StageTimingContext);
}

/** Scope identity to this async call tree, isolating concurrent projects. */
export function withStageTimingContext<T>(value: StageTimingContext, run: () => T): T {
  return context.run(sanitizedContext(value), run);
}

/**
 * Nest one span under the current context (already validated when it was scoped). No
 * caller-supplied context enters the store here; a malformed span id nests nothing.
 */
export function withStageTimingChild<T>(spanId: string, run: () => T): T {
  return boundedTimingId(spanId) ? context.run({ ...stageTimingContext(), parentSpanId: spanId }, run) : run();
}

/**
 * A command launched by a timed parent process adopts the lineage that parent forwarded
 * in SNIPER_TIMING_*, for this call tree only. Nothing reads the environment implicitly:
 * a long-lived server started from a shell that exports these variables must not call
 * this for unrelated jobs, and its jobs keep their own (or standalone) identity.
 */
export function withInheritedStageTimingLineage<T>(run: () => T): T {
  const inherited = inheritedLineage();
  return inherited && !context.getStore() ? context.run(inherited, run) : run();
}

/** Standalone helpers may supply a job identity, but must not overwrite an
 * enclosing execution UUID or sever its parent span when invoked by a stage. */
export function withStageTimingFallback<T>(value: StageTimingContext, run: () => T): T {
  return context.getStore() ? run() : withStageTimingContext(value, run);
}

/** Read stable attempt lineage or explicitly identify standalone execution. */
export function stageTimingContext(): StageTimingContext {
  return context.getStore() ?? standalone();
}

/** A process incarnation is the only domain where monotonic subtraction is valid. */
export function stageTimingWriter() {
  return { writerId, writerPid: process.pid, clock: "process-monotonic" } as const;
}

/** Only the allowlisted lineage of the current context, for a closed child environment. */
export function stageTimingLineageEnv(): Record<string, string> {
  const value = stageTimingContext();
  const result: Record<string, string> = {};
  for (const [field, name] of Object.entries(STAGE_TIMING_LINEAGE_ENV) as [LineageField, string][]) {
    const item = value[field];
    if (item !== undefined) result[name] = String(item);
  }
  return result;
}

/** Pass explicit parent context to a child, without mutating global process.env.
 * Stale inherited lineage is replaced, so an absent parent or task is absent in the child. */
export function stageTimingEnv(): NodeJS.ProcessEnv {
  const inherited: NodeJS.ProcessEnv = { ...process.env };
  for (const name of LINEAGE_VARIABLES) delete inherited[name];
  return { ...inherited, ...stageTimingLineageEnv() };
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
  if ((STAGE_TIMING_ACTIVITIES as readonly unknown[]).includes(value.activity)) result.activity = value.activity!;
  return result;
}
