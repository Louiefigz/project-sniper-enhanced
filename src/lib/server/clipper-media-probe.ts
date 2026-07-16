import { execFile } from "node:child_process";
import type { FrameRate, VideoMetadata } from "@/lib/clipper/types";

interface ProbeStream {
  width?: number;
  height?: number;
  r_frame_rate?: string;
  avg_frame_rate?: string;
  duration?: string;
}

interface ProbePayload {
  streams?: ProbeStream[];
  format?: { duration?: string };
}

function positiveNumber(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function greatestCommonDivisor(a: number, b: number): number {
  let left = Math.abs(a);
  let right = Math.abs(b);
  while (right) [left, right] = [right, left % right];
  return left || 1;
}

export function parseFrameRate(value: unknown): FrameRate | null {
  if (typeof value !== "string") return null;
  const match = value.trim().match(/^(\d+)\/(\d+)$/);
  if (!match) return null;
  const numerator = Number(match[1]);
  const denominator = Number(match[2]);
  if (!Number.isSafeInteger(numerator) || !Number.isSafeInteger(denominator)) return null;
  if (numerator <= 0 || denominator <= 0) return null;
  const divisor = greatestCommonDivisor(numerator, denominator);
  return { numerator: numerator / divisor, denominator: denominator / divisor };
}

export function parseVideoProbe(raw: string): VideoMetadata {
  const payload = JSON.parse(raw) as ProbePayload;
  const stream = payload.streams?.[0];
  const width = positiveNumber(stream?.width);
  const height = positiveNumber(stream?.height);
  const duration = positiveNumber(stream?.duration) ?? positiveNumber(payload.format?.duration);
  const frameRate = parseFrameRate(stream?.r_frame_rate) ?? parseFrameRate(stream?.avg_frame_rate);
  if (!stream || !width || !height || !duration || !frameRate) {
    throw new Error("ffprobe did not return a valid duration, raster, and frame rate");
  }
  return { duration, frameRate, width, height };
}

function ffprobe(filePath: string): Promise<string> {
  const args = [
    "-v", "error", "-select_streams", "v:0",
    "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,duration:format=duration",
    "-of", "json", filePath,
  ];
  return new Promise((resolve, reject) => {
    execFile("ffprobe", args, { maxBuffer: 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) reject(new Error(stderr.trim() || error.message));
      else resolve(stdout);
    });
  });
}

export async function probeVideoMetadata(filePath: string): Promise<VideoMetadata> {
  return parseVideoProbe(await ffprobe(filePath));
}
