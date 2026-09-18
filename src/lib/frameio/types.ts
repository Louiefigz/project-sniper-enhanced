// FRAME.IO REVIEW shapes. Kept self-contained in its own namespace (like CLIPPER)
// so the QC tool stays independent of SEGMENTER/CLIPPER transcript types.

export type Confidence = "high" | "medium" | "low";

export type FrameioStep = "select" | "configure" | "running" | "review";

/** One on-screen text error, as reported by Claude for a single frame. */
export interface FrameError {
  exact_text_seen: string;
  error_type: string;
  suggested_fix: string;
  confidence: Confidence;
  note: string;
}

/** A flattened, sortable flag row (one per finding) shown in the review list. */
export interface FlagRow extends FrameError {
  id: string;
  timestamp: number; // seconds — where the player seeks
  t_start: number;
  t_end: number;
  thumb: string; // absolute path on disk; served via /api/frameio-review/frame
  merged_count?: number; // consecutive same-text verdicts folded into this one (verdict-dedup)
}

/** A kept (post-dedup) frame the UI can show a thumbnail for. */
export interface KeptFrameInfo {
  index: number;
  t_start: number;
  t_end: number;
  thumb: string;
  duplicates: number;
}

export type SelectMode = "visual" | "ocr";

export interface ReviewConfig {
  fps: number;
  mode: SelectMode;
  fuzz: number; // ocr-mode token_set_ratio grouping threshold
  maxReps: number | null; // cap representatives sent to Claude (cheap test runs); null = no cap
  maxFrames: number | null;
  hamming: number;
  model: string;
  confirmThreshold: number;
}

export const MODEL_OPTIONS = [
  { id: "claude-sonnet-4-6", label: "Sonnet 4.6", hint: "best quality" },
  { id: "claude-haiku-4-5", label: "Haiku 4.5", hint: "cheaper / faster" },
] as const;

export const MODE_OPTIONS = [
  { id: "visual", label: "Visual", hint: "pHash settled-frame — any footage" },
  { id: "ocr", label: "OCR text", hint: "tesseract — clean slideware only" },
] as const;

export const DEFAULT_CONFIG: ReviewConfig = {
  fps: 1,
  mode: "visual",
  fuzz: 90,
  maxReps: null,
  maxFrames: null,
  hamming: 5,
  model: "claude-sonnet-4-6",
  confirmThreshold: 200,
};

// --- Server (review.py --server) NDJSON events, forwarded over SSE ----------

export type ReviewEvent =
  | { event: "extract_start"; input: string; fps: number; max_frames: number | null }
  | { event: "extract_progress"; done: number; total: number }
  | { event: "extracted"; frames: number }
  | { event: "dedup"; mode?: SelectMode; extracted: number; kept: number; threshold: number; fuzz?: number }
  | { event: "frames"; items: KeptFrameInfo[] }
  | {
      event: "estimate";
      api_calls: number;
      representatives?: number;
      eligible?: number;
      blanks_skipped?: number;
      capped?: number;
      est_cost_usd?: number;
    }
  | { event: "needs_confirm"; api_calls: number; threshold: number }
  | { event: "select_report"; mode: SelectMode; fuzz: number; total_frames: number; runs: number; items: unknown[] }
  | { event: "flag"; timestamp: number; t_start: number; t_end: number; thumb: string; errors: FrameError[] }
  | { event: "analyze_progress"; done: number; total: number; flags: number }
  | { event: "log"; stream: "stderr"; text: string }
  | {
      event: "done";
      frames_analyzed: number;
      flag_count: number;
      frame_failures: number;
      results_path: string;
      report_path: string;
      frames_dir: string;
      flags: Omit<FlagRow, "id">[];
    }
  | { event: "error"; message: string };
