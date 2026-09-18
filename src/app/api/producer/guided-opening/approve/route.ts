import { NextRequest, NextResponse } from "next/server";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { approveGuidedOpening, GuidedOpeningApprovalError } from "@/lib/server/guided-opening-approval";
import { BoundedBodyError, readBoundedJsonBody } from "@/app/api/_lib/bounded-json-body";
import { RequestFailure } from "../../auto-edit/request-failure";

export const dynamic = "force-dynamic";
// Requalification re-runs the bounded read-only child; keep headroom beyond its protected allowance.
export const maxDuration = 600;
const HEADERS = { "Cache-Control": "private, no-store" }, LIMITS = { maximumBytes: 16_384, deadlineMs: 10_000 };
const BODY_FAILURES: Record<number, string> = { 413: "Opening approval request is too large", 408: "Opening approval request body timed out" };

/** Streams at most 16 KiB inside a 10 s deadline; an oversize or stalled body is refused before any parse. */
async function requestBody(req: NextRequest): Promise<Record<string, unknown>> {
  let body: unknown;
  try { body = await readBoundedJsonBody(req, LIMITS); }
  catch (error) {
    if (!(error instanceof BoundedBodyError)) throw error;
    throw new GuidedOpeningApprovalError(BODY_FAILURES[error.status] ?? "Opening approval requires valid UTF-8 JSON", error.status);
  }
  if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).sort().join(",") !== "dir,submission") {
    throw new GuidedOpeningApprovalError("Opening approval requires only dir and an exact submission", 400);
  }
  return body as Record<string, unknown>;
}

/** Explicit local human decision only; never launches a render, clears ownership, or approves body/delivery. */
export async function POST(req: NextRequest): Promise<Response> {
  const rejected = localApiRejection({ method: req.method, pathname: req.nextUrl.pathname, protocol: req.nextUrl.protocol,
    host: req.headers.get("host"), origin: req.headers.get("origin"), secFetchSite: req.headers.get("sec-fetch-site"),
    contentType: req.headers.get("content-type") });
  if (rejected) return NextResponse.json({ ok: false, error: rejected.error }, { status: rejected.status, headers: HEADERS });
  if (req.nextUrl.search) return NextResponse.json({ ok: false, error: "Opening approval does not accept query parameters" }, { status: 400, headers: HEADERS });
  try {
    const body = await requestBody(req);
    const value = await approveGuidedOpening({ dir: body.dir, submission: body.submission });
    return NextResponse.json({ ...value, openingApproved: true, bodyGenerated: false, deliveryApproved: false }, { headers: HEADERS });
  } catch (error) {
    const known = error instanceof GuidedOpeningApprovalError || error instanceof RequestFailure;
    return NextResponse.json({ ok: false, error: error instanceof Error ? error.message.slice(0, 2048) : "Opening approval could not be confirmed" },
      { status: known ? error.status : 409, headers: HEADERS });
  }
}
