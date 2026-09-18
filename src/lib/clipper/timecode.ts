import type { FrameRate } from "@/lib/clipper/types";

const pad = (value: number, digits = 2) => value.toString().padStart(digits, "0");

function greatestCommonDivisor(a: number, b: number): number {
  let left = Math.abs(a);
  let right = Math.abs(b);
  while (right) [left, right] = [right, left % right];
  return left || 1;
}

function rateFromNumber(fps: number): FrameRate {
  if (!Number.isFinite(fps) || fps <= 0) throw new Error("Frame rate must be positive");
  if (Math.abs(fps - 23.976) < 0.002) return { numerator: 24000, denominator: 1001 };
  if (Math.abs(fps - 29.97) < 0.002) return { numerator: 30000, denominator: 1001 };
  if (Math.abs(fps - 59.94) < 0.002) return { numerator: 60000, denominator: 1001 };
  const scale = Number.isInteger(fps) ? 1 : 100000;
  const numerator = Math.round(fps * scale);
  const divisor = greatestCommonDivisor(numerator, scale);
  return { numerator: numerator / divisor, denominator: scale / divisor };
}

function validRate(rate: FrameRate): boolean {
  return Number.isSafeInteger(rate.numerator) && rate.numerator > 0
    && Number.isSafeInteger(rate.denominator) && rate.denominator > 0;
}

export function frameRateToNumber(rate: FrameRate): number {
  if (!validRate(rate)) throw new Error("Frame rate must be a positive rational");
  return rate.numerator / rate.denominator;
}

/**
 * FCPXML frame duration for an exact rational rate. Numeric input remains for
 * legacy callers, but Clipper export passes the ffprobe numerator/denominator.
 */
export function getFrameTimeFormat(input: number | FrameRate): {
  frameDuration: string;
  frameNum: number;
  frameDenom: number;
} {
  const rate = typeof input === "number" ? rateFromNumber(input) : input;
  if (!validRate(rate)) throw new Error("Frame rate must be a positive rational");
  return {
    frameDuration: `${rate.denominator}/${rate.numerator}s`,
    frameNum: rate.denominator,
    frameDenom: rate.numerator,
  };
}

export function secondsToTimecode(seconds: number, fps = 29.97): string {
  const safeSeconds = Number.isFinite(seconds) && seconds >= 0 ? seconds : 0;
  const wholeSeconds = Math.floor(safeSeconds);
  const hours = Math.floor(wholeSeconds / 3600);
  const minutes = Math.floor((wholeSeconds % 3600) / 60);
  const secs = wholeSeconds % 60;
  const safeFps = fps > 0 ? fps : 29.97;
  const fractional = safeSeconds - wholeSeconds;
  const frames = Math.floor(fractional * safeFps + 1e-4);
  return `${pad(hours)}:${pad(minutes)}:${pad(secs)}:${pad(frames)}`;
}
