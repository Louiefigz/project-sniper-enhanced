import { NextRequest, NextResponse } from "next/server";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { readGuidedOpeningStatus } from "@/lib/server/guided-opening-status";
import { canonicalProducerDir } from "../../auto-edit/request";

export const dynamic = "force-dynamic";
export const maxDuration = 60;
const HEADERS = { "Cache-Control": "private, no-store" };

/** Local read-only observation. Never launch, render, clear ownership, or approve a cut/opening. */
export async function GET(req: NextRequest): Promise<Response> {
  const rejected = localApiRejection({ method: req.method, pathname: req.nextUrl.pathname, protocol: req.nextUrl.protocol,
    host: req.headers.get("host"), origin: req.headers.get("origin"), secFetchSite: req.headers.get("sec-fetch-site"),
    contentType: req.headers.get("content-type") });
  if (rejected) return NextResponse.json({ ok: false, error: rejected.error }, { status: rejected.status, headers: HEADERS });
  const query = req.nextUrl.searchParams;
  if (req.nextUrl.search.length > 8192 || [...query.keys()].some((key) => key !== "dir") || query.getAll("dir").length !== 1
      || !query.get("dir") || query.get("dir")!.length > 4096) {
    return NextResponse.json({ ok: false, error: "Opening status requires exactly one bounded project directory" }, { status: 400, headers: HEADERS });
  }
  try { return NextResponse.json(readGuidedOpeningStatus(canonicalProducerDir(query.get("dir"))), { headers: HEADERS }); }
  catch { return NextResponse.json({ ok: false, error: "Current opening ownership or evidence could not be verified; no media is selectable" },
    { status: 409, headers: HEADERS }); }
}
