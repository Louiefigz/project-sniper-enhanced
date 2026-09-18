"use client";

import { useMemo, useState } from "react";
import { Confidence, FlagRow } from "@/lib/frameio/types";
import { ReviewPhase } from "./review-run-state";

type FindingSort = "timestamp" | "confidence" | "error_type";

const CONFIDENCE_RANK: Record<Confidence, number> = { high: 0, medium: 1, low: 2 };

function frameUrl(thumb: string) {
  return `/api/frameio-review/frame?path=${encodeURIComponent(thumb)}`;
}

function formatClock(seconds: number) {
  const wholeSeconds = Math.floor(seconds);
  return `${Math.floor(wholeSeconds / 60)}:${String(wholeSeconds % 60).padStart(2, "0")}`;
}

function sortFindings(rows: FlagRow[], sortBy: FindingSort) {
  return [...rows].sort((left, right) => {
    if (sortBy === "confidence") {
      return CONFIDENCE_RANK[left.confidence] - CONFIDENCE_RANK[right.confidence];
    }
    if (sortBy === "error_type") return left.error_type.localeCompare(right.error_type);
    return left.timestamp - right.timestamp;
  });
}

interface ReviewFindingsProps {
  flags: FlagRow[];
  phase: ReviewPhase;
  onSeek: (timestamp: number) => void;
}

export function ReviewFindings({ flags, phase, onSeek }: ReviewFindingsProps) {
  const [hideLow, setHideLow] = useState(true);
  const [sortBy, setSortBy] = useState<FindingSort>("timestamp");
  const visible = useMemo(() => {
    const filtered = flags.filter((flag) => !(hideLow && flag.confidence === "low"));
    return sortFindings(filtered, sortBy);
  }, [flags, hideLow, sortBy]);
  return (
    <div className="space-y-3">
      <FindingsHeader
        count={visible.length}
        total={flags.length}
        hideLow={hideLow}
        sortBy={sortBy}
        onHideLow={setHideLow}
        onSort={setSortBy}
      />
      {visible.length ? (
        <FindingsList flags={visible} onSeek={onSeek} />
      ) : (
        <EmptyFindings phase={phase} hasHiddenFindings={flags.length > 0} />
      )}
    </div>
  );
}

function FindingsHeader({
  count,
  total,
  hideLow,
  sortBy,
  onHideLow,
  onSort,
}: {
  count: number;
  total: number;
  hideLow: boolean;
  sortBy: FindingSort;
  onHideLow: (hidden: boolean) => void;
  onSort: (sort: FindingSort) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="label text-foreground">
        Possible text issues <span className="text-muted-foreground/60">({count} of {total})</span>
      </h2>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={hideLow}
            onChange={(event) => onHideLow(event.target.checked)}
            className="accent-signal"
          />
          Hide low confidence
        </label>
        <select
          aria-label="Sort possible text issues"
          value={sortBy}
          onChange={(event) => onSort(event.target.value as FindingSort)}
          className="h-7 rounded-md border border-border bg-card/60 px-2 text-xs text-foreground"
        >
          <option value="timestamp">Timestamp</option>
          <option value="confidence">Confidence</option>
          <option value="error_type">Error type</option>
        </select>
      </div>
    </div>
  );
}

function FindingsList({ flags, onSeek }: { flags: FlagRow[]; onSeek: (timestamp: number) => void }) {
  return (
    <ul className="space-y-2">
      {flags.map((flag) => (
        <li key={flag.id}>
          <FindingRow flag={flag} onSeek={onSeek} />
        </li>
      ))}
    </ul>
  );
}

function FindingRow({ flag, onSeek }: { flag: FlagRow; onSeek: (timestamp: number) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSeek(flag.timestamp)}
      className="flex w-full gap-3 rounded-lg border border-border bg-card/50 p-3 text-left transition-colors hover:border-signal/50 hover:bg-card/80"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={frameUrl(flag.thumb)}
        alt=""
        className="h-16 w-28 shrink-0 rounded border border-border object-cover"
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs tabular-nums text-signal">
            {formatClock(flag.timestamp)}
            {flag.t_end > flag.t_start && `–${formatClock(flag.t_end)}`}
          </span>
          <ConfidenceBadge confidence={flag.confidence} />
          <span className="label text-muted-foreground/70">{flag.error_type}</span>
          {flag.merged_count && flag.merged_count > 1 && (
            <span className="label text-muted-foreground/50">×{flag.merged_count}</span>
          )}
        </div>
        <div className="mt-1 truncate text-sm">
          <span className="text-muted-foreground line-through decoration-destructive/60">
            {flag.exact_text_seen}
          </span>
        </div>
        <div className="truncate text-sm text-emerald-400/90">→ {flag.suggested_fix}</div>
        {flag.note && <div className="mt-0.5 truncate text-xs text-muted-foreground/70">{flag.note}</div>}
      </div>
    </button>
  );
}

function EmptyFindings({
  phase,
  hasHiddenFindings,
}: {
  phase: ReviewPhase;
  hasHiddenFindings: boolean;
}) {
  let message = "Preparing the review…";
  if (phase === "extracting" || phase === "deduping" || phase === "analyzing") {
    message = "Scanning… possible text issues will appear here as they are found.";
  } else if (phase === "needs_confirm") {
    message = "Review paused for your approval. Findings will appear after you continue.";
  } else if (phase === "error") {
    message = "No result is available because the review failed. Use Retry text review.";
  } else if (phase === "done" && hasHiddenFindings) {
    message = "No findings match the current filter. Turn off Hide low confidence to see all.";
  } else if (phase === "done") {
    message = "Review complete — no visible text issues were found.";
  }
  return (
    <div className="rounded-lg border border-dashed border-border bg-card/30 px-4 py-12 text-center text-sm text-muted-foreground">
      {message}
    </div>
  );
}

function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const className =
    confidence === "high"
      ? "bg-destructive/15 text-destructive"
      : confidence === "medium"
        ? "bg-amber-500/15 text-amber-400"
        : "bg-muted text-muted-foreground";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide ${className}`}>
      {confidence}
    </span>
  );
}
