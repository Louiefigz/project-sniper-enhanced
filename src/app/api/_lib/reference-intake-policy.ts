import { spawnSync } from "child_process";

export const MAX_REFERENCE_BYTES = BigInt(2 * 1024 ** 3);
export const MIN_FREE_BYTES = BigInt(5 * 1024 ** 3);
export const MAX_REFERENCE_DURATION_S = 3600;

export class ReferenceMediaError extends Error {}

export function localIntakePreflight(bytes: bigint, freeBytes: bigint): {
  status: number; message: string;
} | null {
  if (bytes > MAX_REFERENCE_BYTES) {
    return { status: 413, message: `reference exceeds the 2 GiB limit (${bytes} bytes)` };
  }
  if (freeBytes < MIN_FREE_BYTES) {
    return { status: 507, message: "at least 5 GiB of free workspace storage is required" };
  }
  return null;
}

export function parseReferenceProbe(value: unknown): {
  width: number; height: number; durationS: number;
} {
  const root = value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
  const format = root.format && typeof root.format === "object" && !Array.isArray(root.format)
    ? root.format as Record<string, unknown> : {};
  const streams = Array.isArray(root.streams) ? root.streams : [];
  const video = streams.find((stream) => stream && typeof stream === "object" &&
    (stream as Record<string, unknown>).codec_type === "video") as Record<string, unknown> | undefined;
  const width = Number(video?.width);
  const height = Number(video?.height);
  const durationS = Number(format.duration);
  if (!video || !Number.isFinite(width) || width <= 0 || !Number.isFinite(height) || height <= 0) {
    throw new ReferenceMediaError("copied reference has no readable video stream");
  }
  if (!Number.isFinite(durationS) || durationS <= 0) {
    throw new ReferenceMediaError("copied reference duration could not be verified");
  }
  if (durationS > MAX_REFERENCE_DURATION_S) {
    throw new ReferenceMediaError(
      `reference is ${durationS.toFixed(1)}s; maximum is ${MAX_REFERENCE_DURATION_S}s`,
    );
  }
  return { width, height, durationS };
}

export function validateCopiedReference(file: string): void {
  const result = spawnSync("ffprobe", ["-v", "error", "-select_streams", "v:0",
    "-show_entries", "stream=codec_type,width,height:format=duration", "-of", "json", file],
  { encoding: "utf8", timeout: 30_000 });
  if (result.error || result.status !== 0) {
    const detail = (result.stderr || result.error?.message || "ffprobe failed").trim();
    throw new ReferenceMediaError(`copied reference is not readable media: ${detail.slice(-300)}`);
  }
  let payload: unknown;
  try {
    payload = JSON.parse(result.stdout || "{}");
  } catch {
    throw new ReferenceMediaError("ffprobe returned malformed media metadata");
  }
  parseReferenceProbe(payload);
}
