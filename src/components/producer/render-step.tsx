"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, FolderSearch, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { readEventStream, summarizeEvent, logStamp } from "@/lib/producer/sse";
import type { LogLine, LogKind } from "@/lib/producer/types";
import { approvedOutputEvent } from "@/lib/producer/editor-preview-authority";
import { streamProgressMessage } from "@/lib/producer/project-state";
import { dlog, derror } from "@/lib/debug";
import StreamLog from "./stream-log";
import {
  editorBrainLabel,
  launchAutoEditFromHyperframes,
  useEditorRuntime,
} from "./use-editor-runtime";

// The known render deliverables render.py writes into outDir (Phase 1 scope).
const OUTPUT_FILES = ["final.mp4", "cover.png", "edit_plan.json", "render_report.json", "timeline_map.json"];

export default function RenderStep({
  planText,
  outDir,
  onOpenEditor,
}: {
  planText: string;
  outDir: string;
  onOpenEditor?: () => void;
}) {
  const runtime = useEditorRuntime();
  const brain = editorBrainLabel(runtime);
  const [lines, setLines] = useState<LogLine[]>([]);
  const [phase, setPhase] = useState<"running" | "done" | "error">("running");
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const push = (kind: LogKind, text: string) =>
    setLines((prev) => [...prev, { t: logStamp(), kind, text }]);

  useEffect(() => {
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    (async () => {
      dlog("producer:render", "start reviewed manual plan", { outDir });
      try {
        const plan = JSON.parse(planText) as Record<string, unknown>;
        const saved = await fetch("/api/producer/save-plan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            path: `${outDir.replace(/\/$/, "")}/edit_plan.json`, plan, timebase: "full-plan",
          }),
          signal: ctrl.signal,
        });
        if (!saved.ok) {
          const detail = await saved.json().catch(() => ({})) as { error?: string };
          throw new Error(detail.error || `save-plan ${saved.status}`);
        }
        push("info", "✓ manual plan saved · previous preview is now stale");
        push("info", `${brain} is starting the reviewed MP4 pipeline…`);
        const res = await launchAutoEditFromHyperframes({
          dir: outDir,
          request: { dir: outDir, reviewSavedPlan: true },
          signal: ctrl.signal,
        });
        await readEventStream(
          res,
          (ev) => {
            if (ev.event === "error") {
              push("error", `✗ ${ev.message}`);
              setError(String(ev.message));
              setPhase("error");
              throw new Error(String(ev.message));
            }
            if (approvedOutputEvent(ev)) {
              push("info", "✓ review, render, and QC complete");
              setPhase((p) => (p === "error" ? p : "done"));
              return;
            }
            push(
              ev.event === "log" ? "stderr" : "event",
              streamProgressMessage(ev) ?? summarizeEvent(ev),
            );
          },
          ctrl.signal,
          "outputs",
        );
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        derror("producer:render", "stream failed", e);
        const msg = e instanceof Error ? e.message : "Render failed";
        setError(msg);
        setPhase("error");
        push("error", `✗ ${msg}`);
      }
    })();
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reveal = async (rel: string) => {
    try {
      const res = await fetch("/api/producer/reveal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: `${outDir}/${rel}` }),
      });
      const data = await res.json();
      if (data.error) push("error", `reveal: ${data.error}`);
    } catch (e) {
      push("error", `reveal: ${(e as Error).message}`);
    }
  };

  return (
    <div className="rise-in space-y-6">
      <div className="flex items-center gap-3">
        {phase === "running" && <Loader2 className="size-5 animate-spin text-signal" />}
        {phase === "done" && <CheckCircle2 className="size-5 text-emerald-400" />}
        {phase === "error" && <AlertTriangle className="size-5 text-destructive" />}
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            {phase === "running" ? "Reviewing and rendering…" : phase === "done" ? "Approved render complete" : "Render failed"}
          </h1>
          <p className="truncate font-mono text-[11px] text-muted-foreground/60">{outDir}</p>
          <p className="text-[10px] text-muted-foreground">{brain} · HyperFrames review · QC-approved MP4</p>
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {phase === "done" && onOpenEditor && (
        <Button onClick={onOpenEditor} className="w-full">
          Open in editor →
        </Button>
      )}

      {phase === "done" && (
        <div className="rounded-lg border border-border bg-card/50 p-4">
          <div className="label mb-3 text-muted-foreground/70">Outputs</div>
          <ul className="space-y-1.5">
            {OUTPUT_FILES.map((f) => (
              <li key={f} className="flex items-center justify-between gap-3">
                <code className="truncate text-xs text-foreground">{f}</code>
                <Button variant="ghost" size="xs" onClick={() => reveal(f)}>
                  <FolderSearch className="size-3" /> Reveal
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <StreamLog title="Render" lines={lines} />
    </div>
  );
}
