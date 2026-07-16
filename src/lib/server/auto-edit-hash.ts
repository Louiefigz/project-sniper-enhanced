import { createHash } from "crypto";
import { closeSync, existsSync, openSync, readSync } from "fs";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";

const HASH_CHUNK_BYTES = 1024 * 1024;

function compareCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left, (value) => value.codePointAt(0)!);
  const rightPoints = Array.from(right, (value) => value.codePointAt(0)!);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    if (leftPoints[index] !== rightPoints[index]) {
      return leftPoints[index] - rightPoints[index];
    }
  }
  return leftPoints.length - rightPoints.length;
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => compareCodePoints(left, right))
      .map(([key, item]) => [key, stableValue(item)]),
  );
}

/** Compact JSON with Python sort_keys=True Unicode code-point key order. */
export function canonicalJson(value: unknown): string {
  return JSON.stringify(stableValue(value));
}

export function canonicalJsonSha256(value: unknown): string {
  return createHash("sha256").update(canonicalJson(value)).digest("hex");
}

export function autoEditRequestKey(ctx: AutoEditCtx): string {
  const {
    doctrine: _runtimeDoctrine,
    pipeline: _runtimePipeline,
    templateUsage: _runtimeTemplateUsage,
    brainSessionId: _runtimeBrainSessionId,
    brainSessionEstablished: _runtimeBrainSessionEstablished,
    ...request
  } = ctx;
  void _runtimeDoctrine;
  void _runtimePipeline;
  void _runtimeTemplateUsage;
  void _runtimeBrainSessionId;
  void _runtimeBrainSessionEstablished;
  return canonicalJsonSha256(request);
}

/** Constant-memory SHA-256 for plans, manifests, and multi-GB final videos. */
export function fileSha256(filePath: string): string | undefined {
  if (!existsSync(filePath)) return undefined;
  const fd = openSync(filePath, "r");
  const chunk = Buffer.allocUnsafe(HASH_CHUNK_BYTES);
  const hash = createHash("sha256");
  try {
    for (;;) {
      const count = readSync(fd, chunk, 0, chunk.length, null);
      if (count === 0) break;
      hash.update(chunk.subarray(0, count));
    }
  } finally {
    closeSync(fd);
  }
  return hash.digest("hex");
}
