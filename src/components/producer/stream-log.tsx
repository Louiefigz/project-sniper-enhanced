"use client";

import { useEffect, useRef } from "react";
import { Terminal } from "lucide-react";
import type { LogLine, LogKind } from "@/lib/producer/types";

const KIND_CLASS: Record<LogKind, string> = {
  info: "text-signal",
  event: "text-foreground/80",
  stderr: "text-muted-foreground/70",
  error: "text-destructive",
};

// Live NDJSON trace for an ingest / render run — same look as FRAME.IO REVIEW's
// Diagnostics panel. Auto-pins to the newest line while running.
export default function StreamLog({ title, lines }: { title: string; lines: LogLine[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [lines]);

  return (
    <div className="rounded-lg border border-border bg-card/50">
      <div className="flex items-center gap-2 px-4 py-2.5">
        <Terminal className="size-3.5 text-muted-foreground" />
        <span className="label text-foreground">{title}</span>
        <span className="label text-muted-foreground/60">({lines.length})</span>
      </div>
      <div className="border-t border-border">
        <div className="max-h-64 overflow-y-auto px-4 py-3 font-mono text-[11px] leading-relaxed">
          {lines.length === 0 ? (
            <div className="text-muted-foreground/50">Waiting for events…</div>
          ) : (
            lines.map((l, i) => (
              <div key={i} className="flex gap-2 whitespace-pre-wrap break-words">
                <span className="shrink-0 text-muted-foreground/40">{l.t}</span>
                <span className={KIND_CLASS[l.kind]}>{l.text}</span>
              </div>
            ))
          )}
          <div ref={endRef} />
        </div>
      </div>
    </div>
  );
}
