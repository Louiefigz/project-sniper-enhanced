import { FlagRow, KeptFrameInfo, ReviewEvent } from "@/lib/frameio/types";

export type ReviewPhase =
  | "extracting"
  | "deduping"
  | "analyzing"
  | "needs_confirm"
  | "done"
  | "error";

export interface ReviewProgress {
  done: number;
  total: number;
}

export interface ReviewRunState {
  phase: ReviewPhase;
  statusLine: string;
  extractProgress: ReviewProgress;
  analyzeProgress: ReviewProgress;
  estimate: number | null;
  keptFrames: KeptFrameInfo[];
  flags: FlagRow[];
  saved: { results: string; report: string } | null;
  failures: number;
  error: string | null;
}

export type ReviewRunAction =
  | { type: "reset"; confirmed: boolean }
  | { type: "event"; event: ReviewEvent }
  | { type: "stream_error"; message: string };

const EMPTY_PROGRESS: ReviewProgress = { done: 0, total: 0 };

export function createInitialReviewState(): ReviewRunState {
  return {
    phase: "extracting",
    statusLine: "Extracting frames…",
    extractProgress: EMPTY_PROGRESS,
    analyzeProgress: EMPTY_PROGRESS,
    estimate: null,
    keptFrames: [],
    flags: [],
    saved: null,
    failures: 0,
    error: null,
  };
}

function resetReviewState(confirmed: boolean): ReviewRunState {
  return {
    ...createInitialReviewState(),
    statusLine: confirmed ? "Continuing approved review…" : "Starting text review…",
  };
}

function applyPreparationEvent(state: ReviewRunState, event: ReviewEvent): ReviewRunState | null {
  switch (event.event) {
    case "extract_start":
      return { ...state, phase: "extracting", statusLine: "Extracting frames…" };
    case "extract_progress":
      return { ...state, extractProgress: { done: event.done, total: event.total } };
    case "extracted":
      return {
        ...state,
        phase: "deduping",
        statusLine: `Extracted ${event.frames} frame(s). Deduplicating…`,
      };
    case "dedup":
      return {
        ...state,
        statusLine: `${event.extracted} frames → ${event.kept} unique after dedup.`,
      };
    case "frames":
      return { ...state, keptFrames: event.items };
    case "estimate":
      return {
        ...state,
        estimate: event.api_calls,
        analyzeProgress: { done: 0, total: event.api_calls },
      };
    case "needs_confirm":
      return {
        ...state,
        phase: "needs_confirm",
        statusLine: `${event.api_calls} API calls needed — over the ${event.threshold} limit.`,
      };
    default:
      return null;
  }
}

function appendFlags(state: ReviewRunState, event: Extract<ReviewEvent, { event: "flag" }>) {
  const nextFlags = event.errors.map((error, index) => ({
    ...error,
    id: `${event.t_start}-${index}-${state.flags.length}`,
    timestamp: event.timestamp,
    t_start: event.t_start,
    t_end: event.t_end,
    thumb: event.thumb,
  }));
  return { ...state, flags: [...state.flags, ...nextFlags] };
}

function applyAnalysisEvent(state: ReviewRunState, event: ReviewEvent): ReviewRunState | null {
  switch (event.event) {
    case "analyze_progress":
      return {
        ...state,
        phase: "analyzing",
        analyzeProgress: { done: event.done, total: event.total },
        statusLine: `Analyzing frames… ${event.done}/${event.total}`,
      };
    case "flag":
      return appendFlags(state, event);
    default:
      return null;
  }
}

function applyTerminalEvent(state: ReviewRunState, event: ReviewEvent): ReviewRunState | null {
  if (event.event === "error") {
    return { ...state, phase: "error", error: event.message, statusLine: "Text review failed" };
  }
  if (event.event !== "done") return null;
  const failureText = event.frame_failures ? `, ${event.frame_failures} frame(s) failed` : "";
  return {
    ...state,
    phase: "done",
    failures: event.frame_failures,
    saved: { results: event.results_path, report: event.report_path },
    // The terminal event carries server-side verdict-deduped findings. It is
    // authoritative over the raw flags streamed while individual frames ran.
    flags: event.flags.map((flag, index) => ({
      ...flag,
      id: `done-${index}-${flag.timestamp}`,
    })),
    statusLine:
      `Done — ${event.flag_count} finding(s) across ${event.frames_analyzed} frame(s)` + failureText,
  };
}

function applyReviewEvent(state: ReviewRunState, event: ReviewEvent): ReviewRunState {
  return (
    applyPreparationEvent(state, event) ??
    applyAnalysisEvent(state, event) ??
    applyTerminalEvent(state, event) ??
    state
  );
}

export function reviewRunReducer(state: ReviewRunState, action: ReviewRunAction): ReviewRunState {
  if (action.type === "reset") return resetReviewState(action.confirmed);
  if (action.type === "stream_error") {
    return { ...state, phase: "error", error: action.message, statusLine: "Text review failed" };
  }
  return applyReviewEvent(state, action.event);
}
