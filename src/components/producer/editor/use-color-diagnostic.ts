"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ColorContext, ColorDescriptor, ColorJob } from "@/lib/producer/color-diagnostic";
import { unknownColorContext } from "@/lib/producer/color-diagnostic";
import { colorCutHash, colorDescriptor, colorStatus, startColorDiagnostic } from "@/lib/producer/color-diagnostic-client";
const message = (error: unknown) => error instanceof Error ? error.message : "Private color diagnostic failed";
export interface ColorFlowState {
  dir: string; descriptor: ColorDescriptor | null; contexts: ColorContext[]; job: ColorJob | null;
  error: string | null; loading: boolean; starting: boolean; activeId: string | null; storageBlocked: boolean;
}
type State = ColorFlowState;
export const initialColorFlow = (dir: string): State => ({ dir, descriptor: null, contexts: [], job: null, error: null,
  loading: true, starting: false, activeId: null, storageBlocked: false });
const initial = initialColorFlow;
type Update = (patch: Partial<State>) => void;
/** Synchronous guard closes the interval before React commits a busy state. */
export async function colorLaunchOnce(guard: { current: boolean }, task: () => Promise<void>): Promise<void> {
  if (guard.current) return;
  guard.current = true;
  try { await task(); } finally { guard.current = false; }
}
export function colorResponseCurrent(captured: { dir: string; generation: number }, current: { dir: string; generation: number }): boolean {
  return captured.dir === current.dir && captured.generation === current.generation;
}
function remembered(dir: string): string | null {
  try { return sessionStorage.getItem(`sniper-private-color:${dir}`); }
  catch { throw new Error("Session storage is unavailable. Enable it before starting a worker so interrupted job identity can be retained."); }
}
export async function loadColorSources(dir: string, update: Update): Promise<void> {
  try {
    const id = remembered(dir); update({ activeId: id });
    const descriptor = await colorDescriptor(dir);
    update({ descriptor, contexts: descriptor.sources.map(unknownColorContext), loading: false });
    if (id) update({ job: await colorStatus(dir, id), error: null });
  } catch (failure) {
    update({ error: message(failure), loading: false, storageBlocked: message(failure).startsWith("Session storage") });
  }
}
export async function launchColorJob(state: State, update: Update): Promise<void> {
  if (!state.descriptor) return;
  const jobId = crypto.randomUUID();
  try { sessionStorage.setItem(`sniper-private-color:${state.dir}`, jobId); }
  catch { update({ error: "Session storage is unavailable; no worker was started.", storageBlocked: true }); return; }
  update({ activeId: jobId, starting: true, error: null, job: null });
  try {
    const job = await startColorDiagnostic({ dir: state.dir, jobId, expectedPlanHash: state.descriptor.planHash,
      expectedManifestHash: state.descriptor.manifestHash, contexts: state.contexts });
    update({ job });
  } catch (failure) { update({ error: `${message(failure)} Outcome may be unknown. Recheck this retained job; do not start another.` }); }
  finally { update({ starting: false }); }
}

export function useColorDiagnostic(dir: string, cutTrack: unknown) {
  const [state, setState] = useState(() => initial(dir)), [cutHash, setCutHash] = useState<string | null>(null);
  const epoch = useRef(0), currentDir = useRef(dir);
  const launchGuard = useRef(false);
  const fenced = useCallback((generation: number): Update => patch => {
    if (colorResponseCurrent({ dir, generation }, { dir: currentDir.current, generation: epoch.current })) setState(previous => ({ ...previous, ...patch }));
  }, [dir]);
  const refresh = useCallback(async () => {
    const update = fenced(++epoch.current); setState(initial(dir)); await loadColorSources(dir, update);
  }, [dir, fenced]);
  const invalidate = useCallback(() => { epoch.current++; }, []);
  useEffect(() => {
    currentDir.current = dir; let cancelled = false;
    queueMicrotask(() => { if (!cancelled) void refresh(); });
    return () => { cancelled = true; invalidate(); };
  }, [dir, refresh, invalidate]);
  useEffect(() => {
    let cancelled = false;
    void colorCutHash(cutTrack).then(value => { if (!cancelled) setCutHash(value); });
    return () => { cancelled = true; };
  }, [cutTrack]);
  const live = state.dir === dir ? state : initial(dir);
  const captureUpdate = useCallback(() => fenced(epoch.current), [fenced]);
  useColorPolling(live, captureUpdate);
  const recheck = async () => {
    if (!live.activeId) return;
    const update = fenced(epoch.current);
    try { update({ job: await colorStatus(dir, live.activeId), error: null }); }
    catch (failure) { update({ error: `${message(failure)} Keep this job identity; cleanup is not verified.` }); }
  };
  const unresolved = !!live.activeId && (!live.job || !live.job.cleanupVerified);
  const busy = live.starting || live.job?.state === "running";
  const start = async () => {
    if (launchGuard.current || !live.descriptor || live.descriptor.cutHash !== cutHash || busy || unresolved || live.storageBlocked) return;
    await colorLaunchOnce(launchGuard, () => launchColorJob(live, fenced(epoch.current)));
  };
  const setContexts: Dispatch<SetStateAction<ColorContext[]>> = value => setState(previous => ({ ...previous,
    contexts: typeof value === "function" ? value(previous.contexts) : value }));
  return { ...live, setContexts, refresh, start, recheck, busy, unresolved,
    savedCutMatches: !!live.descriptor && live.descriptor.cutHash === cutHash };
}
function useColorPolling(state: State, captureUpdate: () => Update): void {
  useEffect(() => {
    if (!state.activeId || (!state.starting && state.job?.state !== "running")) return;
    const update = captureUpdate();
    let stopped = false; let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const job = await colorStatus(state.dir, state.activeId!);
        if (!stopped) update({ job, error: null });
        if (job.state !== "running") return;
      } catch (failure) {
        if (!stopped) update({ error: `${message(failure)} Status is unknown; use Recheck retained job.` });
        return;
      }
      if (!stopped) timer = setTimeout(() => void poll(), 2000);
    };
    timer = setTimeout(() => void poll(), 2000);
    return () => { stopped = true; clearTimeout(timer); };
  }, [state.dir, state.activeId, state.starting, state.job?.state, captureUpdate]);
}
