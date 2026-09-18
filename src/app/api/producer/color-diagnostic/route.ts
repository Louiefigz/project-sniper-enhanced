import { NextRequest, NextResponse } from "next/server";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { descriptor } from "./files";
import { boundedBody, ColorError, parseStart, producerDir, UUID } from "./request";
import { jobStatus, startDiagnostic } from "./service";

export const runtime = "nodejs";
export const maxDuration = 300;
function reject(req: NextRequest): NextResponse | null {
  const failure = localApiRejection({ method: req.method, pathname: req.nextUrl.pathname,
    protocol: req.nextUrl.protocol, host: req.headers.get("host"), origin: req.headers.get("origin"),
    secFetchSite: req.headers.get("sec-fetch-site"), contentType: req.headers.get("content-type") });
  return failure ? NextResponse.json(failure, { status: failure.status }) : null;
}
function failure(error: unknown): NextResponse {
  if (error instanceof ColorError) return NextResponse.json({ error: error.message, code: error.code }, { status: error.status });
  return NextResponse.json({ error: "Private diagnostic could not be verified. No grade or draft was written; retain the attempt for recovery.", code: "COLOR_UNVERIFIED" }, { status: 409 });
}
export async function GET(req: NextRequest): Promise<Response> {
  const denied = reject(req); if (denied) return denied;
  try {
    const query = req.nextUrl.searchParams;
    if ([...query.keys()].some(key => key !== "dir" && key !== "jobId") || query.getAll("dir").length !== 1
        || query.getAll("jobId").length > 1) throw new ColorError("Invalid diagnostic query");
    const dir = producerDir(query.get("dir")), id = query.get("jobId");
    if (id !== null && !UUID.test(id)) throw new ColorError("Invalid diagnostic token");
    return NextResponse.json(id ? jobStatus(dir, id) : descriptor(dir), { headers: { "Cache-Control": "no-store" } });
  } catch (error) { return failure(error); }
}
export async function POST(req: NextRequest): Promise<Response> {
  const timing = { wall: Date.now(), mono: performance.now() };
  const denied = reject(req); if (denied) return denied;
  try {
    if (req.nextUrl.search) throw new ColorError("POST diagnostic queries are not supported");
    const result = await startDiagnostic(parseStart(await boundedBody(req)), undefined, timing);
    return result instanceof Response ? result : NextResponse.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch (error) { return failure(error); }
}
