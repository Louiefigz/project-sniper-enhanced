"use client";

import { useEffect, useState } from "react";

interface RuntimeStatus {
  mode: "live" | "local";
  brain: { provider: "legacy" | "codex"; model: string; reasoning: string | null };
  transcription: string;
  codex: { ready: boolean; version: string | null; detail: string | null } | null;
  whisper: {
    ready: boolean;
    version: string | null;
    model: string | null;
    detail: string | null;
  } | null;
}

function label(status: RuntimeStatus): string {
  if (status.brain.provider === "legacy") {
    return `CLAUDE CODE · ${status.brain.model.toUpperCase()}`;
  }
  if (status.mode === "live") return "LIVE PROVIDERS";
  const model = status.brain.model.replace("gpt-", "GPT ").toUpperCase();
  return status.brain.reasoning
    ? `${model} · ${status.brain.reasoning.toUpperCase()}`
    : model;
}

function runtimeDetails(status: RuntimeStatus): string {
  const asr = `ASR: ${status.transcription}`;
  const whisper = status.whisper
    ? `${status.whisper.version ?? (status.whisper.ready ? "whisper-cli available" : "whisper-cli unavailable")} · ${status.whisper.model ?? "model unavailable"}`
    : null;
  const cli = status.codex?.version ?? (status.codex ? "Codex CLI unavailable" : null);
  return [cli, asr, whisper, status.codex?.detail, status.whisper?.detail]
    .filter(Boolean)
    .join(" · ");
}

export default function RuntimeBadge() {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  useEffect(() => {
    fetch("/api/runtime", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : null)
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);
  if (!status) return null;
  const brainReady = status.brain.provider !== "codex" || status.codex?.ready;
  const asrReady = status.transcription !== "local-whisper" || status.whisper?.ready;
  const ready = status.mode === "live" || (brainReady && asrReady);
  return (
    <details className="relative">
      <summary
        className={`cursor-pointer list-none rounded-full border px-2 py-1 font-mono text-[9px] tracking-wide ${
          ready
            ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-300/90"
            : "border-rose-500/40 bg-rose-500/5 text-rose-300"
        }`}
      >
        {ready ? "READY" : "SETUP NEEDED"} · {status.mode === "local" ? "LOCAL" : "LIVE"}
      </summary>
      <div className="absolute right-0 top-8 z-50 w-80 rounded-lg border border-border bg-background p-3 text-xs leading-relaxed text-muted-foreground shadow-xl">
        <p className="font-medium text-foreground">{ready ? "Video tools are ready" : "A required local tool is unavailable"}</p>
        <p className="mt-1">Editor: {label(status)} · Transcription: {status.transcription}</p>
        <p className="mt-2 break-words font-mono text-[10px]">{runtimeDetails(status)}</p>
      </div>
    </details>
  );
}
