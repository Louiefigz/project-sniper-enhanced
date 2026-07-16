"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { readEventStream } from "@/lib/producer/sse";
import type { StreamEvent } from "@/lib/producer/types";

export interface LiveState {
  status: "running" | "interrupted" | "failed" | "qc_failed" | "complete";
  operationsCompleted: number;
  error?: string;
}

export interface OperationRow {
  id: string;
  summary: string;
  status: string;
}

async function fetchLiveState(dir: string): Promise<LiveState | null | undefined> {
  const response = await fetch(`/api/producer/live-build?dir=${encodeURIComponent(dir)}`,
    { cache: "no-store" });
  if (!response.ok) return undefined;
  const body = await response.json() as { state?: LiveState | null };
  return body.state ?? null;
}

function useLiveState(dir: string) {
  const [state, setState] = useState<LiveState | null>(null);
  const refresh = useCallback(async () => {
    const next = await fetchLiveState(dir);
    if (next !== undefined) setState(next);
  }, [dir]);
  useEffect(() => {
    let active = true;
    void fetchLiveState(dir).then((next) => {
      if (active && next !== undefined) setState(next);
    });
    return () => { active = false; };
  }, [dir]);
  return { state, refresh };
}

function useLiveEventHandler(
  setMessage: (value: string) => void,
  setOperations: React.Dispatch<React.SetStateAction<OperationRow[]>>,
) {
  return useCallback((event: StreamEvent) => {
    if (event.event === "error") throw new Error(String(event.message ?? "Live build failed"));
    if (event.event === "palmier_op" && typeof event.operationId === "string") {
      setOperations((rows) => [...rows, {
        id: event.operationId as string,
        summary: String(event.summary ?? event.tool ?? "Palmier operation"),
        status: "applying",
      }].slice(-12));
      setMessage(String(event.summary ?? "Applying editable Palmier operation…"));
    }
    if (event.event === "palmier_op_result" && typeof event.operationId === "string") {
      setOperations((rows) => rows.map((row) => row.id === event.operationId
        ? { ...row, status: String(event.status ?? "applied") } : row));
    }
    if (event.event === "candidate_qc_progress") {
      setMessage(String(event.message ?? "Reviewing exact candidate export…"));
    }
    if (event.event === "live_build_latency") {
      const seconds = Math.round(Number(event.firstMutationMs ?? 0) / 100) / 10;
      setMessage(`First editable change landed in ${seconds}s; exact candidate QC is continuing.`);
    }
    if (event.event === "live_build_qc_approved") setMessage(String(event.message));
  }, [setMessage, setOperations]);
}

interface StarterInput {
  dir: string;
  state: LiveState | null;
  refresh: () => Promise<void>;
  onChanged: () => void;
  onEvent: (event: StreamEvent) => void;
  setWorking: (value: boolean) => void;
  setMessage: (value: string) => void;
  setOperations: (value: OperationRow[]) => void;
  setExpanded: (value: boolean) => void;
  abortRef: React.MutableRefObject<AbortController | null>;
}

function useStarter(input: StarterInput) {
  return useCallback(async () => {
    const controller = new AbortController();
    input.abortRef.current = controller;
    input.setWorking(true);
    input.setOperations([]);
    input.setExpanded(true);
    input.setMessage(input.state ? "Resuming the retained Palmier candidate…"
      : "Verifying approved plan and Palmier authority…");
    try {
      const response = await fetch("/api/producer/live-build", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dir: input.dir,
          resume: Boolean(input.state && input.state.status !== "complete") }),
        signal: controller.signal,
      });
      await readEventStream(response, input.onEvent, controller.signal,
        "live_build_qc_approved");
    } catch (error) {
      input.setMessage(controller.signal.aborted
        ? "Stopped safely. The editable candidate and retained session can be resumed."
        : error instanceof Error ? error.message : "Palmier live build failed");
    } finally {
      await input.refresh();
      input.onChanged();
      input.abortRef.current = null;
      input.setWorking(false);
    }
  }, [input]);
}

export function useLiveBuildController(dir: string, onChanged: () => void) {
  const { state, refresh } = useLiveState(dir);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [operations, setOperations] = useState<OperationRow[]>([]);
  const [expanded, setExpanded] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const onEvent = useLiveEventHandler(setMessage, setOperations);
  const start = useStarter({ dir, state, refresh, onChanged, onEvent,
    setWorking, setMessage, setOperations, setExpanded, abortRef });
  return { state, working, message, operations, expanded, setExpanded, start,
    stop: () => abortRef.current?.abort() };
}
