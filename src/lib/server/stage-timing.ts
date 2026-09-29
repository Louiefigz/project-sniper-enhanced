import { closeSync, openSync, writeSync } from "node:fs";
import { randomUUID } from "node:crypto";
import path from "node:path";
import {
  boundedTimingId, stageTimingContext, stageTimingWriter, timingMetadata, validClaimEpoch,
  withStageTimingChild, type StageTimingMetadata,
} from "./stage-timing-context";

/**
 * Append-only stage-timing journal (NDJSON) — the TS side of
 * scripts/producer/stage_timing.py. Both writers append the SAME row shape to
 * the SAME `<producer>/stage_timings.jsonl` so a run's wall clock is fully
 * attributable afterwards (the 2026-07 sweep found 57 of 102 real-run minutes
 * dark because no stage timings existed; PLAN_TIME_GEOMETRY_CONTRACT v3 #0).
 *
 * Legacy direct journal calls retain their row shape. timedStage adds v2
 * run/attempt/writer/span identity, parent linkage, optional task/claim/host-turn
 * lineage and terminal execution status. A completed invocation is not a passed
 * editorial/QC verdict. journalHandoffEvent records the task handoff vocabulary;
 * authoritative task and claim transitions never read this journal.
 * Never subtract monotonic timestamps across writers or sum concurrent stage
 * costs and present the result as elapsed request time.
 *
 * The journal is pure telemetry: append failures return false and are never
 * allowed to fail the pipeline (same doctrine as preview_proxy). The file is
 * opened O_APPEND (mode 0600 on create) and never truncated; each row is one
 * small single write(), so concurrent appenders (this controller plus the
 * Python render/assemble stages) cannot interleave partial lines on POSIX.
 */
export const STAGE_TIMINGS_FILE = "stage_timings.jsonl";

export type StageTimingEvent = "start" | "end";

/** Observed task handoff order (same vocabulary as stage_timing_context.HANDOFF_PHASES). */
export const HANDOFF_PHASES = [
  "dependencies-satisfied", "ready", "claim-requested", "host-accepted",
  "execution-started", "artifact-published", "consumer-accepted", "terminal-settlement",
] as const;
export type HandoffPhase = typeof HANDOFF_PHASES[number];
const CLAIM_PHASES = new Set<string>(HANDOFF_PHASES.slice(2));
const ARTIFACT_PHASES = new Set<string>(["artifact-published", "consumer-accepted"]);

/** One observed handoff; task/claim/host-turn lineage comes from the timing context. */
export interface HandoffEvent {
  stage: string;
  phase: HandoffPhase;
  artifactSha256?: string;
  /** consumer-accepted: which of several consumers accepted the artifact. */
  consumerId?: string;
}

export function stageTimingsPath(producerDir: string): string {
  return path.join(producerDir, STAGE_TIMINGS_FILE);
}

/** Append one timing row; best-effort — a broken journal must not fail a job. */
export function journalStageEvent(
  producerDir: string,
  stage: string,
  event: StageTimingEvent,
): boolean {
  return appendTimingRow(producerDir, {
    stage,
    event,
    ts: Date.now() / 1000,
    mono: Number(process.hrtime.bigint()) / 1e9,
  });
}

function appendTimingRow(producerDir: string, value: Record<string, unknown>): boolean {
  try {
    const row = JSON.stringify(value);
    const descriptor = openSync(stageTimingsPath(producerDir), "a", 0o600);
    try {
      writeSync(descriptor, `${row}\n`);
    } finally {
      closeSync(descriptor);
    }
    return true;
  } catch {
    return false;
  }
}

/**
 * START/END rows around one awaited stage. END is written even when the stage
 * rejects — the failing stage still ended; the rejection stays the loud signal.
 */
export async function timedStage<T>(
  producerDir: string,
  stage: string,
  run: () => Promise<T>,
  metadata: StageTimingMetadata = {},
): Promise<T> {
  const began = process.hrtime.bigint();
  const parent = stageTimingContext();
  const spanId = randomUUID();
  const fields = {
    schemaVersion: 2, ...parent, ...stageTimingWriter(), spanId, stage,
    metadata: timingMetadata(metadata),
  };
  appendTimingRow(producerDir, {
    ...fields, event: "start", ts: Date.now() / 1000, mono: Number(began) / 1e9,
  });
  let status = "completed";
  try {
    return await withStageTimingChild(spanId, run);
  } catch (error) {
    status = error instanceof Error && error.name === "AbortError" ? "interrupted" : "failed";
    throw error;
  } finally {
    const ended = process.hrtime.bigint();
    appendTimingRow(producerDir, {
      ...fields, event: "end", ts: Date.now() / 1000, mono: Number(ended) / 1e9,
      status, elapsedMs: Number(ended - began) / 1e6,
    });
  }
}

/** Name the first missing handoff field; mirrors stage_timing_context.handoff_problem. */
export function handoffProblem(row: Record<string, unknown>): string | null {
  const phase = String(row.handoffPhase);
  if (!(HANDOFF_PHASES as readonly string[]).includes(phase)) return "unknown-handoff-phase";
  if (!boundedTimingId(row.taskId)) return "handoff-missing-task";
  if (CLAIM_PHASES.has(phase) && !validClaimEpoch(row.claimEpoch)) return "handoff-missing-claim-epoch";
  if (ARTIFACT_PHASES.has(phase) && !(typeof row.artifactSha256 === "string" && /^[0-9a-f]{64}$/.test(row.artifactSha256))) {
    return "handoff-missing-artifact";
  }
  if ("hostTurnId" in row && !boundedTimingId(row.hostTurnId)) return "handoff-invalid-host-turn";
  if ("consumerId" in row && (phase !== "consumer-accepted" || !boundedTimingId(row.consumerId))) {
    return "handoff-invalid-consumer";
  }
  return null;
}

/** The one refusal that is not about the event's content. */
export const JOURNAL_UNWRITABLE = "journal-unwritable";

/** A recorded handoff row, or the reason nothing was written. */
export type HandoffRecord =
  | { recorded: true; row: Record<string, unknown> }
  | { recorded: false; reason: string };

/**
 * Append one handoff event under the current lineage (withStageTimingContext supplies the
 * task). Timing never fails the work it records, so this never throws for event content:
 * an unknown phase or label, or a missing task, claim epoch or artifact hash, returns
 * { recorded: false, reason } and writes nothing; a refused append returns journal-unwritable.
 */
export function journalHandoffEvent(producerDir: string, event: HandoffEvent): HandoffRecord {
  const optional = { artifactSha256: event.artifactSha256, consumerId: event.consumerId };
  const row: Record<string, unknown> = {
    schemaVersion: 2, ...stageTimingContext(), ...stageTimingWriter(), event: "handoff",
    stage: event.stage, handoffPhase: event.phase, eventId: randomUUID(),
    ts: Date.now() / 1000, mono: Number(process.hrtime.bigint()) / 1e9,
    ...Object.fromEntries(Object.entries(optional).filter(([, value]) => value !== undefined)),
  };
  const label = typeof event.stage === "string" && event.stage.length >= 1 && event.stage.length <= 128;
  const problem = (label ? null : "invalid-stage-label") ?? handoffProblem(row);
  if (problem) return { recorded: false, reason: problem };
  return appendTimingRow(producerDir, row) ? { recorded: true, row } : { recorded: false, reason: JOURNAL_UNWRITABLE };
}
