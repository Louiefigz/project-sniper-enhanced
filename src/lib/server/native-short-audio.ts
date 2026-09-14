/** Explicit native finishing reuses the ordinary dialogue vocabulary and clock. */
import { exactKeys, objectValue } from "@/lib/producer/contracts/validation";
import type { AudioGainEntry } from "@/lib/producer/edit-plan";

export interface NativeShortAudio {
  schemaVersion: 1;
  rationale: string;
  audioEnhance?: { preset: "voice" | "voice-strong" | "voice-rnn" };
  audioGain?: Array<Pick<AudioGainEntry, "outStart" | "outEnd" | "dB">>;
}

/** Reject unavailable processors and malformed windows before native assembly. */
export function assertNativeShortAudio(value: NativeShortAudio | undefined, duration: number): void {
  if (value === undefined) return;
  if (!Number.isFinite(duration) || duration <= 0) throw new Error("Native audio requires a finite positive duration");
  const row = objectValue(value, "native audio finishing");
  exactKeys(row, ["schemaVersion", "rationale", "audioEnhance", "audioGain"],
    ["schemaVersion", "rationale"], "native audio finishing");
  if (value.schemaVersion !== 1 || typeof value.rationale !== "string"
      || value.rationale.trim().length < 3 || value.rationale.length > 2400 || value.rationale.includes("\0")) {
    throw new Error("Native audio finishing requires a source-specific rationale");
  }
  if (value.audioEnhance !== undefined) {
    const enhance = objectValue(value.audioEnhance, "native audio enhancement");
    exactKeys(enhance, ["preset"], ["preset"], "native audio enhancement");
    if (!["voice", "voice-strong", "voice-rnn"].includes(enhance.preset as string)) {
      throw new Error("Native audio supports only installed local voice cleanup presets");
    }
  }
  if (value.audioGain !== undefined) assertGain(value.audioGain, duration);
  if (!value.audioEnhance && !value.audioGain?.length) throw new Error("Native audio finishing has no processing decision");
}

function assertGain(windows: NativeShortAudio["audioGain"], duration: number): void {
  if (!Array.isArray(windows) || !windows.length || windows.length > 128) {
    throw new Error("Native gain requires 1–128 bounded output-time windows");
  }
  let end = 0;
  for (const window of windows) {
    const row = objectValue(window, "native gain window");
    exactKeys(row, ["outStart", "outEnd", "dB"], ["outStart", "outEnd", "dB"], "native gain window");
    if (![window.outStart, window.outEnd, window.dB].every(n => typeof n === "number" && Number.isFinite(n))
        || window.outStart < end || window.outEnd <= window.outStart || window.outEnd > duration
        || window.dB < -12 || window.dB > 12) {
      throw new Error("Native gain windows must be ordered, nonoverlapping and within the output with ±12 dB gain");
    }
    end = window.outEnd;
  }
}
