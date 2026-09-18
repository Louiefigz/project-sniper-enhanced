"use client";

import { RefObject, useEffect, useRef, useState } from "react";
import { Copy, Terminal } from "lucide-react";
import { ReviewLogKind, ReviewLogLine } from "./review-logs";

const LOG_KIND_CLASS: Record<ReviewLogKind, string> = {
  info: "text-signal",
  event: "text-foreground/80",
  flag: "text-emerald-400/90",
  stderr: "text-muted-foreground/70",
  error: "text-destructive",
};

function useDiagnostics(logs: ReviewLogLine[]) {
  const [show, setShow] = useState(false);
  const [copied, setCopied] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (show) endRef.current?.scrollIntoView({ block: "nearest" });
  }, [logs, show]);
  const copy = async () => {
    const text = logs.map((line) => `[${line.t}] ${line.text}`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — no-op */
    }
  };
  return { show, setShow, copied, copy, endRef };
}

export function ReviewDiagnostics({ logs }: { logs: ReviewLogLine[] }) {
  const controls = useDiagnostics(logs);
  return (
    <div className="rounded-lg border border-border bg-card/50">
      <button
        type="button"
        onClick={() => controls.setShow((show) => !show)}
        aria-expanded={controls.show}
        className="flex w-full items-center justify-between px-4 py-2.5 text-left"
      >
        <span className="flex items-center gap-2">
          <Terminal className="size-3.5 text-muted-foreground" />
          <span className="label text-foreground">Advanced diagnostics</span>
          <span className="label text-muted-foreground/60">({logs.length})</span>
        </span>
        <span className="label text-muted-foreground/60">{controls.show ? "Hide" : "Show"}</span>
      </button>
      {controls.show && (
        <DiagnosticsBody
          logs={logs}
          copied={controls.copied}
          onCopy={controls.copy}
          endRef={controls.endRef}
        />
      )}
    </div>
  );
}

function DiagnosticsBody({
  logs,
  copied,
  onCopy,
  endRef,
}: {
  logs: ReviewLogLine[];
  copied: boolean;
  onCopy: () => void;
  endRef: RefObject<HTMLDivElement | null>;
}) {
  return (
    <div className="border-t border-border">
      <div className="flex items-center justify-between px-4 py-1.5">
        <span className="label text-muted-foreground/50">
          events + python stderr · also in the dev terminal
        </span>
        <button
          onClick={onCopy}
          disabled={logs.length === 0}
          className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
        >
          <Copy className="size-3" />
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <LogEntries logs={logs} endRef={endRef} />
    </div>
  );
}

function LogEntries({
  logs,
  endRef,
}: {
  logs: ReviewLogLine[];
  endRef: RefObject<HTMLDivElement | null>;
}) {
  return (
    <div className="max-h-56 overflow-y-auto px-4 pb-3 font-mono text-[11px] leading-relaxed">
      {logs.length === 0 ? (
        <div className="py-3 text-muted-foreground/50">Waiting for events…</div>
      ) : (
        logs.map((line, index) => <LogEntry key={index} line={line} />)
      )}
      <div ref={endRef} />
    </div>
  );
}

function LogEntry({ line }: { line: ReviewLogLine }) {
  return (
    <div className="flex gap-2 whitespace-pre-wrap break-words">
      <span className="shrink-0 text-muted-foreground/40">{line.t}</span>
      <span className={LOG_KIND_CLASS[line.kind]}>{line.text}</span>
    </div>
  );
}
