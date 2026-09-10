import { NextRequest, NextResponse } from "next/server";
import path from "node:path";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { RequestFailure } from "../auto-edit/request-failure";
import { currentCutReview, currentCutReviewForMedia, cutReviewDescription, CutReviewError } from "./state";
import { cutMediaResponse } from "./media";

const IDENTITIES = ["requestHash", "executionKey", "receiptHash"] as const;

export function cutReviewRequestRejection(req: NextRequest): Response | null {
  const rejected = localApiRejection({ method: req.method, pathname: req.nextUrl.pathname,
    protocol: req.nextUrl.protocol, host: req.headers.get("host"), origin: req.headers.get("origin"),
    secFetchSite: req.headers.get("sec-fetch-site"), contentType: req.headers.get("content-type") });
  return rejected ? NextResponse.json({ ok: false, error: rejected.error }, { status: rejected.status }) : null;
}

function failure(error: unknown): Response {
  const known = error instanceof CutReviewError || error instanceof RequestFailure;
  return NextResponse.json({ ok: false, error: error instanceof Error ? error.message : "Cut preview is unavailable" },
    { status: known ? error.status : 409, headers: { "Cache-Control": "private, no-store" } });
}

/** Read-only descriptor or exact private media: no preview creation or cut acceptance. */
export async function cutReviewResponse(req: NextRequest, video: boolean): Promise<Response> {
  const rejected = cutReviewRequestRejection(req);
  if (rejected) return rejected;
  try {
    const query = req.nextUrl.searchParams;
    const allowed = video ? ["dir", ...IDENTITIES] : ["dir"];
    if ([...query.keys()].some((key) => !allowed.includes(key) || query.getAll(key).length !== 1)
        || allowed.some((key) => !query.has(key))) throw new CutReviewError("Unexpected or missing cut review query fields", 400);
    if (video && IDENTITIES.some((key) => !/^[a-f0-9]{64}$/.test(query.get(key)!))) {
      throw new CutReviewError("Cut preview request requires exact review identities", 400);
    }
    if (!video) return NextResponse.json(cutReviewDescription(currentCutReview(query.get("dir"))),
      { headers: { "Cache-Control": "private, no-store" } });
    // No preview movie read here: cutMediaResponse verifies the entire movie on
    // the same opened descriptor it streams, including for HEAD and short ranges.
    const review = currentCutReviewForMedia(query.get("dir"));
    if (query.get("requestHash") !== review.request.requestHash || query.get("executionKey") !== review.receipt.executionKey
        || query.get("receiptHash") !== review.receipt.receiptHash) throw new CutReviewError("The requested cut preview is stale");
    return await cutMediaResponse(req, { path: path.join(review.directory, "cut-preview.mp4"),
      sha256: review.receipt.media.sha256, sizeBytes: review.receipt.media.sizeBytes });
  } catch (error) { return failure(error); }
}
