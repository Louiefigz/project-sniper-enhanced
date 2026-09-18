import { NextRequest, NextResponse } from "next/server";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { StudioError } from "./model";
import { studioProducerDir } from "./paths";
import { getStudioStatus, openStudio } from "./service";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

function rejectRequest(req: NextRequest): Response | null {
  const rejected = localApiRejection({ method: req.method, pathname: req.nextUrl.pathname,
    protocol: req.nextUrl.protocol, host: req.headers.get("host"), origin: req.headers.get("origin"),
    secFetchSite: req.headers.get("sec-fetch-site"), contentType: req.headers.get("content-type") });
  return rejected ? NextResponse.json({ ok: false, error: rejected.error,
    code: "LOCAL_REQUEST_REQUIRED" }, { status: rejected.status }) : null;
}

function failure(error: unknown): Response {
  const known = error instanceof StudioError;
  return NextResponse.json({ ok: false, error: error instanceof Error ? error.message : "Studio request failed",
    code: known ? error.code : "STUDIO_FAILED" }, { status: known ? error.status : 502 });
}

/** Read-only inspection: no preview servers, projection writes, sync or renders. */
export async function GET(req: NextRequest): Promise<Response> {
  const rejected = rejectRequest(req);
  if (rejected) return rejected;
  try {
    return NextResponse.json(await getStudioStatus(studioProducerDir(req.nextUrl.searchParams.get("dir"))));
  } catch (error) { return failure(error); }
}

/** Open/reuse only. No force, plan edits, sync, assemble or render operation exists here. */
export async function POST(req: NextRequest): Promise<Response> {
  const rejected = rejectRequest(req);
  if (rejected) return rejected;
  const body = await req.json().catch(() => null);
  if (!body || typeof body !== "object" || Array.isArray(body)
      || Object.keys(body).some((key) => key !== "dir")) {
    return failure(new StudioError("Expected only {dir}; force, sync and render are not supported", 400, "INVALID_REQUEST"));
  }
  try {
    const result = await openStudio(studioProducerDir(body.dir));
    return result instanceof Response ? result : NextResponse.json(result);
  } catch (error) { return failure(error); }
}
