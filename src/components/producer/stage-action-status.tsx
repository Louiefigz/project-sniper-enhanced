"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Loader2, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  runPhaseLabel,
  runPhaseRemainingLabel,
  type ProducerRunState,
} from "@/lib/producer/project-state";
import {
  plainRunFailureMessage,
  runTimingLabel,
} from "@/lib/producer/run-status-copy";
import { editorBrainLabel, useEditorRuntime } from "./use-editor-runtime";

export interface SseState {
  running: boolean;
  error: string | null;
  progress: string | null;
  logs: string[];
  operation?: "intent" | "ingest" | "auto_edit" | "resume_edit" | "render";
}

export function ActionShell({ state, children }: { state: SseState; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col items-end gap-1">
      <span className="flex items-center gap-1.5">
        {state.error && (
          <span className="max-w-[20rem] text-right text-[10px] text-destructive">
            {plainRunFailureMessage(state.error)}
          </span>
        )}
        {children}
      </span>
      {state.error && (
        <details className="max-w-[28rem] text-right text-[10px] text-muted-foreground">
          <summary className="cursor-pointer">Technical error details</summary>
          <p className="mt-1 break-words font-mono text-destructive">{state.error}</p>
        </details>
      )}
      {(state.running || (state.progress && !state.error)) && (
        <span className="max-w-[28rem] text-right text-[10px] text-signal">
          {state.progress}
        </span>
      )}
    </div>
  );
}

interface ActiveRunProps {
  run: ProducerRunState;
  dir: string;
  onStopped: () => void;
}

export function StopRunControl({ run, dir, onStopped }: ActiveRunProps) {
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stop = async () => {
    if (!run.controlToken) return;
    setStopping(true);
    setError(null);
    try {
      const response = await fetch("/api/producer/auto-edit/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dir, token: run.controlToken }),
      });
      const result = await response.json().catch(() => ({})) as { error?: string };
      if (!response.ok) throw new Error(result.error || `stop → ${response.status}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not stop Auto Edit");
    } finally {
      setStopping(false);
      onStopped();
    }
  };
  return (
    <div className="mt-1 flex max-w-[30rem] flex-col items-end gap-1">
      <div className="flex items-center gap-2">
        {error && <span className="max-w-64 text-[10px] text-destructive">{error}</span>}
        <Button type="button" variant="default" size="xs" disabled={stopping || !run.controlToken} onClick={stop}>
          {stopping ? <Loader2 className="size-3 animate-spin" /> : <Square className="size-3" />}
          {stopping ? "Stopping…" : "Stop & keep checkpoint"}
        </Button>
      </div>
      <p className="max-w-[24rem] text-right text-[10px] text-muted-foreground/70">
        To change source assets, stop first. Completed checkpoints are kept, and Resume edit continues from them.
      </p>
    </div>
  );
}

function useNow(initialAt: string): number {
  const [now, setNow] = useState(() => Date.parse(initialAt));
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

export function RunProgress({ run, align = "right" }: { run: ProducerRunState; align?: "left" | "right" }) {
  const now = useNow(run.startedAt);
  const runtime = useEditorRuntime();
  const brain = editorBrainLabel(runtime);
  const message = run.message.replace(/\bCodex\b/g, brain).replace(/\bClaude\b(?! Code)/g, brain);
  return (
    <div className={`max-w-[32rem] space-y-0.5 text-[10px] ${align === "right" ? "text-right" : "text-left"}`}>
      <p className="font-medium text-signal">{runPhaseLabel(run.phase)} · {runTimingLabel(run, now)}</p>
      <p className="text-muted-foreground">{message}</p>
      <p className="text-muted-foreground/80">{brain} · Palmier updates at each governed checkpoint</p>
      <p className="text-muted-foreground/70">{runPhaseRemainingLabel(run.phase)}</p>
    </div>
  );
}

export function ActiveRun({ run, dir, onStopped }: ActiveRunProps) {
  return (
    <div className="flex min-w-[14rem] flex-col items-end gap-1 text-right">
      <Button variant="ghost" size="xs" disabled>
        <Loader2 className="size-3 animate-spin" /> {runPhaseLabel(run.phase)}
      </Button>
      <RunProgress run={run} />
      {run.kind === "auto_edit" && <StopRunControl run={run} dir={dir} onStopped={onStopped} />}
    </div>
  );
}

export function LocalRun({ state }: { state: SseState }) {
  const labels = {
    intent: "Saving edit request",
    ingest: "Ingesting",
    auto_edit: "Generating edit",
    resume_edit: "Resuming edit",
    render: "Rendering",
  };
  const label = state.operation ? labels[state.operation] : "Producer job running";
  return (
    <div className="flex flex-col items-end gap-1">
      <ActionShell state={state}>
        <Button variant="ghost" size="xs" disabled><Loader2 className="size-3 animate-spin" /> {label}…</Button>
      </ActionShell>
      <span className="max-w-[28rem] text-right text-[10px] text-muted-foreground">
        Auto Edit may spend up to 30 minutes authoring; bounded planning reviews, rendering, and QC follow automatically.
      </span>
    </div>
  );
}

export function Spinner({ on }: { on: boolean }) {
  return on ? <Loader2 className="size-3 animate-spin" /> : null;
}
