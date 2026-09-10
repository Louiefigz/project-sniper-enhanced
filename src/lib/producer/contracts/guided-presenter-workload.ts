/** Whole-program declared input budget. Observed dimensions/bytes and execution remain separate obligations. */
import { objectValue } from "./validation";
import { parsePositiveRationalV1 } from "./positive-rational";

export const PRESENTER_GRAPH_PIXEL_LIMIT = 64 * 1024 * 1024;
export interface PresenterAssetCanvas { width: number; height: number }
export interface PresenterGraphWorkloadInput {
  target: unknown; clock: { frameRate: string; totalFrames: number }; graphicCount: number;
  captioned: boolean; presenterAssetCanvases: PresenterAssetCanvas[];
}

function integer(value: unknown, maximum: number, label: string, minimum = 1): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`Presenter workload ${label} needs bounded exact integer metadata`);
  }
  return value;
}

/** Both native canvases have identical pixel area; target acceptance is not a source observation. */
export function presenterNativeCanvas(value: unknown): PresenterAssetCanvas {
  const row = objectValue(value, "presenter target");
  const dimensions = row.mode === "longform" ? [1920, 1080] : row.mode === "short" ? [1080, 1920] : [];
  if (!dimensions.length || row.width !== dimensions[0] || row.height !== dimensions[1]) {
    throw new Error("Presenter profile requires exact native1920x1080 longform or1080x1920 short target");
  }
  return { width: dimensions[0], height: dimensions[1] };
}

function captionPages(clock: PresenterGraphWorkloadInput["clock"], captioned: boolean): number {
  integer(clock.totalFrames, 72_000, "total frames");
  if (typeof clock.frameRate !== "string" || !/^[1-9][0-9]{0,9}\/[1-9][0-9]{0,9}$/.test(clock.frameRate)) {
    throw new Error("Presenter workload requires the original canonical rational frame rate");
  }
  const [numerator, denominator] = clock.frameRate.split("/");
  parsePositiveRationalV1({ numerator, denominator });
  if (BigInt(numerator) < BigInt(denominator) || BigInt(numerator) > BigInt(denominator) * BigInt(60)) {
    throw new Error("Presenter workload frame rate is outside the existing1..60 class");
  }
  const pageFrames = BigInt(numerator) * BigInt(30) / BigInt(denominator);
  return captioned ? Number((BigInt(clock.totalFrames) + pageFrames - BigInt(1)) / pageFrames) : 0;
}

function assetPixels(value: PresenterAssetCanvas): number {
  const row = objectValue(value, "presenter asset canvas");
  const pixels = integer(row.width, 4096, "asset width") * integer(row.height, 4096, "asset height");
  if (pixels > 4096 * 2160) throw new Error("Presenter asset exceeds existing single-input pixel workload");
  return pixels;
}

/** Count full pages and repeated assets even when future/disjoint. Never deduplicate occurrences or clamp work. */
export function assertPresenterGraphWorkload(input: PresenterGraphWorkloadInput) {
  const canvas = presenterNativeCanvas(input.target);
  const graphics = integer(input.graphicCount, 128, "graphic count", 0);
  if (typeof input.captioned !== "boolean" || !Array.isArray(input.presenterAssetCanvases)
      || !input.presenterAssetCanvases.length || input.presenterAssetCanvases.length > 32) throw new Error("Presenter workload requires exact bounded occurrence/caption metadata");
  const pages = captionPages(input.clock, input.captioned);
  const occurrences = input.presenterAssetCanvases.map(assetPixels);
  const pixels = canvas.width * canvas.height * (1 + graphics + pages) + occurrences.reduce((sum, count) => sum + count, 0);
  if (graphics + pages + occurrences.length > 128 || pixels > PRESENTER_GRAPH_PIXEL_LIMIT) {
    throw new Error("Presenter combined graph exceeds existing64MiPixel workload; no requested inputs may be dropped");
  }
  return { scope: "declared-whole-program-input-metadata-not-observed-media-or-clearance" as const,
    basePixels: canvas.width * canvas.height, graphicCount: graphics, captionPageCount: pages,
    presenterOccurrenceCount: occurrences.length, inputPixels: pixels, limitPixels: PRESENTER_GRAPH_PIXEL_LIMIT };
}
