import { NextRequest } from "next/server";
import { parseHumanCutRetry, parseHumanCutSubmission,
  type HumanCutRetryV1, type HumanCutSubmissionV1 } from "@/lib/producer/contracts/human-cut-acceptance";
import { canonicalProducerDir } from "../auto-edit/request";
import { CutReviewError } from "./state";

const MAXIMUM = 16_384;

async function requestBytes(req: NextRequest): Promise<Buffer> {
  if (Number(req.headers.get("content-length")) > MAXIMUM) throw new CutReviewError("Cut acceptance request is too large", 413);
  const reader = req.body?.getReader();
  if (!reader) throw new CutReviewError("Cut acceptance requires a JSON body", 400);
  const chunks: Uint8Array[] = [];
  const signal = AbortSignal.any([req.signal, AbortSignal.timeout(5000)]);
  const canceled = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener("abort", canceled, { once: true });
  let size = 0;
  try {
    for (;;) {
      signal.throwIfAborted();
      const chunk = await reader.read();
      signal.throwIfAborted();
      if (chunk.done) return Buffer.concat(chunks);
      size += chunk.value.length;
      if (size > MAXIMUM) throw new CutReviewError("Cut acceptance request is too large", 413);
      chunks.push(chunk.value);
    }
  } finally {
    signal.removeEventListener("abort", canceled);
    await reader.cancel().catch(() => {}); reader.releaseLock();
  }
}

export interface CutAcceptanceInput {
  dir: string;
  submission: HumanCutSubmissionV1 | HumanCutRetryV1;
}

/** Closed decision envelope; no caller timestamps, plans, source paths or policy overrides. */
export async function cutAcceptanceInput(req: NextRequest): Promise<CutAcceptanceInput> {
  if (req.nextUrl.search) throw new CutReviewError("Cut acceptance does not accept query parameters", 400);
  const raw = await requestBytes(req);
  let body: unknown;
  try { body = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)); }
  catch { throw new CutReviewError("Cut acceptance requires valid UTF-8 JSON", 400); }
  if (!body || typeof body !== "object" || Array.isArray(body)
      || Object.keys(body).sort().join(",") !== "dir,submission") {
    throw new CutReviewError("Cut acceptance requires only dir and an exact submission", 400);
  }
  const value = body as Record<string, unknown>;
  const submitted = value.submission as Record<string, unknown> | null;
  let submission: HumanCutSubmissionV1 | HumanCutRetryV1;
  try { submission = submitted?.operation === "retry-continuation"
    ? parseHumanCutRetry(submitted) : parseHumanCutSubmission(submitted); }
  catch (error) { throw new CutReviewError(error instanceof Error ? error.message : "Invalid cut decision", 400); }
  return { dir: canonicalProducerDir(value.dir), submission };
}
