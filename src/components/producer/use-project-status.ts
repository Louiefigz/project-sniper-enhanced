"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ProjectIntent } from "@/lib/producer/intent-presets";
import type { IntentCapabilityDecision } from "@/lib/producer/intent-capabilities";
import {
  ACTIVE_PROJECT_POLL_MS,
  IDLE_PROJECT_POLL_MS,
  activeProjectDirs,
  idleProjectDirs,
  projectStatusUrl,
} from "@/lib/producer/project-status-polling";
import { SerialRequestQueue } from "@/lib/producer/serial-request-queue";
import type { RunTimingReport } from "@/lib/producer/run-timing";
import {
  STAGE_ORDER,
  type ProducerRunState,
  type StageFlags,
  type StageName,
} from "@/lib/producer/project-state";
import type {
  FinalArtifactState,
  PalmierProjectState,
} from "@/lib/producer/project-card-state";

// Client hook over GET /api/producer/project-status?dir= — the disk-derived
// stage strip + provenance for one registry entry. Shapes mirror the route.

export interface SegmentFile {
  name: string;
  path: string;
}

export interface ProjectPlanRefitReceipt {
  source: "surgical-cut" | "saved-plan";
  createdAt: string;
  remapped: number;
  dropped: number;
  changes: Array<{
    track: string;
    index: number;
    action: "remapped" | "dropped";
    from?: unknown;
    to?: unknown;
    reason?: string;
  }>;
}

export interface ProjectStatus {
  dir: string;
  projectRoot: string | null;
  producerDir: string;
  origin: "segmenter" | "clipper" | "raw" | null;
  intent: ProjectIntent | null;
  requestedIntent: ProjectIntent | null;
  intentDecisions: IntentCapabilityDecision[];
  stages: StageFlags;
  segments: SegmentFile[];
  clipperFiles: SegmentFile[];
  sourceDir: string | null;
  manifestPath: string | null;
  finalArtifact: FinalArtifactState;
  palmier: PalmierProjectState;
  planRefit?: ProjectPlanRefitReceipt | null;
  run: ProducerRunState | null;
  timing?: RunTimingReport | null;
}

export { STAGE_ORDER };
export type { StageFlags, StageName };

/** The first stage not yet on disk (null = everything done). */
export function firstMissingStage(stages: StageFlags): StageName | null {
  return STAGE_ORDER.find((s) => !stages[s]) ?? null;
}

export interface ProjectStatusEntry {
  status: ProjectStatus | null;
  error: string | null;
}

async function fetchProjectStatus(
  dir: string,
  signal: AbortSignal,
  recoverProcesses: boolean,
): Promise<ProjectStatus> {
  const response = await fetch(projectStatusUrl(dir, recoverProcesses), { signal });
  const result = await response.json().catch(() => ({})) as { error?: string };
  if (!response.ok) throw new Error(result.error || `project-status ${response.status}`);
  return result as ProjectStatus;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "status failed";
}

export function useProjectStatuses(dirs: readonly string[]) {
  const [entries, setEntries] = useState<Record<string, ProjectStatusEntry>>({});
  const allowedRef = useRef(new Set<string>());
  const activeRef = useRef(new Set<string>());
  const queueRef = useRef<SerialRequestQueue<ProjectStatus> | null>(null);
  const enqueue = useCallback((targets: Iterable<string>) => queueRef.current?.enqueue(targets), []);
  useEffect(() => {
    const queue = new SerialRequestQueue<ProjectStatus>({
      request: (dir, signal) => fetchProjectStatus(dir, signal, activeRef.current.has(dir)),
      shouldRun: (dir) => !document.hidden && allowedRef.current.has(dir),
      onSuccess: (dir, status) => setEntries((current) => ({
        ...current, [dir]: { status, error: null },
      })),
      onError: (dir, error) => setEntries((current) => ({
        ...current,
        [dir]: { status: current[dir]?.status ?? null, error: errorMessage(error) },
      })),
    });
    queueRef.current = queue;
    return () => {
      queue.dispose();
      if (queueRef.current === queue) queueRef.current = null;
    };
  }, []);
  useEffect(() => {
    allowedRef.current = new Set(dirs);
    setEntries((current) => Object.fromEntries(
      Object.entries(current).filter(([dir]) => allowedRef.current.has(dir)),
    ));
    enqueue(dirs);
  }, [dirs, enqueue]);
  useEffect(() => {
    const onVisibility = () => {
      if (document.hidden) queueRef.current?.pause();
      else enqueue(allowedRef.current);
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [enqueue]);
  const runningDirs = useMemo(() => activeProjectDirs(dirs, entries), [dirs, entries]);
  const idleDirs = useMemo(() => idleProjectDirs(dirs, runningDirs), [dirs, runningDirs]);
  useEffect(() => {
    activeRef.current = new Set(runningDirs);
  }, [runningDirs]);
  usePollTimer(runningDirs, ACTIVE_PROJECT_POLL_MS, enqueue);
  useIdlePollTimer(idleDirs, IDLE_PROJECT_POLL_MS, enqueue);
  const refresh = useCallback((dir: string) => enqueue([dir]), [enqueue]);
  return { entries, refresh };
}

function usePollTimer(
  dirs: readonly string[],
  intervalMs: number,
  enqueue: (dirs: Iterable<string>) => void,
): void {
  useEffect(() => {
    if (!dirs.length) return;
    let timer = 0;
    const schedule = () => {
      timer = window.setTimeout(() => {
        if (!document.hidden) enqueue(dirs);
        schedule();
      }, intervalMs);
    };
    schedule();
    return () => window.clearTimeout(timer);
  }, [dirs, enqueue, intervalMs]);
}

/** Active responses rerender every 2.5s; key by contents so they do not reset this slow timer. */
function useIdlePollTimer(
  dirs: readonly string[],
  intervalMs: number,
  enqueue: (dirs: Iterable<string>) => void,
): void {
  const targetsKey = dirs.join("\u0000");
  useEffect(() => {
    if (!targetsKey) return;
    const targets = targetsKey.split("\u0000");
    const timer = window.setInterval(() => {
      if (!document.hidden) enqueue(targets);
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [targetsKey, enqueue, intervalMs]);
}

export function useProjectStatus(dir: string) {
  const dirs = useMemo(() => [dir], [dir]);
  const { entries, refresh: refreshOne } = useProjectStatuses(dirs);
  const refresh = useCallback(() => refreshOne(dir), [dir, refreshOne]);
  const entry = entries[dir];
  return { status: entry?.status ?? null, error: entry?.error ?? null, refresh };
}
