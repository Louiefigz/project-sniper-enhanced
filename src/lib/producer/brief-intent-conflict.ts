import type { Mode } from "./intent-presets";

const SHORT_SIGNAL = /\b(vertical|9\s*:\s*16|short[- ]?form|instagram reel|tiktok)\b/i;
const LONG_SIGNAL = /\b(horizontal|16\s*:\s*9|long[- ]?form|long video)\b/i;

/** Return only high-confidence format contradictions; ambiguous prose is silent. */
export function briefModeConflict(brief: string, mode: Mode): string | null {
  const short = SHORT_SIGNAL.test(brief);
  const long = LONG_SIGNAL.test(brief);
  if (!short && !long || short && long) return null;
  if (short && mode === "longform") {
    return "Your description asks for a vertical short, but the format card says Horizontal video (16:9).";
  }
  if (long && mode === "short") {
    return "Your description asks for a horizontal long video, but the format card says Vertical short (9:16).";
  }
  return null;
}

export interface IntentSelection {
  format: boolean;
  style: boolean;
}

/** No draft choice becomes authority until both operator decisions are explicit. */
export function intentSelectionReady(
  selection: IntentSelection,
  brief: string,
  mode: Mode,
): boolean {
  return selection.format && selection.style && briefModeConflict(brief, mode) == null;
}
