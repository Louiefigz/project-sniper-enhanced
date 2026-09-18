import { NextRequest, NextResponse } from "next/server";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { studioProducerDir } from "../paths";
import { StudioError } from "../model";
import { applyImport, prepareImport } from "./service";
import { ImportError, type ApplyInput } from "./model";
import { UUID } from "./files";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

async function boundedBody(req: NextRequest): Promise<Record<string, unknown>> {
  if (Number(req.headers.get("content-length") ?? 0) > 16_384) throw new ImportError("Studio import request is too large", 413, "INVALID_REQUEST");
  const reader = req.body?.getReader();
  if (!reader) throw new ImportError("Studio import requires a JSON body", 400, "INVALID_REQUEST");
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const chunk = await reader.read(); if (chunk.done) break;
      size += chunk.value.length;
      if (size > 16_384) throw new ImportError("Studio import request is too large", 413, "INVALID_REQUEST");
      chunks.push(chunk.value);
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  let body;
  try { body = JSON.parse(Buffer.concat(chunks).toString("utf8")); }
  catch { throw new ImportError("Invalid Studio import JSON", 400, "INVALID_REQUEST"); }
  if (!body || typeof body !== "object" || Array.isArray(body)) throw new ImportError("Expected a Studio import object", 400, "INVALID_REQUEST");
  return body;
}

function parseInput(body: Record<string, unknown>): { dir: string; input: ApplyInput | null } {
  const action = body.action;
  const allowed = action === "prepare" ? ["dir", "action"] : ["dir", "action", "proposalId", "expectedPlanHash", "expectedPlanVersion"];
  if (!["prepare", "apply"].includes(String(action)) || Object.keys(body).some((key) => !allowed.includes(key))) {
    throw new ImportError("Expected only prepare/apply import fields; arbitrary plans, paths and rendering are not supported", 400, "INVALID_REQUEST");
  }
  const dir = studioProducerDir(body.dir);
  if (action === "prepare") return { dir, input: null };
  if (typeof body.proposalId !== "string" || !UUID.test(body.proposalId)
      || typeof body.expectedPlanHash !== "string" || !/^[0-9a-f]{64}$/u.test(body.expectedPlanHash)
      || !Number.isSafeInteger(body.expectedPlanVersion) || Number(body.expectedPlanVersion) < 0) {
    throw new ImportError("Apply requires exact reviewed proposal, plan hash and version", 400, "INVALID_REQUEST");
  }
  return { dir, input: { proposalId: body.proposalId, expectedPlanHash: body.expectedPlanHash,
    expectedPlanVersion: Number(body.expectedPlanVersion) } };
}

/** Explicit POST preparation writes private evidence only; apply saves a draft, never a render. */
export async function POST(req: NextRequest): Promise<Response> {
  const rejected = localApiRejection({ method: req.method, pathname: req.nextUrl.pathname,
    protocol: req.nextUrl.protocol, host: req.headers.get("host"), origin: req.headers.get("origin"),
    secFetchSite: req.headers.get("sec-fetch-site"), contentType: req.headers.get("content-type") });
  if (rejected) return NextResponse.json({ ok: false, error: rejected.error, code: "LOCAL_REQUEST_REQUIRED" }, { status: rejected.status });
  try {
    const { dir, input } = parseInput(await boundedBody(req));
    const result = input ? await applyImport(dir, input) : await prepareImport(dir);
    return result instanceof Response ? result : NextResponse.json(result);
  } catch (error) {
    const known = error instanceof ImportError || error instanceof StudioError;
    const committed = error instanceof ImportError && error.committed;
    return NextResponse.json({ ok: false, error: error instanceof Error ? error.message : "Studio import failed",
      code: known ? error.code : "STUDIO_IMPORT_FAILED", ...(committed ? { committed: true, requiresRender: true } : {}) },
    { status: known ? error.status : 502 });
  }
}
