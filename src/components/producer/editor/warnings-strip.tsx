"use client";

import { useState } from "react";
import type { WarningItem } from "@/lib/producer/warnings";

interface Props {
  warnings: WarningItem[];
  onDismiss: () => void;
}

// Persistent amber warnings strip under the editor header. Collects the
// warning-class statuses from re-render / speech-cleanup streams and SURVIVES
// stream completion (unlike the header's reMsg, which is wiped on success).
// Dismiss clears the collected list; the count reads "N warnings".
export default function WarningsStrip({ warnings, onDismiss }: Props) {
  const [expanded, setExpanded] = useState(false);
  if (warnings.length === 0) return null;

  return (
    <div className="shrink-0 border-b border-amber-500/30 bg-amber-500/10 px-4 py-1.5 text-[11px] text-amber-200">
      <div className="flex items-center gap-2">
        <span className="font-medium">
          {warnings.length} warning{warnings.length === 1 ? "" : "s"}
        </span>
        <span className="min-w-0 truncate text-amber-200/80">
          {expanded ? "" : warnings.map((w) => w.status).join(" · ")}
        </span>
        <button
          onClick={() => setExpanded((e) => !e)}
          className="ml-auto shrink-0 text-amber-300/80 hover:text-amber-100"
        >
          {expanded ? "collapse" : "details"}
        </button>
        <button
          onClick={onDismiss}
          aria-label="Dismiss warnings"
          className="shrink-0 rounded px-1 text-amber-300/80 hover:bg-amber-500/20 hover:text-amber-100"
        >
          ✕
        </button>
      </div>
      {expanded && (
        <ul className="mt-1 space-y-0.5 pl-1">
          {warnings.map((w, i) => (
            <li key={i} className="truncate" title={w.text}>
              <span className="mr-1.5 rounded bg-amber-500/20 px-1 py-px text-[10px]">{w.status}</span>
              {w.text}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
