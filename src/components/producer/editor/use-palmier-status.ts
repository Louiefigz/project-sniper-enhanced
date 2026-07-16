"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { EditPlan } from "@/lib/producer/edit-plan";
import { SerialRequestQueue } from "@/lib/producer/serial-request-queue";
import type { PalmierParity } from "./palmier-parity";

export interface Preflight {
  ok?: boolean;
  blocked?: string;
  warnings?: string[];
  renderExists?: boolean;
  exportVerified?: boolean;
  audioVerified?: boolean;
  authorityVerified?: boolean;
  publicationVerified?: boolean;
  planHash?: string;
  syncState?: "in_sync" | "behind" | "not_synced" | "palmier_owned";
  ownership?: "sniper" | "palmier";
  managedWorkspace?: boolean;
  targetProject?: string | null;
  targetProjectPath?: string | null;
  parity?: PalmierParity;
  error?: string;
}

interface PalmierProbe {
  up: boolean;
  project: string | null;
  projectPath: string | null;
}

interface StatusOptions {
  dir: string;
  plan: EditPlan;
}

const PALMIER_POLL_MS = 30_000;
const PREFLIGHT_DEBOUNCE_MS = 300;

async function requestProbe(_key: string, signal: AbortSignal): Promise<PalmierProbe> {
  const response = await fetch("/api/producer/palmier/status", { signal });
  if (!response.ok) throw new Error(`Palmier status ${response.status}`);
  return await response.json() as PalmierProbe;
}

function usePalmierProbe() {
  const [probe, setProbe] = useState<{
    up: boolean | null;
    project: string | null;
    projectPath: string | null;
  }>({ up: null, project: null, projectPath: null });
  const queueRef = useRef<SerialRequestQueue<PalmierProbe> | null>(null);
  const refreshProbe = useCallback(() => queueRef.current?.enqueue(["palmier"]), []);
  useEffect(() => {
    const queue = new SerialRequestQueue<PalmierProbe>({
      request: requestProbe,
      shouldRun: () => !document.hidden,
      onSuccess: (_key, result) => setProbe(result),
      onError: () => setProbe((current) => ({ ...current, up: false, projectPath: null })),
    });
    queueRef.current = queue;
    let timer = 0;
    const schedule = () => {
      window.clearTimeout(timer);
      if (document.hidden) return;
      timer = window.setTimeout(() => {
        queue.enqueue(["palmier"]);
        schedule();
      }, PALMIER_POLL_MS);
    };
    const onVisibility = () => {
      if (document.hidden) queue.pause();
      else queue.enqueue(["palmier"]);
      schedule();
    };
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      queue.dispose();
      if (queueRef.current === queue) queueRef.current = null;
    };
  }, []);
  return { ...probe, refreshProbe };
}

function usePalmierPreflight(options: StatusOptions) {
  const [pre, setPre] = useState<Preflight | null>(null);
  const [renderExists, setRenderExists] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const refreshPreflight = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      const response = await fetch("/api/producer/palmier/preflight", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dir: options.dir, plan: options.plan }),
        signal: controller.signal,
      });
      const verdict = await response.json() as Preflight;
      if (!controller.signal.aborted) {
        setPre(verdict);
        setRenderExists(Boolean(verdict.renderExists));
      }
    } catch {
      if (!controller.signal.aborted) {
        setPre({ ok: false, blocked: "preflight unreachable" });
        setRenderExists(false);
      }
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }, [options.dir, options.plan]);
  const abortPreflight = useCallback(() => controllerRef.current?.abort(), []);
  usePreflightRefresh(refreshPreflight, abortPreflight);
  const markRenderExists = useCallback(() => setRenderExists(true), []);
  return { pre, renderExists, refreshPreflight, markRenderExists };
}

function usePreflightRefresh(
  refresh: () => Promise<void>,
  abort: () => void,
): void {
  useEffect(() => {
    let timer = 0;
    const onVisibility = () => {
      window.clearTimeout(timer);
      if (document.hidden) abort();
      else timer = window.setTimeout(() => void refresh(), PREFLIGHT_DEBOUNCE_MS);
    };
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      abort();
    };
  }, [abort, refresh]);
}

export function usePalmierStatus(options: StatusOptions) {
  return { ...usePalmierProbe(), ...usePalmierPreflight(options) };
}
