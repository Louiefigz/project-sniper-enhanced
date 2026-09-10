import { createHash } from "crypto";
import { closeSync, existsSync, openSync, readSync } from "fs";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import {
  DEFAULT_AUTO_EDIT_DELIVERY_POLICY,
  resolvedAutoEditDeliveryPolicy,
} from "@/lib/producer/auto-edit-delivery-policy";

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

function canonicalToken(value: unknown): string | undefined {
  if (Array.isArray(value)) {
    const rows = Array.from(
      value, (item) => canonicalToken(item) ?? "null");
    return `[${rows.join(",")}]`;
  }
  if (typeof value === "bigint") {
    throw new Error("canonical bigint is outside the JSON domain");
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)
        || (Number.isInteger(value) && !Number.isSafeInteger(value))) {
      throw new Error("canonical number is outside the cross-runtime domain");
    }
    return JSON.stringify(value);
  }
  if (value === null || typeof value === "string"
      || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value !== "object") return undefined;
  const entries = Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => compareCodePoints(left, right))
    .flatMap(([key, item]) => {
      const token = canonicalToken(item);
      return token === undefined ? [] : [`${JSON.stringify(key)}:${token}`];
    });
  return `{${entries.join(",")}}`;
}

/** Compact JSON with Python sort_keys=True Unicode code-point key order. */
export function canonicalJson(value: unknown): string {
  const token = canonicalToken(value);
  if (token === undefined) {
    throw new Error("canonical value is outside the JSON domain");
  }
  return token;
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
    ...requestValue
  } = ctx;
  void _runtimeDoctrine;
  void _runtimePipeline;
  void _runtimeTemplateUsage;
  void _runtimeBrainSessionId;
  void _runtimeBrainSessionEstablished;
  const request = { ...requestValue } as Partial<AutoEditCtx>;
  // The historical request identity omitted deliveryPolicy because every run
  // was hybrid. Keep that canonical spelling for the default so old durable
  // journals remain resumable; MP4-only remains a distinct identity.
  if (resolvedAutoEditDeliveryPolicy(request) === DEFAULT_AUTO_EDIT_DELIVERY_POLICY) {
    delete request.deliveryPolicy;
  }
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
