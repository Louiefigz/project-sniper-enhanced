/** Cheap screening of existing source-float-v2 finishing, never media or approval evidence. */
import { AUDIO_ENHANCE_PRESETS } from "@/lib/producer/intent-presets";
import { exactKeys, objectValue } from "@/lib/producer/contracts/validation";

// Mirrors audio.audio_gain; the cross-runtime tests exercise both endpoints.
const MIN_GAIN_DB = -12, MAX_GAIN_DB = 12;

function assertEnhancement(value: unknown): void {
  if (value == null) return;
  const row = objectValue(value, "requested lanes: audioEnhance");
  exactKeys(row, ["preset", "rationale"], ["preset"], "requested lanes: audioEnhance");
  if (typeof row.preset !== "string" || row.preset === "separate"
      || !(AUDIO_ENHANCE_PRESETS as readonly string[]).includes(row.preset)) {
    throw new Error("Private opening requested lanes: audioEnhance needs an installed filter preset");
  }
}

interface GainWindow { start: number; end: number; db: number }

function gainWindow(value: unknown): GainWindow {
  const row = objectValue(value, "requested lanes: audioGain window");
  const values = [row.outStart, row.outEnd, row.dB];
  // Plans contain actual JSON numbers. Do not coerce booleans, strings or null into gain.
  if (values.some((item) => typeof item !== "number" || !Number.isFinite(item))) {
    throw new Error("Private opening requested lanes: audioGain needs finite numeric windows");
  }
  const [start, end, db] = values as number[];
  if (end <= start || db < MIN_GAIN_DB || db > MAX_GAIN_DB) {
    throw new Error("Private opening requested lanes: audioGain window is reversed or outside the gain range");
  }
  return { start, end, db };
}

function assertGain(value: unknown): void {
  if (value == null) return;
  if (!Array.isArray(value)) throw new Error("Private opening requested lanes: audioGain must be a window list");
  const windows = value.map(gainWindow).sort((a, b) => a.start - b.start);
  for (let index = 1; index < windows.length; index++) {
    if (windows[index].start < windows[index - 1].end) {
      throw new Error("Private opening requested lanes: audioGain windows overlap");
    }
  }
}

/** Python separately validates the full request, exact program bounds, master and final audio.
 * Enhancement and gain run on that shared master before the opening excerpt is sliced.
 * This does not admit visual transitions/SFX, presenter profiles, downloaded runtimes,
 * or a malformed value merely because it is falsy. Keep the submitted plan untouched.
 */
export function assertOpeningFinishingMetadata(plan: Record<string, unknown>): void {
  assertEnhancement(plan.audioEnhance);
  assertGain(plan.audioGain);
}
