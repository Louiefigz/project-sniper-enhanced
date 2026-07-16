import { ReviewEvent } from "@/lib/frameio/types";

export type ReviewLogKind = "info" | "event" | "flag" | "stderr" | "error";

export interface ReviewLogLine {
  t: string;
  kind: ReviewLogKind;
  text: string;
}

type PendingLog = Omit<ReviewLogLine, "t">;

export function clockStamp(): string {
  try {
    return new Date().toISOString().slice(11, 23);
  } catch {
    return "--:--:--";
  }
}

function dedupLog(event: Extract<ReviewEvent, { event: "dedup" }>): PendingLog {
  const criterion =
    event.mode === "ocr" ? `fuzz ≥ ${event.fuzz}` : `hamming ≤ ${event.threshold}`;
  return {
    kind: "event",
    text: `select [${event.mode ?? "visual"}]: ${event.extracted} → ${event.kept} representative(s) (${criterion})`,
  };
}

function flagLogs(event: Extract<ReviewEvent, { event: "flag" }>): PendingLog[] {
  return event.errors.map((error) => ({
    kind: "flag",
    text:
      `flag @ ${event.t_start}s [${error.confidence}] ${error.error_type}: ` +
      `"${error.exact_text_seen}" → "${error.suggested_fix}"`,
  }));
}

function doneLog(event: Extract<ReviewEvent, { event: "done" }>): PendingLog {
  const failureText = event.frame_failures ? `, ${event.frame_failures} failed` : "";
  return {
    kind: "info",
    text: `✓ done — ${event.flag_count} flag(s) / ${event.frames_analyzed} frame(s)${failureText}`,
  };
}

export function logsForReviewEvent(event: ReviewEvent): PendingLog[] {
  switch (event.event) {
    case "log":
      return [{ kind: "stderr", text: event.text }];
    case "extract_start":
      return [{ kind: "info", text: `▶ run started — fps=${event.fps}, max_frames=${event.max_frames ?? "none"}` }];
    case "extracted":
      return [{ kind: "event", text: `extracted ${event.frames} frame(s)` }];
    case "dedup":
      return [dedupLog(event)];
    case "estimate":
      return [{ kind: "event", text: `estimate: ${event.api_calls} API call(s) after dedup` }];
    case "needs_confirm":
      return [{ kind: "info", text: `⚠ needs confirm: ${event.api_calls} calls > ${event.threshold} limit` }];
    case "flag":
      return flagLogs(event);
    case "done":
      return [doneLog(event)];
    case "error":
      return [{ kind: "error", text: `✗ ${event.message}` }];
    default:
      return [];
  }
}
