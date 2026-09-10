import type { ColorContext, ColorSource, ColorStart } from "@/lib/producer/color-diagnostic";
import { canonicalProducerDir } from "../../_lib/workspace";

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
export const SHA = /^[0-9a-f]{64}$/u;
export class ColorError extends Error {
  constructor(message: string, readonly status = 400, readonly code = "INVALID_COLOR_REQUEST") { super(message); }
}
export function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new ColorError("Expected an object");
  return value as Record<string, unknown>;
}
export function closed(value: Record<string, unknown>, keys: string[]): void {
  if (Object.keys(value).sort().join() !== [...keys].sort().join()) throw new ColorError("Unknown or missing request fields");
}
export function producerDir(value: unknown): string {
  if (typeof value !== "string" || value.length > 2048 || value.includes("\\") || value.split("/").includes("..")) {
    throw new ColorError("Choose a canonical Producer project");
  }
  try { return canonicalProducerDir(value); } catch { throw new ColorError("Choose a canonical Producer project"); }
}
export function parseStart(value: unknown): ColorStart {
  const row = object(value);
  closed(row, ["dir", "jobId", "expectedPlanHash", "expectedManifestHash", "contexts"]);
  if (typeof row.jobId !== "string" || !UUID.test(row.jobId)
      || typeof row.expectedPlanHash !== "string" || !SHA.test(row.expectedPlanHash)
      || typeof row.expectedManifestHash !== "string" || !SHA.test(row.expectedManifestHash)
      || !Array.isArray(row.contexts) || row.contexts.length < 1 || row.contexts.length > 8) {
    throw new ColorError("Invalid diagnostic token, parents, or source count");
  }
  return { ...row, dir: producerDir(row.dir) } as unknown as ColorStart;
}
function contextFields(value: unknown): ColorContext {
  const row = object(value);
  closed(row, ["sourceId", "sourceProfile", "cameraProfile", "historyState", "transformHistory", "lightingGroups"]);
  if (typeof row.sourceProfile !== "string" || !["unknown", "bt709-sdr", "log", "hdr"].includes(row.sourceProfile)
      || typeof row.historyState !== "string" || !["known", "unknown"].includes(row.historyState)
      || !(row.cameraProfile === null || typeof row.cameraProfile === "string" && row.cameraProfile.length <= 200)
      || !Array.isArray(row.transformHistory) || row.transformHistory.length > 20
      || row.transformHistory.some(item => typeof item !== "string" || !item.trim() || item.length > 500)
      || !Array.isArray(row.lightingGroups) || row.lightingGroups.length !== 1) {
    throw new ColorError("Invalid source profile, history, or lighting context");
  }
  return row as unknown as ColorContext;
}
/** First UI deliberately declares at most one whole-source group; no automatic grouping. */
export function validateContexts(contexts: ColorContext[], sources: ColorSource[]): void {
  if (contexts.length !== sources.length || new Set(contexts.map(row => row?.sourceId)).size !== sources.length) {
    throw new ColorError("Declare context for each retained source exactly once");
  }
  for (const raw of contexts) {
    const row = contextFields(raw), source = sources.find(item => item.id === row.sourceId);
    const group = object(row.lightingGroups[0]);
    closed(group, ["id", "start", "end", "intent", "description"]);
    if (!source || group.id !== "whole-source" || group.start !== 0 || group.end !== source.duration
        || typeof group.intent !== "string" || !["unknown", "neutral", "dark", "colored"].includes(group.intent)
        || typeof group.description !== "string" || group.description.length > 500) {
      throw new ColorError("This panel supports only an explicit whole-source lighting declaration");
    }
  }
}

/** Bound actual streamed bytes and elapsed body time, not Content-Length alone. */
export async function boundedBody(request: Request): Promise<unknown> {
  const reader = request.body?.getReader();
  if (!reader) throw new ColorError("A request body is required");
  const chunks: Uint8Array[] = []; let size = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let onAbort: (() => void) | undefined;
  const expired = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new ColorError("Request body timed out", 408)), 5000);
    onAbort = () => reject(new ColorError("Diagnostic request body was disconnected", 400));
    request.signal.addEventListener("abort", onAbort, { once: true });
    if (request.signal.aborted) onAbort();
  });
  try {
    while (true) {
      const { done, value } = await Promise.race([reader.read(), expired]);
      if (done) break;
      size += value.length;
      if (size > 64 * 1024) throw new ColorError("Request body exceeds 64 KiB", 413);
      chunks.push(value);
    }
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks)));
  } catch (error) {
    if (error instanceof ColorError) throw error;
    throw new ColorError("Request body must be valid UTF-8 JSON");
  } finally {
    clearTimeout(timer); if (onAbort) request.signal.removeEventListener("abort", onAbort);
    void reader.cancel().catch(() => {}).finally(() => { try { reader.releaseLock(); } catch {} });
  }
}
