import { closeSync, openSync, writeSync } from "node:fs";
import { randomUUID } from "node:crypto";
import path from "node:path";
import {
  stageTimingContext, stageTimingWriter, timingMetadata, withStageTimingContext,
  type StageTimingMetadata,
} from "./stage-timing-context";

/**
 * Append-only stage-timing journal (NDJSON) — the TS side of
 * scripts/producer/stage_timing.py. Both writers append the SAME row shape to
 * the SAME `<producer>/stage_timings.jsonl` so a run's wall clock is fully
 * attributable afterwards (the 2026-07 sweep found 57 of 102 real-run minutes
 * dark because no stage timings existed; PLAN_TIME_GEOMETRY_CONTRACT v3 #0).
 *
 * Legacy direct journal calls retain their row shape. timedStage adds v2
 * run/attempt/writer/span identity, parent linkage and terminal execution
 * status. A completed invocation is not a passed editorial/QC verdict.
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
    return await withStageTimingContext({ ...parent, parentSpanId: spanId }, run);
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
