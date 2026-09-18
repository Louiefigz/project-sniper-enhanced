"use client";

import { Check } from "lucide-react";
import { projectPhaseCopy, requestedEditLabel } from "@/lib/producer/project-state";
import {
  STAGE_ORDER,
  useProjectStatus,
  type ProjectStatus,
  type StageName,
} from "./use-project-status";

// PIPELINE CHECKMARKS strip — the disk-derived stage dots for one project:
// origin badge (source stage), the stored-intent badge (e.g. "SHORT · Light"),
// then ingested → transcribed → plan → base → final as grey dot / green check.
// `compact` renders the icons-only header variant (tooltips carry the labels).

const LABELS: Record<StageName, string> = {
  ingested: "Ingested (manifest on disk)",
  transcribed: "Transcribed (every source has a transcript)",
  plan: "Plan (edit_plan.json)",
  base: "Base render (base_final.mp4 + fingerprint)",
  final: "Final (final.mp4)",
};

const SHORT: Record<StageName, string> = {
  ingested: "Ingested",
  transcribed: "Transcript",
  plan: "Plan",
  base: "Base",
  final: "Final",
};

function OriginBadge({ origin, compact }: { origin: ProjectStatus["origin"]; compact?: boolean }) {
  return (
    <span
      title={origin ? `origin: ${origin}` : "untagged legacy project (no project.json)"}
      className={`shrink-0 rounded-full border border-neutral-700 px-1.5 py-px font-mono uppercase text-neutral-400 ${
        compact ? "text-[9px]" : "text-[10px]"
      }`}
    >
      {!compact && "SOURCE · "}{origin ?? "—"}
    </span>
  );
}

function IntentBadge({ intent, compact }: { intent: ProjectStatus["intent"]; compact?: boolean }) {
  if (!intent) return null;
  const detail = [
    `intent: ${intent.preset ?? "custom"}`,
    `scope ${intent.scope}`,
    Object.keys(intent.lanes ?? {}).length ? `lanes ${JSON.stringify(intent.lanes)}` : "",
    intent.pace ? `pace ${intent.pace}` : "",
    intent.music ? "music on" : "",
    intent.audioEnhance ? `audio ${intent.audioEnhance.preset}` : "",
  ].filter(Boolean);
  return (
    <span
      title={detail.join(" · ")}
      className={`shrink-0 rounded-full border border-sky-500/30 bg-sky-500/5 px-1.5 py-px font-mono text-sky-400/90 ${
        compact ? "text-[9px]" : "text-[10px]"
      }`}
    >
      {!compact && "REQUESTED · "}{requestedEditLabel(intent)}
    </span>
  );
}

function WorkflowBadge({ status, compact }: { status: ProjectStatus; compact?: boolean }) {
  if (compact) return null;
  const copy = status.palmier.state === "approved_working_head"
    ? {
        label: "Palmier edit approved",
        detail: status.palmier.detail,
        tone: "complete" as const,
      }
    : projectPhaseCopy(status.stages, status.run);
  const cls = {
    neutral: "border-neutral-700 text-neutral-400",
    ready: "border-amber-500/30 bg-amber-500/5 text-amber-300",
    running: "border-signal/40 bg-signal/10 text-signal",
    complete: "border-emerald-500/30 bg-emerald-500/5 text-emerald-300",
    error: "border-destructive/40 bg-destructive/5 text-destructive",
  }[copy.tone];
  return (
    <span className={`shrink-0 rounded-full border px-1.5 py-px font-mono text-[10px] ${cls}`} title={copy.detail}>
      STATUS · {copy.label}
    </span>
  );
}

function StageDot({ stage, done, compact }: { stage: StageName; done: boolean; compact?: boolean }) {
  return (
    <span
      title={`${LABELS[stage]} — ${done ? "done" : "missing"}`}
      className="flex items-center gap-1"
    >
      {done ? (
        <Check className="size-3 text-emerald-400" strokeWidth={3} />
      ) : (
        <span className="inline-block size-1.5 rounded-full bg-neutral-600" />
      )}
      {!compact && (
        <span className={`text-[10px] ${done ? "text-neutral-400" : "text-neutral-600"}`}>
          {SHORT[stage]}
        </span>
      )}
    </span>
  );
}

export default function StageStrip({
  status,
  compact,
}: {
  status: ProjectStatus;
  compact?: boolean;
}) {
  const palmierPrimaryResult = status.palmier.state === "approved_working_head";
  return (
    <span className={`flex flex-wrap items-center ${compact ? "gap-1.5" : "gap-2.5"}`}>
      <OriginBadge origin={status.origin} compact={compact} />
      <IntentBadge intent={status.intent} compact={compact} />
      <WorkflowBadge status={status} compact={compact} />
      {!palmierPrimaryResult && STAGE_ORDER.map((stage) => (
        <StageDot key={stage} stage={stage} done={status.stages[stage]} compact={compact} />
      ))}
    </span>
  );
}

/** Self-contained icons-only strip for the editor header (fetches its own status). */
export function CompactStageStrip({ dir }: { dir: string }) {
  const { status } = useProjectStatus(dir);
  if (!status) return null;
  return <StageStrip status={status} compact />;
}
