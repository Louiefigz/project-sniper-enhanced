import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { guardProjectMutation, mutationProjectRoot } from "../../_lib/project-mutation";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { prepareSceneReviewRequest } from "./request";
import { runSceneReview } from "./runner";

export const dynamic = "force-dynamic";
export const maxDuration = 600;

function localRejection(req: NextRequest): Response | null {
  const rejected = localApiRejection({
    method: req.method,
    pathname: req.nextUrl.pathname,
    protocol: req.nextUrl.protocol,
    host: req.headers.get("host"),
    origin: req.headers.get("origin"),
    secFetchSite: req.headers.get("sec-fetch-site"),
    contentType: req.headers.get("content-type"),
  });
  return rejected
    ? NextResponse.json({ error: rejected.error }, { status: rejected.status })
    : null;
}

function errorResponse(error: unknown, status = 400): Response {
  const message = error instanceof Error ? error.message : String(error);
  const canceled = /canceled/u.test(message);
  return NextResponse.json(
    { error: message, code: canceled ? "SCENE_REVIEW_CANCELED" : "SCENE_REVIEW_FAILED" },
    { status: canceled ? 499 : status },
  );
}

/** Render one changed scene unit into an isolated review artifact. */
export async function POST(req: NextRequest): Promise<Response> {
  const rejected = localRejection(req);
  if (rejected) return rejected;
  let prepared;
  try {
    const body = await req.json() as Record<string, unknown>;
    prepared = prepareSceneReviewRequest(body);
  } catch (error) {
    return errorResponse(error);
  }
  const guarded = guardProjectMutation({
    projectRoot: mutationProjectRoot(prepared.dir),
    producerDir: prepared.dir,
    operation: `rendering private scene review ${prepared.requestId}`,
  });
  if (guarded.response) return guarded.response;
  try {
    return NextResponse.json(await runSceneReview(prepared, req.signal));
  } catch (error) {
    return errorResponse(error, 500);
  } finally {
    guarded.lease.release();
  }
}
