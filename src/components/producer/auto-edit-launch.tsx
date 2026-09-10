"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { readEventStream } from "@/lib/producer/sse";
import { intentBadge, type ProjectIntent } from "@/lib/producer/intent-presets";
import { buildAutoEditRequest } from "@/lib/producer/intent-flow";
import { streamProgressMessage } from "@/lib/producer/project-state";
import {
  editorBrainLabel,
  launchAutoEditFromHyperframes,
  useEditorRuntime,
} from "./use-editor-runtime";

export default function AutoEditLaunch({
  dir,
  intent,
  onDone,
}: {
  dir: string;
  intent?: ProjectIntent;
  onDone: () => void;
}) {
  const [running, setRunning] = useState(false);
  const runtime = useEditorRuntime();
  const brain = editorBrainLabel(runtime);
  const [status, setStatus] = useState(intent
    ? "Creates the edit, renders the MP4, and checks the finished file."
    : "Choose Short or Long and an edit level before creating this video.");
  const activeRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activeRef.current?.abort();
    };
  }, []);
  const run = async () => {
    if (!intent) return;
    activeRef.current?.abort();
    const controller = new AbortController();
    activeRef.current = controller;
    setRunning(true);
    setStatus("Starting the reviewed MP4 pipeline…");
    try {
      const request = buildAutoEditRequest(dir, intent);
      const response = await launchAutoEditFromHyperframes({
        dir,
        mode: intent.mode,
        request,
        signal: controller.signal,
      });
      setStatus(`${brain} is authoring the transcript-first cut…`);
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || `auto-edit ${response.status}`);
      }
      await readEventStream(response, (event) => {
        if (event.event === "error") throw new Error(String(event.message));
        const progress = streamProgressMessage(event as Record<string, unknown>);
        if (progress && mountedRef.current && activeRef.current === controller) setStatus(progress);
      }, controller.signal, request.workflowPolicy === "cut-first" ? ["outputs", "awaiting_cut_approval"] : "outputs");
      if (!controller.signal.aborted && mountedRef.current && activeRef.current === controller) onDone();
    } catch (error) {
      if ((error as Error).name !== "AbortError" && mountedRef.current) {
        setStatus(error instanceof Error ? error.message : "Auto-edit failed");
      }
    } finally {
      if (mountedRef.current && activeRef.current === controller) setRunning(false);
    }
  };
  return (
    <div className="rounded-lg border border-signal/25 bg-signal/5 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium"><Sparkles className="size-4 text-signal" /> Create your video</div>
          <p className="mt-1 text-xs text-muted-foreground">{status}</p>
          {intent && <p className="mt-1 font-mono text-[10px] text-signal">Target: {intentBadge(intent)}</p>}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <Button onClick={run} disabled={running || !intent}>
            {running ? <Loader2 className="size-4 animate-spin" /> : null}
            {running ? "Working…" : "Generate video →"}
          </Button>
          <p className="text-right text-[10px] text-muted-foreground">
            {brain} · HyperFrames review · QC-approved MP4
          </p>
        </div>
      </div>
    </div>
  );
}
