import type { GuidedOpeningMediaDescriptorV1 } from "./contracts/guided-opening-status-v1";
import { parsePositiveRationalV1 } from "./contracts/positive-rational";
import { exactKeys, objectValue, sha256, stringValue } from "./contracts/validation";

const KEYS = ["url", "mediaSha256", "sizeBytes", "width", "height", "frameRate", "videoFrames",
  "startFrame", "endFrameExclusive", "audioSamples"];

/** Browser bounds/clock agreement, not proof of source bytes or execution. */
function frameRate(value: unknown) {
  const text = stringValue(value, "opening frame rate", 21);
  const [numerator, denominator, extra] = text.split("/");
  if (extra !== undefined || !denominator) throw new Error("Opening frame rate is malformed");
  const rate = parsePositiveRationalV1({ numerator, denominator });
  const fps = Number(rate.numerator) / Number(rate.denominator);
  if (fps < 1 || fps > 60) throw new Error("Opening frame rate is outside its supported bounds");
  return rate;
}

/** Same ties-to-even absolute 48kHz boundary used by the source-derived master. */
function sampleBoundary(frame: number, rate: ReturnType<typeof frameRate>): number {
  const scaled = BigInt(frame) * BigInt(48_000) * BigInt(rate.denominator);
  const divisor = BigInt(rate.numerator), quotient = scaled / divisor, twiceRemainder = (scaled % divisor) * BigInt(2);
  const up = twiceRemainder > divisor || (twiceRemainder === divisor && quotient % BigInt(2) !== BigInt(0));
  return Number(quotient + (up ? BigInt(1) : BigInt(0)));
}

function boundedInteger(value: unknown, minimum: number, maximum: number): boolean {
  return Number.isSafeInteger(value) && Number(value) >= minimum && Number(value) <= maximum;
}

function mediaUrl(value: unknown, expected: Record<string, string>): void {
  const text = stringValue(value, "opening media URL", 8192);
  if (!text.startsWith("/api/producer/guided-opening/media?")) throw new Error("Opening media URL is not the guarded local route");
  const url = new URL(text, "http://localhost");
  if (url.hash || [...url.searchParams].length !== 4 || Object.entries(expected).some(([key, field]) =>
    url.searchParams.getAll(key).length !== 1 || url.searchParams.get(key) !== field)) {
    throw new Error("Opening playback URL does not match its exact selection");
  }
}

function descriptor(value: unknown, context: { dir: string; selectionHash: string; range: "core" | "review" }) {
  const row = objectValue(value, "opening media descriptor");
  exactKeys(row, KEYS, KEYS, "opening media descriptor");
  const mediaSha256 = sha256(row.mediaSha256, "opening media SHA-256"), rate = frameRate(row.frameRate);
  if (!boundedInteger(row.sizeBytes, 1, Number.MAX_SAFE_INTEGER)
      || !boundedInteger(row.width, 2, 16_384) || !boundedInteger(row.height, 2, 16_384)
      || row.startFrame !== 0 || !boundedInteger(row.endFrameExclusive, 1, 72_000)
      || row.videoFrames !== row.endFrameExclusive
      || row.audioSamples !== sampleBoundary(Number(row.endFrameExclusive), rate)) {
    throw new Error("Opening media geometry or exact picture/audio clock is inconsistent");
  }
  mediaUrl(row.url, { dir: context.dir, selectionHash: context.selectionHash, mediaSha256, range: context.range });
  return row as unknown as GuidedOpeningMediaDescriptorV1;
}

export function parseOpeningMedia(value: unknown, context: { dir: string; selectionHash: string }) {
  const row = objectValue(value, "opening media"); exactKeys(row, ["core", "review"], ["core", "review"], "opening media");
  const core = descriptor(row.core, { ...context, range: "core" });
  const review = descriptor(row.review, { ...context, range: "review" });
  if (core.width !== review.width || core.height !== review.height || core.frameRate !== review.frameRate
      || core.endFrameExclusive > review.endFrameExclusive) throw new Error("Opening context does not contain the same core frame clock");
  return { core, review };
}

/** Metadata screening only; a browser loading successfully is not human review. */
export function openingPlaybackMatches(media: GuidedOpeningMediaDescriptorV1, observed: {
  duration: number; width: number; height: number;
}): boolean {
  const [numerator, denominator] = media.frameRate.split("/").map(Number);
  const expected = media.videoFrames * denominator / numerator;
  return Number.isFinite(observed.duration) && Math.abs(observed.duration - expected) <= 0.1
    && observed.width === media.width && observed.height === media.height;
}

export function openingRangeSeconds(media: GuidedOpeningMediaDescriptorV1): number {
  const [numerator, denominator] = media.frameRate.split("/").map(Number);
  return media.videoFrames * denominator / numerator;
}
