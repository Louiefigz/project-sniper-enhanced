// Warning-class NDJSON statuses the Python stages emit on streams that OTHERWISE
// succeed (the deliverable landed, but something honest was skipped/unproven).
// reMsg is wiped on completion, so these are collected into a persistent,
// dismissible strip instead. Pure reducer — tsx-tested.

import { summarizeEvent } from "./sse";
import type { StreamEvent } from "./types";

export const WARNING_STATUSES = new Set([
  "warning", // Palmier translator fidelity warning (grade/captions/audio/music)
  "base_unverifiable",
  "refit_skipped",
  "plan_refit_dropped", // deterministic cut refit removed timed elements; receipt lists each one
  "music_not_applied",
  "audio_fast_path_skipped",
  "proxy_failed",
  "lint_warning",
  "placement_unsafe", // editor-emitted: graphic dropped outside the shorts SAFE_BOX
  "midrender_edits_discarded", // editor-emitted: a refit rewrite superseded unsaved mid-render edits
]);

export interface WarningItem {
  status: string;
  text: string;
}

/**
 * Fold one stream event into the warning list. Returns `prev` UNCHANGED (same
 * reference — cheap to call per event) unless the event is a warning-class
 * status not already collected; then returns a new appended list. Duplicate
 * (status, text) pairs collapse (a retried stream must not double-count).
 */
export function collectWarnings(prev: WarningItem[], ev: StreamEvent): WarningItem[] {
  const status = typeof ev.status === "string" ? ev.status : null;
  if (!status || !WARNING_STATUSES.has(status)) return prev;
  const text = summarizeEvent(ev);
  if (prev.some((w) => w.status === status && w.text === text)) return prev;
  return [...prev, { status, text }];
}
