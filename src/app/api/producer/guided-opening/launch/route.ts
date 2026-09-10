import { NextRequest, NextResponse } from "next/server";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { launchGuidedOpening } from "@/lib/server/guided-opening-launcher";
import { readGuidedOpeningLaunchStatus } from "@/lib/server/guided-opening-launch-status";
import { BoundedBodyError, readBoundedJsonBody } from "@/app/api/_lib/bounded-json-body";
import { parsePrepareGuidedOpening } from "@/lib/producer/contracts/guided-opening-v1";
import { canonicalProducerDir } from "../../auto-edit/request";
import { RequestFailure } from "../../auto-edit/request-failure";

export const dynamic = "force-dynamic";
export const maxDuration = 60;
const HEADERS = { "Cache-Control": "private, no-store" };

function localRejection(req: NextRequest): Response | null {
  const rejected = localApiRejection({ method: req.method, pathname: req.nextUrl.pathname, protocol: req.nextUrl.protocol,
    host: req.headers.get("host"), origin: req.headers.get("origin"), secFetchSite: req.headers.get("sec-fetch-site"), contentType: req.headers.get("content-type") });
  return rejected ? NextResponse.json({ ok: false, error: rejected.error }, { status: rejected.status, headers: HEADERS }) : null;
}

function failure(error: unknown): Response {
  const status = error instanceof RequestFailure || error instanceof BoundedBodyError ? error.status : 409;
  return NextResponse.json({ ok: false, error: error instanceof Error ? error.message.slice(0, 2048) : "Opening launch could not be verified" }, { status, headers: HEADERS });
}

/** Cheap local journal metadata only; never source/media verification, generation or approval. */
export async function GET(req: NextRequest): Promise<Response> {
  const rejected = localRejection(req); if (rejected) return rejected;
  const query = req.nextUrl.searchParams;
  if (req.nextUrl.search.length > 8192 || [...query.keys()].some((key) => key !== "dir") || query.getAll("dir").length !== 1
      || !query.get("dir") || query.get("dir")!.length > 4096) {
    return failure(new RequestFailure("Opening launch status requires exactly one bounded project directory", 400));
  }
  try { return NextResponse.json(readGuidedOpeningLaunchStatus(canonicalProducerDir(query.get("dir"))), { headers: HEADERS }); }
  catch (error) { return failure(error); }
}

/** Explicit same-origin action only. A recorded request is not process liveness or approval. */
export async function POST(req: NextRequest): Promise<Response> {
  const rejected = localRejection(req); if (rejected) return rejected;
  if (req.nextUrl.search) return failure(new RequestFailure("Opening launch does not accept query parameters", 400));
  try {
    const value = await readBoundedJsonBody(req, { maximumBytes: 16_384, deadlineMs: 10_000 });
    if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join(",") !== "dir,submission") {
      throw new RequestFailure("Opening launch requires only dir and an exact submission", 400);
    }
    const body = value as Record<string, unknown>; let submission;
    try { submission = parsePrepareGuidedOpening(body.submission); }
    catch { throw new RequestFailure("Opening launch submission is malformed", 400); }
    const result = await launchGuidedOpening({ dir: canonicalProducerDir(body.dir), submission });
    return NextResponse.json(result, { status: 202, headers: HEADERS });
  } catch (error) { return failure(error); }
}
